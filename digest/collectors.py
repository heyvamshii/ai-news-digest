"""Step 1: pull recent articles from RSS feeds, a scraped page and Hacker News."""

import calendar
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from config import Source
from digest.http import FetchError, get
from digest.models import Article
from digest.text import html_to_text, is_ai_related, normalize_title, normalize_url, truncate_words

SNIPPET_WORDS = 60
HN_MIN_POINTS = 20
SKIPPED_MARKER = " skipped: "


def _entry_time(entry) -> datetime | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return None
    return datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc)


def parse_feed(content: bytes, source: Source) -> list[Article]:
    """Turn raw RSS/Atom bytes into Articles."""
    articles = []
    for entry in feedparser.parse(content).entries:
        published = _entry_time(entry)
        url, title = entry.get("link", ""), html_to_text(entry.get("title", ""))
        if not (published and url and title):
            continue
        snippet = html_to_text(entry.get("summary", ""))
        articles.append(Article(url, title, source.name, published, truncate_words(snippet, SNIPPET_WORDS)))
    return articles


def fetch_rss(source: Source) -> list[Article]:
    return parse_feed(get(source.url).content, source)


def parse_anthropic_news(html: str, source: Source) -> list[Article]:
    """Scrape anthropic.com/news: it has no RSS feed, so we read the HTML list.

    Each item is an <a href="/news/..."> holding a <time> and a title <span>.
    Class names are auto-generated, so we match on 'title' inside them.
    """
    soup = BeautifulSoup(html, "html.parser")
    articles, seen = [], set()
    for link in soup.select('a[href^="/news/"]'):
        href = link["href"]
        time_tag = link.find("time")
        title_tag = link.select_one('[class*="title"]') or link.find(["h2", "h3", "h4"])
        if href in seen or not (time_tag and title_tag):
            continue
        try:
            day = datetime.strptime(time_tag.get_text(strip=True), "%b %d, %Y")
        except ValueError:
            continue
        seen.add(href)
        published = day.replace(hour=12, tzinfo=timezone.utc)
        articles.append(Article(urljoin(source.url, href), title_tag.get_text(" ", strip=True), source.name, published))
    return articles


def scrape_page(source: Source) -> list[Article]:
    return parse_anthropic_news(get(source.url, check_robots=True).text, source)


def parse_hn(payload: dict, source: Source) -> list[Article]:
    articles = []
    for hit in payload.get("hits", []):
        title, url = hit.get("title") or "", hit.get("url")
        if not (title and url) or (hit.get("points") or 0) < HN_MIN_POINTS:
            continue
        published = datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc)
        snippet = f"{hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments on Hacker News"
        articles.append(Article(url, title, source.name, published, snippet))
    return articles


def fetch_hn(source: Source, since: datetime) -> list[Article]:
    params = {
        "tags": "story",
        "numericFilters": f"created_at_i>{int(since.timestamp())},points>={HN_MIN_POINTS}",
        "hitsPerPage": 200,
    }
    return parse_hn(get(source.url, params=params).json(), source)


def fetch_source(source: Source, since: datetime) -> list[Article]:
    fetchers: dict[str, Callable[[], list[Article]]] = {
        "rss": lambda: fetch_rss(source),
        "scrape": lambda: scrape_page(source),
        "hn": lambda: fetch_hn(source, since),
    }
    return fetchers[source.kind]()


def keep_relevant(articles: Iterable[Article], source: Source, since: datetime, limit: int) -> list[Article]:
    """Recent, AI-related (for mixed sources), newest first, capped per source."""
    recent = [a for a in articles if a.published_at >= since]
    if not source.ai_only:
        recent = [a for a in recent if is_ai_related(f"{a.title} {a.snippet}")]
    return sorted(recent, key=lambda a: a.published_at, reverse=True)[:limit]


def dedupe(articles: Iterable[Article]) -> list[Article]:
    """The same story often appears in two feeds; keep the first copy."""
    seen_urls, seen_titles, unique = set(), set(), []
    for article in articles:
        url_key, title_key = normalize_url(article.url), normalize_title(article.title)
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(article)
    return unique


def round_robin(groups: list[list[Article]], limit: int) -> list[Article]:
    """Take one article from each source in turn so no source dominates."""
    mixed = [a for row in zip_longest(*groups) for a in row if a is not None]
    return mixed[:limit]


def collect_all(
    sources: Iterable[Source],
    *,
    lookback_hours: int,
    per_source_limit: int,
    max_articles: int,
    now: datetime | None = None,
    on_error: Callable[[str], None] = lambda message: None,
) -> tuple[list[Article], list[str]]:
    """Fetch every source. A broken source is reported, never fatal.

    Returns (articles, names of sources that answered, even with nothing new).
    """
    since = (now or datetime.now(timezone.utc)) - timedelta(hours=lookback_hours)
    groups, reachable = [], []
    for source in sources:
        try:
            kept = keep_relevant(fetch_source(source, since), source, since, per_source_limit)
        except (FetchError, ValueError, KeyError) as exc:
            on_error(f"{source.name}{SKIPPED_MARKER}{exc}")
            continue
        reachable.append(source.name)
        if kept:
            groups.append(kept)
    total = sum(len(g) for g in groups)
    return dedupe(round_robin(groups, total))[:max_articles], reachable
