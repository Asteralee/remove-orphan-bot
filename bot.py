import requests
import re
import time
import os

TEST_API = "https://test.wikipedia.org/w/api.php"
SIMPLE_WIKT_API = "https://simple.wiktionary.org/w/api.php"

USERNAME = os.getenv("WIKI_USER")
PASSWORD = os.getenv("WIKI_PASS")

CATEGORY_NAME = "Articles with broken Wiktionary links"
LIMIT = 10

# REQUIRED by Wikimedia API policy
HEADERS = {"User-Agent": "BrokenWiktBot/1.0)"}

if not USERNAME or not PASSWORD:
    raise Exception("Missing WIKI_USER or WIKI_PASS environment variables")

session = requests.Session()
session.headers.update(HEADERS)

simple_session = requests.Session()
simple_session.headers.update(HEADERS)


# ========================
# Utility
# ========================

def safe_json(response):
    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}: {response.text}")

    try:
        return response.json()
    except Exception:
        raise Exception(f"Invalid JSON response:\n{response.text}")


# ========================
# Login
# ========================

def login():
    r1 = session.get(TEST_API, params={
        "action": "query",
        "meta": "tokens",
        "type": "login",
        "format": "json"
    }, timeout=30)

    data = safe_json(r1)
    login_token = data["query"]["tokens"]["logintoken"]

    r2 = session.post(TEST_API, data={
        "action": "login",
        "lgname": USERNAME,
        "lgpassword": PASSWORD,
        "lgtoken": login_token,
        "format": "json"
    }, timeout=30)

    result = safe_json(r2)

    if result["login"]["result"] != "Success":
        raise Exception(f"Login failed: {result}")

    print("Logged in successfully.")


def get_csrf_token():
    r = session.get(TEST_API, params={
        "action": "query",
        "meta": "tokens",
        "format": "json"
    }, timeout=30)

    data = safe_json(r)
    return data["query"]["tokens"]["csrftoken"]


# ========================
# Page Retrieval
# ========================

def get_pages_from_category():
    r = session.get(TEST_API, params={
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{CATEGORY_NAME}",
        "cmlimit": LIMIT,
        "format": "json"
    }, timeout=30)

    data = safe_json(r)
    return [p["title"] for p in data["query"]["categorymembers"]]


def get_page_text(title):
    r = session.get(TEST_API, params={
        "action": "query",
        "prop": "revisions",
        "rvprop": "content|timestamp",
        "rvslots": "main",
        "titles": title,
        "format": "json"
    }, timeout=30)

    data = safe_json(r)

    pages = data["query"]["pages"]
    page_id = next(iter(pages))
    page = pages[page_id]

    if "revisions" not in page:
        return None, None

    content = page["revisions"][0]["slots"]["main"]["*"]
    timestamp = page["revisions"][0]["timestamp"]

    return content, timestamp


def page_exists_on_simple_wikt(title):
    r = simple_session.get(SIMPLE_WIKT_API, params={
        "action": "query",
        "titles": title,
        "format": "json"
    }, timeout=30)

    data = safe_json(r)

    pages = data["query"]["pages"]
    page_id = next(iter(pages))

    return page_id != "-1"


# ========================
# Editing
# ========================

def edit_page(title, new_text, summary, base_timestamp, csrf_token):
    r = session.post(TEST_API, data={
        "action": "edit",
        "title": title,
        "text": new_text,
        "summary": summary,
        "token": csrf_token,
        "basetimestamp": base_timestamp,
        "bot": True,
        "format": "json"
    }, timeout=30)

    result = safe_json(r)
    print("Edit result:", result)


pattern = re.compile(
    r"\{\{broken wikt link\|([^|}]+)(?:\|([^}]+))?\}\}",
    re.IGNORECASE
)


def fix_text(text):
    changed = False

    def replacer(match):
        nonlocal changed

        term = match.group(1).strip()
        display = match.group(2)

        if page_exists_on_simple_wikt(term):
            changed = True
            if display:
                return f"[[wikt:{term}|{display.strip()}]]"
            else:
                return f"[[wikt:{term}]]"
        else:
            return match.group(0)

    new_text = pattern.sub(replacer, text)
    return new_text, changed


# ========================
# MAIN
# ========================

def main():
    login()
    csrf_token = get_csrf_token()

    pages = get_pages_from_category()

    for title in pages:
        print(f"Processing: {title}")

        text, timestamp = get_page_text(title)
        if not text:
            continue

        new_text, changed = fix_text(text)

        if changed:
            edit_page(
                title,
                new_text,
                "Fix broken Wiktionary links (checking Simple English Wiktionary)",
                timestamp,
                csrf_token
            )
            time.sleep(2)  # polite delay
        else:
            print("No changes needed.")


if __name__ == "__main__":
    main()
