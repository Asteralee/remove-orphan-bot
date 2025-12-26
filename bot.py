import os
import requests
import time
import random
import re

API_URL = "https://simple.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "OrphanCleanupBot/1.0"}

MIN_BACKLINKS = 2
NUM_PAGES = int(os.getenv("NUM_PAGES", "10"))
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


def get_pages_from_category(session, category):
    pages = []
    cont = {}

    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmnamespace": 0,
            "cmlimit": "max",
            "format": "json",
            **cont
        }

        r = session.get(API_URL, params=params).json()
        pages.extend(r.get("query", {}).get("categorymembers", []))

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
        backlinks.update(bl["title"] for bl in r.get("query", {}).get("backlinks", []))

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
    text = re.sub(r"\{\{[Oo]rphan(?:\|[^}]*)?\}\}", "", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text


def save_page(session, title, text, token):
    r = session.post(API_URL, data={
        "action": "edit",
        "title": title,
        "text": text,
        "token": token,
        "summary": "Bot: removing {{orphan}} — article has 2+ incoming links",
        "minor": True,
        "format": "json"
    })

    print(f"Edit result for {title}: {r.json()}")
    return r


def main():
    username = os.getenv("WIKI_USER")
    password = os.getenv("WIKI_PASS")

    if not username or not password:
        raise RuntimeError("Missing WIKI_USER or WIKI_PASS")

    session = login_and_get_session(username, password)
    csrf = get_csrf_token(session)

    category_pages = get_pages_from_category(session, CATEGORY_NAME)
    print(f"Found {len(category_pages)} pages in Category:{CATEGORY_NAME}")

    if not category_pages:
        print("No pages found — exiting.")
        return

    pages_to_check = (
        random.sample(category_pages, NUM_PAGES)
        if len(category_pages) > NUM_PAGES
        else category_pages
    )

    print(f"Checking {len(pages_to_check)} random pages\n")

    for page in pages_to_check:
        title = page["title"]
        backlinks = count_mainspace_backlinks(session, title)

        print(f"{title}: {backlinks} backlinks")

        if backlinks >= MIN_BACKLINKS:
            print(" → Eligible for orphan removal")

            if not DRY_RUN:
                text = get_page_text(session, title)
                new_text = remove_orphan_template(text)

                if new_text != text:
                    save_page(session, title, new_text, csrf)

        time.sleep(SLEEP_TIME)


if __name__ == "__main__":
    main()
