"""Daily research feed for Cepda (Center for Psykedelisk Dannelse).

Fetches articles, filters for relevance with Claude, writes bilingual
(English + Danish) summaries, and saves a JSON feed consumed by the
static GitHub Pages site in docs/.
"""

import json
import os
import time
from datetime import datetime, timezone

import anthropic

from fetch_sources import Article, fetch_all
from seen_articles import SEEN_WEB_FILE, is_seen, mark_seen

MODEL = "claude-haiku-4-5-20251001"
MAX_PER_RUN = 5       # max new items summarised per daily run
MAX_FEED_ITEMS = 60   # rolling cap of items kept in the feed

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_DOCS_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data")
FEED_FILE = os.path.join(_DOCS_DATA_DIR, "feed.json")

LANGUAGES = {
    "en": "English",
    "da": "Danish",
}

FILTER_PROMPT = """\
You are the editor of a research and news feed about psychedelic science, \
run by Cepda (Center for Psykedelisk Dannelse), a Danish organisation that \
promotes scientific knowledge about psychedelics.

Decide whether the following article is relevant to share with a well-informed \
audience interested in psychedelic research.

Relevant = peer-reviewed research OR credible journalism about: clinical trials, \
neuroscience, psychiatry, policy and legal developments, harm reduction, or the \
anthropology of psychedelics.

NOT relevant = blog posts, speculative opinion pieces, product promotion, \
designer-drug hype, or crime reporting without a scientific angle.

Article:
Title: {title}
Source: {source}
Abstract/summary: {abstract}

Reply ONLY with JSON: {{"relevant": true/false, "reason": "short reason in English", "relevance_score": 1-5}}"""

SUMMARY_PROMPT = """\
You are the editor of a bilingual feed about psychedelic science run by Cepda \
(Center for Psykedelisk Dannelse), a Danish organisation.

Write a short, clear summary of the article below for a knowledgeable audience \
and provide it in BOTH of these languages:
- en: English
- da: Danish

RULES (apply to every language):
- Maximum 500 characters per summary
- Neutral, scientific tone — no hype
- Use "psychedelics" in English and "psykedelika" in Danish (never "psykedeliske stoffer")
- Mention study design and key data where applicable
- Write naturally and fluently for a native reader of that language

Article:
Title: {title}
Source/journal: {source}
Abstract/summary: {abstract}
URL: {url}

Reply ONLY with a JSON object with keys "en" and "da" whose values are the \
summary strings. No other text."""


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _truncate(text: str, max_chars: int = 1500) -> str:
    return text[:max_chars] + "…" if len(text) > max_chars else text


def _parse_json(raw: str) -> dict:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def filter_article(client: anthropic.Anthropic, article: Article) -> dict:
    prompt = FILTER_PROMPT.format(
        title=article.title,
        source=article.source,
        abstract=_truncate(article.abstract or "No abstract available."),
    )
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_json(msg.content[0].text)
    except Exception as e:
        print(f"  [filter] Error for '{article.title[:60]}': {e}")
        return {"relevant": False, "reason": "Assessment error", "relevance_score": 1}


def summarize(client: anthropic.Anthropic, article: Article) -> dict:
    """Returns {"en": "...", "da": "..."} in a single Claude call."""
    prompt = SUMMARY_PROMPT.format(
        title=article.title,
        source=article.source,
        abstract=_truncate(article.abstract or "No abstract available."),
        url=article.url,
    )
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json(msg.content[0].text)
        fallback = data.get("en") or article.title
        return {code: (data.get(code) or fallback) for code in LANGUAGES}
    except Exception as e:
        print(f"  [summary] Error for '{article.title[:60]}': {e}")
        return {code: article.title for code in LANGUAGES}


def _load_feed() -> dict:
    try:
        with open(FEED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"generated_at": "", "items": []}


def _save_feed(feed: dict) -> None:
    os.makedirs(os.path.dirname(FEED_FILE), exist_ok=True)
    feed["generated_at"] = datetime.now(timezone.utc).isoformat()
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)


def main() -> None:
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    if dry_run:
        print("=" * 60)
        print("DRY RUN — feed.json will not be written")
        print("=" * 60)

    print("\n── Fetching articles ────────────────────────────────────")
    all_articles = fetch_all()
    print(f"Total fetched: {len(all_articles)}")

    new_articles = [a for a in all_articles if not is_seen(a.url, path=SEEN_WEB_FILE)]
    skipped = len(all_articles) - len(new_articles)
    print(f"New (unseen): {len(new_articles)} · Already seen: {skipped}")

    if not new_articles:
        print("No new articles — nothing to add.")
        return

    client = _client()
    relevant: list[dict] = []

    print("\n── Filtering ────────────────────────────────────────────")
    for i, article in enumerate(new_articles):
        print(f"  [{i+1}/{len(new_articles)}] {article.title[:70]}")
        result = filter_article(client, article)
        print(
            f"    → relevant={result.get('relevant')}, "
            f"score={result.get('relevance_score')}, "
            f"{result.get('reason', '')[:80]}"
        )
        if result.get("relevant"):
            relevant.append({"article": article, "score": result.get("relevance_score", 3)})
        if i < len(new_articles) - 1:
            time.sleep(0.5)

    relevant.sort(key=lambda x: x["score"], reverse=True)
    relevant = relevant[:MAX_PER_RUN]
    print(f"Relevant this run: {len(relevant)}")

    print("\n── Summarizing ──────────────────────────────────────────")
    now = datetime.now(timezone.utc).isoformat()
    new_items = []
    for item in relevant:
        article = item["article"]
        print(f"  Summarizing: {article.title[:70]}")
        new_items.append(
            {
                "title": article.title,
                "url": article.url,
                "source": article.source,
                "date": article.date,
                "summaries": summarize(client, article),
                "added_at": now,
            }
        )
        time.sleep(0.5)

    if dry_run:
        print("\n[DRY RUN] Would add these items to the feed:")
        print(json.dumps(new_items, ensure_ascii=False, indent=2))
        return

    feed = _load_feed()
    existing_urls = {it["url"] for it in feed["items"]}
    merged = [it for it in new_items if it["url"] not in existing_urls] + feed["items"]
    feed["items"] = merged[:MAX_FEED_ITEMS]
    _save_feed(feed)
    print(f"\nFeed now holds {len(feed['items'])} items.")

    mark_seen([a.url for a in all_articles], path=SEEN_WEB_FILE)
    print(f"Marked {len(all_articles)} articles as seen.")
    print("\nDone.")


if __name__ == "__main__":
    main()
