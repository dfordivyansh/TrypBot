"""
Website tour catalogue (www.trypdeals.com/tours/) for the bot's replies.

The website publishes every tour in /tours/_index.json (title, slug, price,
duration, days, destinations). This module keeps a local copy in
BASE_DIR/data/website_tours.json, refreshed in the background every
REFRESH_HOURS (or now with `manage.py sync_website_tours`), and finds the
tours that match a customer's message so the bot can recommend real packages
with real prices and links instead of guessing.
"""
import json
import logging
import re
import threading
import time
from pathlib import Path

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

INDEX_URL = getattr(settings, "WEBSITE_TOURS_INDEX_URL", "https://www.trypdeals.com/tours/_index.json")
SITE = "https://www.trypdeals.com"
REFRESH_HOURS = 12
CACHE_FILE = Path(settings.BASE_DIR) / "data" / "website_tours.json"

_lock = threading.Lock()
_state = {"tours": None, "loaded_at": 0.0, "refreshing": False}

# Words that never identify a place on their own.
_STOP = {
    "tour", "tours", "package", "packages", "trip", "from", "days", "day", "nights", "night",
    "the", "and", "with", "for", "to", "in", "of", "a", "an", "i", "me", "my", "we", "want",
    "plan", "planning", "book", "booking", "price", "cost", "please", "hi", "hello", "india",
    "visit", "go", "going", "travel", "near", "best", "cheap", "family", "group", "need",
    "can", "you", "is", "are", "what", "how", "much", "any", "some", "there", "this", "that",
    "per", "person", "persons", "people", "kya", "hai", "ka", "ki", "ke", "se", "chahiye",
}


def _slim(t):
    return {
        "title": t.get("title") or "",
        "slug": t.get("slug") or "",
        "price": int(t.get("price") or 0),
        "duration": t.get("duration") or "",
        "days": int(t.get("days") or 0),
        "destinations": [str(d).replace("-", " ") for d in (t.get("destinations") or [])],
        "categories": t.get("categories") or [],
    }


def fetch_and_store():
    """Download the website index and save the slim copy. Returns the tour count."""
    # requests (certifi CA bundle): urllib fails certificate checks on the EC2 server.
    res = requests.get(INDEX_URL, headers={"User-Agent": "Trypbot/1.0", "Accept": "application/json"}, timeout=60)
    res.raise_for_status()
    raw = res.json()
    items = raw if isinstance(raw, list) else raw.get("tours") or []
    tours = [_slim(t) for t in items if t.get("slug") and t.get("published") is not False]
    if not tours:
        raise ValueError("Website tour index is empty")
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tours, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_FILE)
    with _lock:
        _state["tours"] = tours
        _state["loaded_at"] = time.time()
    logger.info(f"[WEBSITE TOURS] synced {len(tours)} tours")
    return len(tours)


def _refresh_in_background():
    with _lock:
        if _state["refreshing"]:
            return
        _state["refreshing"] = True

    def run():
        try:
            fetch_and_store()
        except Exception as exc:
            logger.warning(f"[WEBSITE TOURS] refresh failed: {exc}")
        finally:
            with _lock:
                _state["refreshing"] = False

    threading.Thread(target=run, daemon=True).start()


def get_tours():
    """The cached catalogue (possibly empty on the very first call while it downloads)."""
    with _lock:
        tours = _state["tours"]
        loaded_at = _state["loaded_at"]
    if tours is None and CACHE_FILE.exists():
        try:
            tours = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            loaded_at = CACHE_FILE.stat().st_mtime
            with _lock:
                _state["tours"], _state["loaded_at"] = tours, loaded_at
        except Exception as exc:
            logger.warning(f"[WEBSITE TOURS] cache unreadable: {exc}")
            tours = None
    if tours is None or time.time() - loaded_at > REFRESH_HOURS * 3600:
        _refresh_in_background()
    return tours or []


def tour_url(t):
    return f"{SITE}/tours/{t['slug']}/"


def _words(text):
    return [w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2 and w not in _STOP]


def find_tours(message, destination="", limit=3):
    """
    Tours whose destinations/title match the message (and the destination the
    conversation is about). Prefers tours from a departure city named in the
    message ("from Delhi") and the number of days asked for.
    """
    tours = get_tours()
    if not tours:
        return []
    text = f"{message or ''} {destination or ''}".lower()
    words = set(_words(text))
    if not words:
        return []
    from_city = re.search(r"\bfrom\s+([a-z]+(?:\s[a-z]+)?)", text)
    from_city = from_city.group(1) if from_city else ""
    days = re.search(r"\b(\d{1,2})\s*(?:days?|d\b|din)", text)
    days = int(days.group(1)) if days else 0

    scored = []
    for t in tours:
        dest_words = set(_words(" ".join(t["destinations"])))
        title = t["title"].lower()
        title_words = set(_words(title.split(" from ")[0]))
        hits = len(words & dest_words) * 3 + len(words & title_words) * 2
        if not hits:
            continue
        score = hits
        if from_city and f"from {from_city}" in title:
            score += 6
        elif " from " not in title:
            score += 1  # generic package, fine when no city was named
        if days and t["days"] == days:
            score += 3
        scored.append((score, -t["price"] if t["price"] else 0, t))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    picked, seen = [], set()
    for _, _, t in scored:
        key = t["title"].split(" from ")[0].split("(")[0].strip().lower(), t["days"]
        if key in seen:
            continue
        seen.add(key)
        picked.append(t)
        if len(picked) >= limit:
            break
    return picked


def tours_context(message, destination="", limit=3):
    """Plain-text lines for the AI prompt (empty string when nothing matches)."""
    lines = []
    for t in find_tours(message, destination, limit):
        price = f"from Rs. {t['price']:,} per person" if t["price"] else "price on request"
        lines.append(f"- {t['title']} | {t['duration']} | {price} | {tour_url(t)}")
    return "\n".join(lines)
