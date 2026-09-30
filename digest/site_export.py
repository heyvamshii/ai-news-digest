"""Export the database as JSON files for the static web dashboard (hosted on Vercel).

    site/
    ├── index.html, app.js, style.css,     copied from dashboard/
    │   vercel.json
    └── data/
        ├── index.json                     every issue + totals + chart data
        ├── issues/<date>.json             one newsletter per day
        └── articles.json                  recent articles, for search
"""

import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import TOP_STORIES
from digest import storage

DASHBOARD_SRC = Path(__file__).resolve().parent.parent / "dashboard"
SEARCH_DAYS = 60             # how far back the search box looks
TREND_DAYS = 30              # bars in the "articles collected per day" chart
STATIC_FILES = ("index.html", "app.js", "style.css", "vercel.json")


def _web_url(url: str | None) -> str | None:
    """Only real web links reach the browser (no javascript: or data: tricks)."""
    return url if url and url.lower().startswith(("https://", "http://")) else None


def _article(row: sqlite3.Row) -> dict:
    return {
        "title": row["title"],
        "url": _web_url(row["url"]),
        "source": row["source"],
        "category": row["category"],
        "importance": row["importance"],
        "summary": row["summary"],
        "published": row["published_at"][:10],
    }


def date_label(iso_day: str) -> str:
    day = date.fromisoformat(iso_day)
    return f"{day:%A}, {day.day} {day:%B %Y}"


def issue_payload(conn: sqlite3.Connection, row: sqlite3.Row, pdf_url: str | None) -> dict:
    """One day's newsletter. Days saved before `content` existed are rebuilt from the
    articles marked as featured that day (no 'Today in AI' bullets for those)."""
    content = json.loads(row["content"]) if row["content"] else None
    if content:
        found = storage.articles_by_url(conn, [*content["top"], *content["also"]])
        top = [_article(found[u]) for u in content["top"] if u in found]
        also = [_article(found[u]) for u in content["also"] if u in found]
        overview, notes, rebuilt = content["overview"], content.get("notes", []), False
    else:
        featured = storage.featured_articles(conn, row["digest_date"])     # most important first
        summarised = [r for r in featured if r["summary"]]
        top = [_article(r) for r in summarised[:TOP_STORIES]]
        also = [_article(r) for r in featured if r not in summarised[:TOP_STORIES]]
        overview, notes, rebuilt = [], [], True
    return {
        "date": row["digest_date"],
        "date_label": date_label(row["digest_date"]),
        "overview": overview,
        "top": top,
        "also": also,
        "notes": notes,
        "mode": row["mode"],
        "article_count": row["article_count"],
        "source_count": row["source_count"],
        "pdf": pdf_url,
        "rebuilt": rebuilt,
    }


def index_payload(conn: sqlite3.Connection, issues: list[dict], now: datetime) -> dict:
    stats = storage.stats(conn)
    since = (now - timedelta(days=TREND_DAYS - 1)).date()
    counts = {r["day"]: r["n"] for r in storage.daily_fetch_counts(conn, since.isoformat())}
    daily = [{"day": (since + timedelta(days=i)).isoformat(),
              "n": counts.get((since + timedelta(days=i)).isoformat(), 0)} for i in range(TREND_DAYS)]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "latest": issues[-1]["date"] if issues else None,
        "issues": [{k: i[k] for k in ("date", "article_count", "source_count", "mode", "pdf", "rebuilt")}
                   | {"top_count": len(i["top"])} for i in issues],
        "totals": {"issues": len(issues), "articles": stats["articles"],
                   "sources": stats["sources"], "summarised": stats["summarised"]},
        "by_category": [{"name": r["category"], "n": r["n"]} for r in stats["by_category"]],
        "by_source": [{"name": r["source"], "n": r["n"]} for r in stats["by_source"]],
        "daily": daily,
    }


def search_payload(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    since = (now - timedelta(days=SEARCH_DAYS)).isoformat()
    return [_article(r) | {"featured_on": r["featured_on"]} for r in storage.recent_articles(conn, since)]


def pdf_file_name(stored_path: str) -> str:
    r"""'reports\AI_Digest_x.pdf' (saved on Windows) or 'reports/AI_Digest_x.pdf' -> 'AI_Digest_x.pdf'."""
    return re.split(r"[\\/]", stored_path)[-1]


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def export_site(db_path: Path, out_dir: Path, pdf_url_for, now: datetime | None = None) -> dict:
    """Write the whole dashboard into out_dir. `pdf_url_for(file_name)` gives each PDF's link.
    Returns a small summary for the log."""
    now = now or datetime.now(timezone.utc)
    with storage.connect(db_path) as conn:
        issues = [issue_payload(conn, row, pdf_url_for(pdf_file_name(row["pdf_path"])))
                  for row in storage.all_digests(conn)]
        index = index_payload(conn, issues, now)
        articles = search_payload(conn, now)

    data_dir = out_dir / "data"
    # Write the issues to a fresh folder first, then swap it in, so a failure halfway
    # never leaves a half-empty dashboard behind.
    staging = data_dir / "issues.new"
    if staging.exists():
        shutil.rmtree(staging)
    for issue in issues:
        _write_json(staging / f"{issue['date']}.json", issue)
    staging.mkdir(parents=True, exist_ok=True)
    if (data_dir / "issues").exists():
        shutil.rmtree(data_dir / "issues")          # drops issues that no longer exist
    staging.rename(data_dir / "issues")
    _write_json(data_dir / "index.json", index)
    _write_json(data_dir / "articles.json", articles)
    for name in STATIC_FILES:
        shutil.copyfile(DASHBOARD_SRC / name, out_dir / name)
    return {"issues": len(issues), "articles": len(articles),
            "categories": Counter(a["category"] for a in articles)}
