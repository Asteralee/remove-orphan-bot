import os
import requests
import time
import re
import random

API_URL = "https://simple.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "OrphanCleanupBot/1.0"}

MIN_BACKLINKS = 2
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "10"))
MAX_BATCH = 30  # safety cap
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
SLEEP_TIME = int(os.getenv("SLEEP_BETWEEN", "2"))

WORKLIST_TITLE = os.getenv(
    "WORKLIST_TITLE",
    "User:AsteraBot/Pages to fix"
)

CATEGORY_NAME = os.getenv("CATEGORY_NAME", "All orphaned articles")

def login_and_get_session(username, password):
    session = requests.Session()
    session.headers.update(HEADERS)

    # Get login token
    r1 = session.get(API_URL, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    })
    token = r1.json()["query"]["tokens"]["logintoken"]

    # Login
    r2 = session.post(API_URL, data={
        "action": "login",
        "lgname": username,
        "lgpassword": password,
        "lgtoken": token,
        "format": "json"
    })

    if r2.json()["login"]["result"] != "Success":
        raise RuntimeError("Login failed")

    print(f"Logged in as {username}")
    return session

def get_csrf_token(session):
    r = session.get(API_URL, params={
        "action": "query",
        "meta": "tokens",
        "format": "json"
    })
    return r.json()["query"]["tokens"]["csrftoken"]

BULLET_RE = re.compile(r'^\* \[\[(.+?)\]\]\s*$', re.M)

def fetch_worklist(session, title):
    r = session.get(API_URL, params={
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": title,
        "format": "json"
    })
    pages = r.json()["query"]["pages"]
    page = next(iter(pages.values()))
    if "revisions" not in page:
        return ""
    return page["revisions"][0]["slots"]["main"]["*"]

def extract_items(text):
    return BULLET_RE.findall(text)

def remove_item(text, title):
    return re.sub(
        rf'^\* \[\[{re.escape(title)}\]\]\s*\n?',
        '',
        text,
        flags=re.M
    )

def save_worklist(session, text, title, summary, token):
    r = session.post(API_URL, data={
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": token,
        "bot": True,
        "format": "json"
    })
    if "error" in r.json():
        print(f"Worklist edit failed: {r.json()['error']}")
    else:
        print("Worklist updated successfully")

def get_page_text(session, title):
    r = session.get(API_URL, params={
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": title,
        "format": "json"
    })
    pages = r.json()["query"]["pages"]
    page = next(iter(pages.values()))
    if "revisions" not in page:
        raise RuntimeError(f"No revisions found for {title}")
    return page["revisions"][0]["slots"]["main"]["*"]

def remove_orphan_template(text):
    text = re.sub(
        r"\{\{\s*[Oo]rphan\b[^}]*\}\}\s*",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip() + "\n"

def save_page(session, title, text, token):
    r = session.post(API_URL, data={
        "action": "edit",
        "title": title,
        "text": text,
        "token": token,
        "summary": "Bot: removing {{orphan}} — article has 2+ incoming links",
        "minor": True,
        "bot": True,
        "format": "json"
    })
    result = r.json()
    if "error" in result:
        print(f"{title}: edit failed ({result['error']})")
    else:
        print(f"{title}: edit successful")

def has_2plus_nonredirect_backlinks(session, title):
    found = 0
    cont = {}
    while True:
        r = session.get(API_URL, params={
            "action": "query",
            "list": "backlinks",
            "bltitle": title,
            "blnamespace": 0,
            "blfilterredir": "nonredirects",
            "bllimit": "max",
            "format": "json",
            **cont
        }).json()
        found += len(r.get("query", {}).get("backlinks", []))
        if found >= MIN_BACKLINKS:
            return True
        if "continue" not in r:
            return False
        cont = r["continue"]

def process_article(session, csrf_token, title):
    """Remove orphan template if present, safe for dry-run."""
    try:
        text = get_page_text(session, title)
    except Exception as e:
        print(f"{title}: error fetching text ({e})")
        return False

    # Verify backlinks before editing
    if not has_2plus_nonredirect_backlinks(session, title):
        print(f"{title}: fewer than {MIN_BACKLINKS} backlinks, skipping")
        return False

    new_text = remove_orphan_template(text)

    if new_text == text:
        print(f"{title}: no orphan template found")
        return False

    if DRY_RUN:
        print(f"[DRY RUN] Would save changes to {title}")
        return True

    save_page(session, title, new_text, csrf_token)
    return True

def main():
    username = os.getenv("WIKI_USER")
    password = os.getenv("WIKI_PASS")

    if not username or not password:
        raise RuntimeError("Missing WIKI_USER or WIKI_PASS")

    session = login_and_get_session(username, password)
    csrf = get_csrf_token(session)

    # Fetch worklist page
    text = fetch_worklist(session, WORKLIST_TITLE)
    items = extract_items(text)

    if not items:
        print("Worklist empty — exiting.")
        return

    # Pick batch
    batch_size = min(BATCH_SIZE, MAX_BATCH, len(items))
    batch = items[:batch_size]
    random.shuffle(batch)
    print(f"Processing batch of {len(batch)} articles")

    new_text = text
    processed = []

    for title in batch:
        ok = process_article(session, csrf, title)
        if ok:
            processed.append(title)
            new_text = remove_item(new_text, title)
        time.sleep(SLEEP_TIME)

    remaining = len(items) - len(processed)

    if DRY_RUN:
        print("\n[DRY RUN] Would remove templates from:")
        for t in processed:
            print(f" - {t}")
        print(f"Remaining in worklist: {remaining}")
        print("Dry-run mode enabled, no edits made.")
        return

    if processed:
        summary = f"Bot: processed {len(processed)} articles; {remaining} remaining"
        save_worklist(session, new_text, WORKLIST_TITLE, summary, csrf)

if __name__ == "__main__":
    main()
