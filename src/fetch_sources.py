"""Fetches articles from all configured sources."""

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Cepda-ResearchBot/1.0; "
        "+https://github.com/JonasThy/cepda-research-monitor)"
    )
}

PUBMED_SEARCH = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    "?db=pubmed&term=psilocybin+OR+psilocin+OR+psychedelic+OR+mdma"
    "+OR+ayahuasca+OR+hallucinogen+OR+mescaline+OR+ketamine+AND+psychiatry"
    "&retmax=20&sort=date&usehistory=y&retmode=json"
)
PUBMED_FETCH = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    "?db=pubmed&rettype=abstract&retmode=xml"
)

PSYCHEDELIC_ALPHA_RSS = "https://psychedelicalpha.com/feed/"
PSYCHEDELIC_ALPHA_NEWS = "https://psychedelicalpha.com/news/"


@dataclass
class Article:
    title: str
    url: str
    source: str
    abstract: str = ""
    date: str = ""
    authors: list[str] = field(default_factory=list)


def _today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


# ── PubMed ─────────────────────────────────────────────────────────────────


def fetch_pubmed() -> list[Article]:
    articles: list[Article] = []
    try:
        r = requests.get(PUBMED_SEARCH, headers=HEADERS, timeout=20)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return articles

        fetch_url = PUBMED_FETCH + "&id=" + ",".join(ids)
        r2 = requests.get(fetch_url, headers=HEADERS, timeout=30)
        r2.raise_for_status()
        root = ET.fromstring(r2.content)

        for article_el in root.findall(".//PubmedArticle"):
            try:
                pmid = article_el.findtext(".//PMID", "")
                title = article_el.findtext(".//ArticleTitle", "").strip()
                abstract_texts = article_el.findall(".//AbstractText")
                abstract = " ".join(
                    (el.text or "") for el in abstract_texts
                ).strip()
                year = article_el.findtext(".//PubDate/Year", "")
                month = article_el.findtext(".//PubDate/Month", "")
                date = f"{year}-{month}" if month else year
                authors_els = article_el.findall(".//Author")
                authors = []
                for a in authors_els[:3]:
                    last = a.findtext("LastName", "")
                    fore = a.findtext("ForeName", "")
                    if last:
                        authors.append(f"{last} {fore}".strip())

                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                if title and pmid:
                    articles.append(
                        Article(
                            title=title,
                            url=url,
                            source="PubMed",
                            abstract=abstract,
                            date=date,
                            authors=authors,
                        )
                    )
            except Exception:
                continue
    except Exception as e:
        print(f"[PubMed] Error: {e}")
    return articles


# ── Semantic Scholar ────────────────────────────────────────────────────────
# Uses the public API with a retry on 429 rate-limit responses.


def fetch_semantic_scholar() -> list[Article]:
    articles: list[Article] = []
    params = {
        "query": "psilocybin OR psychedelic OR mdma OR ayahuasca",
        "fields": "title,abstract,year,authors,externalIds,publicationDate",
        "limit": 10,
    }
    for attempt in range(3):
        try:
            r = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
                headers=HEADERS,
                timeout=20,
            )
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  [Semantic Scholar] Rate limited — waiting {wait}s before retry {attempt + 1}/3")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json().get("data", [])
            for paper in data:
                ext = paper.get("externalIds") or {}
                doi = ext.get("DOI", "")
                url = (
                    f"https://doi.org/{doi}"
                    if doi
                    else f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}"
                )
                authors = [
                    a.get("name", "") for a in (paper.get("authors") or [])[:3]
                ]
                articles.append(
                    Article(
                        title=paper.get("title", "").strip(),
                        url=url,
                        source="Semantic Scholar",
                        abstract=(paper.get("abstract") or "").strip(),
                        date=paper.get("publicationDate") or str(paper.get("year", "")),
                        authors=authors,
                    )
                )
            break
        except Exception as e:
            print(f"[Semantic Scholar] Error: {e}")
            break
    return articles


# ── Psychedelic Alpha ───────────────────────────────────────────────────────


