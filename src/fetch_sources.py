"""Fetches articles from all configured sources."""

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

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
SEMANTIC_SCHOLAR_API = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
    "?query=psilocybin+OR+psychedelic+OR+mdma+OR+ayahuasca"
    "&fields=title,abstract,year,authors,externalIds,publicationDate"
    "&limit=10&sort=publicationDate"
)
PSYCHEDELIC_ALPHA_RSS = "https://psychedelicalpha.com/feed/"
PSYCHEDELIC_ALPHA_NEWS = "https://psychedelicalpha.com/news/"

# EuropePMC: finds research papers with Danish institutional affiliations.
# Free API, no key required. Replaces DiVA/SwePub from the reference implementation.
EUROPEPMC_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    "?query=({terms})+AFF%3A%22Denmark%22"
    "&format=json&resultType=core&pageSize=10&sort=P_PDATE_D+desc"
)
EUROPEPMC_TERMS = (
    "psilocybin+OR+psilocin+OR+psychedelic+OR+MDMA+OR+ayahuasca"
    "+OR+mescaline+OR+ketamine+AND+psychiatry"
)


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


def fetch_semantic_scholar() -> list[Article]:
    articles: list[Article] = []
    try:
        r = requests.get(SEMANTIC_SCHOLAR_API, headers=HEADERS, timeout=20)
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
    except Exception as e:
        print(f"[Semantic Scholar] Error: {e}")
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
# Replaces the Sweden-specific DiVA source from the reference implementation.


def fetch_europepmc_denmark() -> list[Article]:
    articles: list[Article] = []
    url = EUROPEPMC_URL.format(terms=EUROPEPMC_TERMS)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        results = r.json().get("resultList", {}).get("result", [])
        for paper in results[:10]:
            pmid = paper.get("pmid", "")
            doi = paper.get("doi", "")
            if pmid:
                paper_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            elif doi:
                paper_url = f"https://doi.org/{doi}"
            else:
                paper_url = f"https://europepmc.org/article/{paper.get('source', 'MED')}/{paper.get('id', '')}"

            author_list = paper.get("authorList", {}).get("author", [])
            authors = [
                f"{a.get('lastName', '')} {a.get('firstName', '')}".strip()
                for a in author_list[:3]
            ]

            abstract = paper.get("abstractText", "") or ""
            # EuropePMC sometimes wraps abstract in HTML
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

    all_articles = pubmed + ss + pa + epmc
    return [a for a in all_articles if a.url and a.title]
