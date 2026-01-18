import os
import requests
import time
import re
import random

API_URL = "https://test.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "OrphanCleanupBot/1.0"}

MIN_BACKLINKS = 2
NUM_PAGES = int(os.getenv("NUM_PAGES", "20"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
SLEEP_TIME = 2

CATEGORY_NAME = os.getenv("CATEGORY_NAME", "All orphaned articles")


def login_and_get_session(username, password):
    session = requests.Session()
    session.headers.update(HEADERS)

    r1 = session.get(API_URL, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    })
    token = r1.json()["query"]["tokens"]["logintoken"]

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


def has_2plus_nonredirect_backlinks(session, title):
    """
    Return True if the page has at least MIN_BACKLINKS
    non-redirect backlinks from mainspace.
    Stops early to minimize API calls.
    """
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


def get_pages_with_2plus_backlinks(session, category, max_pages=None):
    """
    Return pages in the given category that truly have
    2 or more non-redirect mainspace backlinks.
    """
    eligible = set()
    cont = {}

    while True:
        params = {
            "action": "query",
            "generator": "categorymembers",
            "gcmtitle": f"Category:{category}",
            "gcmnamespace": 0,
            "gcmlimit": "50",

            # Fast candidate filter
            "prop": "linkshere",
            "lhnamespace": 0,
            "lhlimit": MIN_BACKLINKS,
            "lhfilterredir": "nonredirects",

            "format": "json",
            **cont
        }

        r = session.get(API_URL, params=params).json()
        pages = r.get("query", {}).get("pages", {})

        for page in pages.values():
            title = page["title"]

            # Must appear to have at least MIN_BACKLINKS
            if len(page.get("linkshere", [])) < MIN_BACKLINKS:
                continue

            # Accurate verification
            if has_2plus_nonredirect_backlinks(session, title):
                eligible.add(title)

                if max_pages and len(eligible) >= max_pages:
                    return list(eligible)

        if "continue" not in r:
            break
        cont = r["continue"]

    return list(eligible)


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
        raise RuntimeError("No revisions found")

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
    return r


def main():
    username = os.getenv("WIKI_USER")
    password = os.getenv("WIKI_PASS")

    if not username or not password:
        raise RuntimeError("Missing WIKI_USER or WIKI_PASS")

    session = login_and_get_session(username, password)
    csrf = get_csrf_token(session)

    print(
        f"Scanning category '{CATEGORY_NAME}' "
        f"for pages with ≥{MIN_BACKLINKS} non-redirect backlinks...\n"
    )

    eligible_pages = get_pages_with_2plus_backlinks(
        session,
        CATEGORY_NAME,
        max_pages=NUM_PAGES
    )

    if not eligible_pages:
        print("No eligible pages found — exiting.")
        return

    print(f"Found {len(eligible_pages)} eligible pages to process.\n")

    random.shuffle(eligible_pages)

    for title in eligible_pages:
        if DRY_RUN:
            print(f"[DRY RUN] Would remove {{orphan}} from {title}")
            continue

        try:
            text = get_page_text(session, title)
        except Exception as e:
            print(f"{title}: error fetching text ({e})")
            continue

        new_text = remove_orphan_template(text)

        if new_text == text:
            print(f"{title}: no orphan template found")
            continue

        save_page(session, title, new_text, csrf)
        time.sleep(SLEEP_TIME)


if __name__ == "__main__":
    main()
