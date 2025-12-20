import os
import requests
import time
import random

API_URL = "https://test.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "OrphanCleanupBot/0.2 (testwiki)"}

MIN_BACKLINKS = 3
NUM_PAGES = int(os.getenv("NUM_PAGES", "10"))  # number of pages to process per run
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
SLEEP_TIME = 2   # seconds between edits


def login_and_get_session(username, password):
    session = requests.Session()
    session.headers.update(HEADERS)

    r1 = session.get(API_URL, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    })
    login_token = r1.json()["query"]["tokens"]["logintoken"]

    r2 = session.post(API_URL, data={
        "action": "login",
        "lgname": username,
        "lgpassword": password,
        "lgtoken": login_token,
        "format": "json"
    })

    if r2.json()["login"]["result"] != "Success":
        raise Exception("Login failed")

    print(f"Logged in as {username}")
    return session


def get_csrf_token(session):
    r = session.get(API_URL, params={
        "action": "query",
        "meta": "tokens",
        "format": "json"
    })
    return r.json()["query"]["tokens"]["csrftoken"]


def get_orphaned_pages(session):
    pages = []
    cont = {}

    while True:
        params = {
            "action": "query",
            "list": "embeddedin",
            "eititle": "Template:Orphan",
            "einamespace": 0,
            "eilimit": "max",
            "format": "json",
            **cont
        }

        r = session.get(API_URL, params=params).json()
        pages.extend(r["query"]["embeddedin"])

        if "continue" not in r:
            break
        cont = r["continue"]

    return pages


def count_mainspace_backlinks(session, title):
    backlinks = set()
    cont = {}

    while True:
        params = {
            "action": "query",
            "list": "backlinks",
            "bltitle": title,
            "blnamespace": 0,
            "bllimit": "max",
            "format": "json",
            **cont
        }

        r = session.get(API_URL, params=params).json()
        backlinks.update(bl["title"] for bl in r["query"]["backlinks"])

        if "continue" not in r:
            break
        cont = r["continue"]

    return len(backlinks)


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
    return page["revisions"][0]["slots"]["main"]["*"]


def remove_orphan_template(text):
    for variant in ("{{Orphan}}", "{{orphan}}"):
        text = text.replace(variant, "")
    return text


def save_page(session, title, text, token):
    session.post(API_URL, data={
        "action": "edit",
        "title": title,
        "text": text,
        "token": token,
        "summary": "Bot: removing {{orphan}} — article has 3+ incoming links",
        "minor": True,
        "format": "json"
    })


def main():
    username = os.getenv("WIKI_USER")
    password = os.getenv("WIKI_PASS")
    if not username or not password:
        raise Exception("Missing WIKI_USER or WIKI_PASS")

    session = login_and_get_session(username, password)
    csrf_token = get_csrf_token(session)

    orphan_pages = get_orphaned_pages(session)
    print(f"Found {len(orphan_pages)} orphan-tagged pages")

    # Count backlinks and filter eligible pages
    eligible_pages = []
    for p in orphan_pages:
        title = p["title"]
        backlinks = count_mainspace_backlinks(session, title)
        if backlinks >= MIN_BACKLINKS:
            eligible_pages.append({"title": title, "backlinks": backlinks})
        print(f"{title}: {backlinks} backlinks")
        time.sleep(0.5)  # gentle throttling

    print(f"\nEligible pages for orphan removal: {len(eligible_pages)}")

    # Pick random subset
    if len(eligible_pages) > NUM_PAGES:
        pages_to_process = random.sample(eligible_pages, NUM_PAGES)
    else:
        pages_to_process = eligible_pages

    print(f"Processing {len(pages_to_process)} pages this run\n")

    # Process selected pages
    for p in pages_to_process:
        title = p["title"]
        print(f"Processing {title} ({p['backlinks']} backlinks)")

        if not DRY_RUN:
            text = get_page_text(session, title)
            new_text = remove_orphan_template(text)
            if new_text != text:
                save_page(session, title, new_text, csrf_token)
                print("  → {{orphan}} removed")

        time.sleep(SLEEP_TIME)


if __name__ == "__main__":
    main()
