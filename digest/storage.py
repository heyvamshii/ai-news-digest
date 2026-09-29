"""SQLite storage: every article we collect, plus a record of each digest."""

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from digest.models import Article
from digest.text import normalize_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url_key       TEXT NOT NULL UNIQUE,     -- normalised URL, blocks duplicates
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    source        TEXT NOT NULL,
    published_at  TEXT NOT NULL,            -- ISO 8601, UTC
    fetched_at    TEXT NOT NULL,
    snippet       TEXT NOT NULL DEFAULT '',
    category      TEXT,
    importance    INTEGER,
    summary       TEXT,
    featured_on   TEXT                      -- digest date that used this article
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);

CREATE TABLE IF NOT EXISTS digests (
    digest_date    TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    article_count  INTEGER NOT NULL,
    source_count   INTEGER NOT NULL,
    top_story_count INTEGER NOT NULL,
    mode           TEXT NOT NULL,
    pdf_path       TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_new(conn: sqlite3.Connection, articles: Iterable[Article]) -> int:
    """Insert articles we haven't seen before. Returns how many were new."""
    rows = [
        (normalize_url(a.url), a.url, a.title, a.source, a.published_at.isoformat(), _now(), a.snippet)
        for a in articles
    ]
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO articles (url_key, url, title, source, published_at, fetched_at, snippet) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return conn.total_changes - before


def _to_article(row: sqlite3.Row) -> Article:
    return Article(
        url=row["url"],
        title=row["title"],
        source=row["source"],
        published_at=datetime.fromisoformat(row["published_at"]),
        snippet=row["snippet"],
        category=row["category"],
        importance=row["importance"],
        summary=row["summary"],
    )


def load_candidates(conn: sqlite3.Connection, *, since: datetime, digest_date: str, limit: int) -> list[Article]:
    """Articles for today's digest: recent, and not already used on an earlier day.

    Articles already featured *today* stay eligible, so re-running the same
    day (e.g. during a demo) rebuilds the same digest instead of an empty one.
    """
    rows = conn.execute(
        "SELECT * FROM articles WHERE published_at >= ? AND (featured_on IS NULL OR featured_on = ?) "
        "ORDER BY published_at DESC LIMIT ?",
        (since.isoformat(), digest_date, limit),
    ).fetchall()
    return [_to_article(r) for r in rows]


def save_analysis(conn: sqlite3.Connection, articles: Iterable[Article]) -> None:
    """Store category / importance / summary produced by the AI step."""
    conn.executemany(
        "UPDATE articles SET category = ?, importance = ?, summary = COALESCE(?, summary) WHERE url_key = ?",
        [(a.category, a.importance, a.summary, normalize_url(a.url)) for a in articles],
    )


def mark_featured(conn: sqlite3.Connection, articles: Iterable[Article], digest_date: str) -> None:
    conn.executemany(
        "UPDATE articles SET featured_on = ? WHERE url_key = ?",
        [(digest_date, normalize_url(a.url)) for a in articles],
    )


def record_digest(
    conn: sqlite3.Connection, *, digest_date: str, article_count: int, source_count: int,
    top_story_count: int, mode: str, pdf_path: str,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO digests VALUES (?, ?, ?, ?, ?, ?, ?)",
        (digest_date, _now(), article_count, source_count, top_story_count, mode, pdf_path),
    )


def stats(conn: sqlite3.Connection) -> dict:
    """Numbers for show_db.py and the demo."""
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "articles": one("SELECT COUNT(*) FROM articles"),
        "sources": one("SELECT COUNT(DISTINCT source) FROM articles"),
        "summarised": one("SELECT COUNT(*) FROM articles WHERE summary IS NOT NULL"),
        "digests": one("SELECT COUNT(*) FROM digests"),
        "first_fetch": one("SELECT MIN(fetched_at) FROM articles"),
        "by_source": conn.execute(
            "SELECT source, COUNT(*) AS n FROM articles GROUP BY source ORDER BY n DESC"
        ).fetchall(),
        "by_category": conn.execute(
            "SELECT COALESCE(category, 'Not yet rated') AS category, COUNT(*) AS n "
            "FROM articles GROUP BY 1 ORDER BY n DESC"
        ).fetchall(),
        "recent_digests": conn.execute(
            "SELECT digest_date, article_count, source_count, mode FROM digests ORDER BY digest_date DESC LIMIT 7"
        ).fetchall(),
    }
