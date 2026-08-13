# Cepda Research Monitor — Project Guide

## What this is
An automated daily psychedelic science research monitor for **Cepda** (Center for Psykedelisk Dannelse, Denmark). It fetches new academic articles and news each morning, filters them for relevance using Claude AI, generates bilingual (Danish + English) summaries, and publishes them to a GitHub Pages static website.

**Live site:** https://jonasthy.github.io/cepda-research-monitor/
**Repo:** https://github.com/JonasThy/cepda-research-monitor (will eventually be transferred to a Cepda organisation account)
**Owner:** Jonas Thy (GitHub: JonasThy). Anthropic API key and Claude account remain personal even after transfer.

Human review happens before any social media sharing — the system never posts autonomously.

---

## Architecture

```
GitHub Actions (daily 09:00 Danish time / 07:00 UTC)
    └── src/main.py
         └── src/web_feed.py        ← main pipeline
              ├── src/fetch_sources.py  ← fetch from 5 sources
              ├── src/seen_articles.py  ← SHA-256 deduplication
              └── Claude API (claude-haiku-4-5-20251001)
                   ├── filter_article()   ← relevance scoring
                   └── summarize()        ← bilingual summary
                        └── docs/data/feed.json  ← consumed by static site
docs/index.html              ← GitHub Pages frontend (served from /docs on master)
data/seen_web.json           ← deduplication store (committed after each real run)
```

---

## Article Sources (5 total)

| Source | Function | Notes |
|--------|----------|-------|
| PubMed | `fetch_pubmed()` | 20 articles/run. Stable. Uses NCBI Entrez API. |
| CrossRef | `fetch_crossref()` | 10 articles/run. Replaced Semantic Scholar (blocked by GitHub Actions IPs). Polite API, no auth needed. |
| Psychedelic Alpha | `fetch_psychedelic_alpha()` | 10 articles/run. RSS feed with scrape fallback. |
| EuropePMC (Denmark) | `fetch_europepmc_denmark()` | Peer-reviewed papers with Danish institutional affiliations. Query uses `AFF:Denmark` (not `AFFILIATION:Denmark`). |
| OpenAlex | `fetch_openalex()` | 10 articles/run. Replaced DOAJ (which required registration). Fully open, no auth. |

**Sources that were replaced and why:**
- Semantic Scholar → CrossRef (Semantic Scholar permanently blocks GitHub Actions IP ranges)
- DOAJ → OpenAlex (DOAJ requires API registration)

---

## AI Model & Prompts

**Model:** `claude-haiku-4-5-20251001`

**Filter prompt** (`FILTER_PROMPT` in `web_feed.py`): Scores each article 1–5 for relevance. Relevant = peer-reviewed research or credible journalism about clinical trials, neuroscience, psychiatry, policy, harm reduction, or anthropology of psychedelics.

**Summary prompt** (`SUMMARY_PROMPT` in `web_feed.py`):
- Output: JSON `{"en": "...", "da": "..."}` — both languages in one call
- Length: **1300–1500 characters including spaces** (hard requirement per language)
- Structure: 3–4 paragraphs. No bullet points or headers.
  1. What was found (plain, vivid language)
  2. How it was studied + key numbers/findings
  3. Implications for the **wider field of psychedelic research** (context, trends, parallel studies)
  4. (Optional) What comes next / what remains uncertain
- Tone: warm and curious, like a science journalist for a quality newspaper
- Terminology: "psychedelics" in English, "psykedelika" in Danish (never "psykedeliske stoffer")
- `max_tokens=2000` (required to fit bilingual output; was previously 800 which truncated)

---

## GitHub Actions Workflow (`.github/workflows/daily-scan.yml`)

- **Schedule:** `cron: '0 7 * * *'` (07:00 UTC = 09:00 Danish summer time)
- **Manual trigger:** `workflow_dispatch` with `dry_run` input (choice: `false`/`true`, default `false`)
- **Secret required:** `ANTHROPIC_API_KEY` (already present in repo secrets, added ~2 months ago)
- **After real run:** commits `data/seen_web.json` and `docs/data/feed.json` back to master
- **Dry run:** runs the full pipeline but does NOT write feed.json or commit anything — safe for testing

To trigger manually: go to **Actions → Daily Scan → Run workflow** on GitHub.

---

## Frontend (`docs/index.html`)

Single-file static site. Fetches `./data/feed.json` at load time.

**Visual design** matches cepda.dk:
```css
--bg: #f5f4f1;        /* warm off-white page background */
--surface: #ffffff;   /* card background */
--brand: #2c2c2c;     /* dark brand colour */
--text: #1c1c1a;
--muted: #6b6965;
font-family: Inter (Google Fonts)
```

**Default language:** Danish (`da`). User can switch to English via dropdown. Preference stored in `localStorage`.

**Card structure per article:**
1. Source + date (small caps, muted)
2. Title (linked to original source)
3. Summary text (in current language)
4. "Kilde"/"Source" button (outlined, links to original)
5. Membership block — fixed Danish text + dark "cepda.dk" button → https://cepda.dk/

**Disclaimer** in footer lists: PubMed, CrossRef, Psychedelic Alpha, EuropePMC, OpenAlex.

---

## Pipeline limits

- `MAX_PER_RUN = 5` — max articles summarised per daily run (to control API cost)
- `MAX_FEED_ITEMS = 60` — rolling cap of items kept in feed.json

---

## Known issues & history

- EuropePMC: the correct affiliation query field is `AFF:Denmark`. `AFFILIATION:Denmark` returns 0 results.
- EuropePMC sort field must be `P_PDATE_D desc` (or omitted) — `FIRST_PDATE desc` was tried but may not be valid.
- CrossRef abstracts come as HTML — parsed with BeautifulSoup (`lxml`).
- OpenAlex abstracts come as an inverted index — reconstructed by sorting word positions.
- Claude occasionally outputs malformed JSON for very short abstracts — handled by try/except fallback to article title.

---

## Development notes

- Local files are at `C:/Users/demia/AppData/Local/Temp/cepda2/`
- The repo remote is `https://github.com/JonasThy/cepda-research-monitor.git`
- GitHub Pages serves from the `/docs` folder on the `master` branch
- After pushing, the live site updates within ~1 minute
- The URL does not change when the repo is transferred to the Cepda organisation account (only the GitHub owner changes)
