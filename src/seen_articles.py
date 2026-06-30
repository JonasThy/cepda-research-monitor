import hashlib
import json
import os
from datetime import datetime, timezone

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SEEN_FILE = os.path.join(_DATA_DIR, "seen.json")
SEEN_WEB_FILE = os.path.join(_DATA_DIR, "seen_web.json")


def _load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen": [], "last_updated": ""}


def _save(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def article_hash(url: str) -> str:
    return "sha256:" + hashlib.sha256(url.strip().encode()).hexdigest()


def is_seen(url: str, path: str = SEEN_FILE) -> bool:
    return article_hash(url) in _load(path)["seen"]


def mark_seen(urls: list[str], path: str = SEEN_FILE) -> None:
    data = _load(path)
    seen_set = set(data["seen"])
    for url in urls:
        seen_set.add(article_hash(url))
    data["seen"] = sorted(seen_set)
    _save(data, path)
