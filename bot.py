import os
import requests
import time
import random
import re

API_URL = "https://test.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "OrphanCleanupBot/0.4 (testwiki)"}

MIN_BACKLINKS = 3 
NUM_PAGES = int(os.getenv("NUM_PAGES", "10"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
SLEEP_TIME = 2  # seconds between API requests


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
        raise Exception("Login failed...sorry!")

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
    "list": "categorymembers",
    "cmtitle": "Category:All_orphaned_articles",  # replace with actual category name
    "cmnamespace": 0,  # mainspace articles only
    "cmlimit": "max",
    "format": "json",
    **cont
}
        r = session.get(API_URL, params=params).json()
        pages_batch = r.get("query", {}).get("embeddedin", [])
        pages.extend(pages_batch)
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
    """
    Removes all {{orphan}} templates, including variants with parameters.
    """
    return re.sub(r"\{\{[Oo]rphan(?:\|[^}]*)?\}\}", "", text)


def save_page(session, title, text, token):
    res = session.post(API_URL, data={
        "action": "edit",
        "title": title,
        "text": text,
        "token": token,
        "summary": "Bot: removing {{orphan}} — article has 3+ incoming links",
        "minor": True,
        "format": "json"
    })
    # Log the API response for troubleshooting
    print(f"Edit response for {title}: {res.json()}")
    return res


def main():
    username = os.getenv("WIKI_USER")
    password = os.getenv("WIKI_PASS")
    if not username or not password:
        raise Exception("Missing WIKI_USER or WIKI_PASS")

    session = login_and_get_session(username, password)
    csrf_token = get_csrf_token(session)

    orphan_pages = get_orphaned_pages(session)
    print(f"Found {len(orphan_pages)} orphan-tagged pages")

    if len(orphan_pages) > NUM_PAGES:
        pages_to_check = random.sample(orphan_pages, NUM_PAGES)
    else:
        pages_to_check = orphan_pages

    print(f"Selected {len(pages_to_check)} random pages to check\n")

    for p in pages_to_check:
        title = p["title"]
        backlinks = count_mainspace_backlinks(session, title)
        print(f"{title}: {backlinks} backlinks")

        if backlinks >= MIN_BACKLINKS:
            print(f"READY: {title} has enough backlinks")

            if not DRY_RUN:
                text = get_page_text(session, title)
                new_text = remove_orphan_template(text)
                if new_text != text:
                    save_page(session, title, new_text, csrf_token)
                    print("  → {{orphan}} removed")

        time.sleep(SLEEP_TIME)


if __name__ == "__main__":
    main()