def fetch_psychedelic_alpha() -> list[Article]:
    articles: list[Article] = []

    try:
        feed = feedparser.parse(
            PSYCHEDELIC_ALPHA_RSS,
            request_headers={"User-Agent": HEADERS["User-Agent"]},
        )
        if feed.entries:
            for entry in feed.entries[:10]:
                articles.append(
                    Article(
                        title=entry.get("title", "").strip(),
                        url=entry.get("link", ""),
                        source="Psychedelic Alpha",
                        abstract=BeautifulSoup(
                            entry.get("summary", ""), "lxml"
                        ).get_text()[:500],
                        date=entry.get("published", _today_str())[:10],
                    )
                )
            return articles
    except Exception:
        pass

    # Fallback: scrape news index
    try:
        time.sleep(2)
        r = requests.get(PSYCHEDELIC_ALPHA_NEWS, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select("article, .post, .news-item")[:10]:
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not href.startswith("http"):
                href = "https://psychedelicalpha.com" + href
            articles.append(
                Article(
                    title=title,
                    url=href,
                    source="Psychedelic Alpha",
                    abstract="",
                    date=_today_str(),
                )
            )
    except Exception as e:
        print(f"[Psychedelic Alpha] Error: {e}")
    return articles


# ── EuropePMC (Danish national source) ─────────────────────────────────────
# Finds peer-reviewed papers with Danish institutional affiliations.


def fetch_europepmc_denmark() -> list[Article]:
    articles: list[Article] = []
    # Use simple keyword query — AFF filter applied via full-text search field
    query = (
        "psilocybin OR psilocin OR psychedelic OR MDMA OR ayahuasca OR ketamine "
        "AND AFFILIATION:Denmark"
    )
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": 10,
        "sort": "P_PDATE_D desc",
    }
    try:
        r = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        r.raise_for_status()
        results = r.json().get("resultList", {}).get("result", [])
        for paper in results:
            pmid = paper.get("pmid", "")
            doi = paper.get("doi", "")
            if pmid:
                paper_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            elif doi:
                paper_url = f"https://doi.org/{doi}"
            else:
                paper_url = (
                    f"https://europepmc.org/article/"
                    f"{paper.get('source', 'MED')}/{paper.get('id', '')}"
                )

            author_list = paper.get("authorList", {}).get("author", [])
            authors = [
                f"{a.get('lastName', '')} {a.get('firstName', '')}".strip()
                for a in author_list[:3]
            ]

            abstract = paper.get("abstractText", "") or ""
            if "<" in abstract:
                abstract = BeautifulSoup(abstract, "lxml").get_text()

            articles.append(
                Article(
                    title=(paper.get("title") or "").strip().rstrip("."),
                    url=paper_url,
                    source="EuropePMC (Denmark)",
                    abstract=abstract[:1500],
                    date=paper.get("firstPublicationDate", "")[:10],
                    authors=authors,
                )
            )
    except Exception as e:
        print(f"[EuropePMC Denmark] Error: {e}")
    return articles


# ── OpenAlex ────────────────────────────────────────────────────────────────
# Fully open academic database (200M+ works). No API key required.
# Replaces DOAJ which requires registration.


def fetch_openalex() -> list[Article]:
    articles: list[Article] = []
    params = {
        "search": "psilocybin OR psychedelic OR MDMA OR ayahuasca OR psilocin",
        "filter": "type:article",
        "sort": "publication_date:desc",
        "per-page": 10,
        "select": "id,title,abstract_inverted_index,authorships,publication_date,primary_location,doi",
        "mailto": "info@cepda.dk",
    }
    try:
        r = requests.get(
            "https://api.openalex.org/works",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        for paper in results:
            title = (paper.get("title") or "").strip()
            if not title:
                continue

            doi = paper.get("doi", "") or ""
            if doi.startswith("https://doi.org/"):
                paper_url = doi
            elif doi:
                paper_url = f"https://doi.org/{doi}"
            else:
                oa_id = paper.get("id", "")
                paper_url = oa_id if oa_id.startswith("http") else ""
            if not paper_url:
                continue

            # Reconstruct abstract from inverted index
            inv = paper.get("abstract_inverted_index") or {}
            if inv:
                word_positions = [(word, pos) for word, positions in inv.items() for pos in positions]
                word_positions.sort(key=lambda x: x[1])
                abstract = " ".join(w for w, _ in word_positions)
            else:
                abstract = ""

            authorships = paper.get("authorships") or []
            authors = [
                a.get("author", {}).get("display_name", "")
                for a in authorships[:3]
            ]

            articles.append(
                Article(
                    title=title,
                    url=paper_url,
                    source="OpenAlex",
                    abstract=abstract[:1500],
                    date=(paper.get("publication_date") or "")[:10],
                    authors=authors,
                )
            )
    except Exception as e:
        print(f"[OpenAlex] Error: {e}")
    return articles


# ── Main ───────────────────────────────────────────────────────────────────


def fetch_all() -> list[Article]:
    print("[fetch] PubMed...")
    pubmed = fetch_pubmed()
    print(f"  → {len(pubmed)} articles")

    time.sleep(1)
    print("[fetch] Semantic Scholar...")
    ss = fetch_semantic_scholar()
    print(f"  → {len(ss)} articles")

    time.sleep(2)
    print("[fetch] Psychedelic Alpha...")
    pa = fetch_psychedelic_alpha()
    print(f"  → {len(pa)} articles")

    time.sleep(1)
    print("[fetch] EuropePMC (Denmark)...")
    epmc = fetch_europepmc_denmark()
    print(f"  → {len(epmc)} articles")

    time.sleep(1)
    print("[fetch] OpenAlex (open academic database)...")
    openalex = fetch_openalex()
    print(f"  → {len(openalex)} articles")

    all_articles = pubmed + ss + pa + epmc + openalex
    return [a for a in all_articles if a.url and a.title]
