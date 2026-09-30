import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

import build_site
import config
from digest import site_export, storage
from digest.models import Digest
from tests.conftest import make_article

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)


def _seed(db_path, *, with_content: bool = True):
    top = [replace(make_article(i, category="Models", importance=9 - i), summary=f"Summary {i}.") for i in range(2)]
    also = [make_article(10, category="Tools", importance=3), make_article(11, url="javascript:alert(1)")]
    digest = Digest(date_label="Tuesday, 29 September 2026", file_date="2026-09-29",
                    overview=("Point A.", "Point B."), top_stories=tuple(top), also_worth_knowing=tuple(also),
                    article_count=40, source_names=("TechCrunch AI",), mode="Groq (m)",
                    notes=("Unavailable today: Wired AI.",))
    with storage.connect(db_path) as conn:
        storage.save_new(conn, [*top, *also])
        storage.save_analysis(conn, [*top, *also])
        storage.mark_featured(conn, [*top, *also], "2026-09-29")
        storage.record_digest(conn, digest_date="2026-09-29", article_count=40, source_count=1,
                              top_story_count=2, mode="Groq (m)", pdf_path="reports/AI_Digest_2026-09-29.pdf",
                              content=storage.digest_content(digest) if with_content else None)
    return top, also


def _export(tmp_path, db, **kwargs):
    out = tmp_path / "site"
    summary = site_export.export_site(db, out, lambda name: f"https://example.com/{name}", now=NOW, **kwargs)
    read = lambda rel: json.loads((out / rel).read_text(encoding="utf-8"))  # noqa: E731
    return out, summary, read


def test_export_writes_dashboard_files_and_issue(tmp_path):
    db = tmp_path / "news.db"
    _seed(db)
    out, summary, read = _export(tmp_path, db)

    for name in ("index.html", "app.js", "style.css", "vercel.json"):
        assert (out / name).exists()
    assert summary["issues"] == 1

    index = read("data/index.json")
    assert index["latest"] == "2026-09-29"
    assert index["issues"][0] | {} == {"date": "2026-09-29", "article_count": 40, "source_count": 1,
                                       "mode": "Groq (m)", "pdf": "https://example.com/AI_Digest_2026-09-29.pdf",
                                       "rebuilt": False, "top_count": 2}
    assert index["totals"]["issues"] == 1 and index["totals"]["articles"] == 4
    assert len(index["daily"]) == site_export.TREND_DAYS
    assert {c["name"] for c in index["by_category"]} >= {"Models", "Tools"}

    issue = read("data/issues/2026-09-29.json")
    assert issue["date_label"] == "Tuesday, 29 September 2026"
    assert issue["overview"] == ["Point A.", "Point B."]
    assert [s["title"] for s in issue["top"]] == ["AI story number 0", "AI story number 1"]
    assert issue["top"][0]["summary"] == "Summary 0."
    assert issue["notes"] == ["Unavailable today: Wired AI."]
    assert issue["rebuilt"] is False


def test_unsafe_links_are_dropped(tmp_path):
    db = tmp_path / "news.db"
    _seed(db)
    _, _, read = _export(tmp_path, db)
    urls = [a["url"] for a in read("data/issues/2026-09-29.json")["also"]]
    assert None in urls and not any(u and u.startswith("javascript") for u in urls)


def test_issue_without_saved_content_is_rebuilt_from_featured_articles(tmp_path):
    db = tmp_path / "news.db"
    _seed(db, with_content=False)
    _, _, read = _export(tmp_path, db)
    issue = read("data/issues/2026-09-29.json")
    assert issue["rebuilt"] is True
    assert issue["overview"] == []
    assert len(issue["top"]) == 2 and len(issue["also"]) == 2      # summary decides top vs also


def test_search_file_lists_recent_articles_with_featured_date(tmp_path):
    db = tmp_path / "news.db"
    _seed(db)
    _, summary, read = _export(tmp_path, db)
    articles = read("data/articles.json")
    assert summary["articles"] == 4
    assert all(a["featured_on"] == "2026-09-29" for a in articles)


def test_old_issue_files_are_removed_on_rebuild(tmp_path):
    db = tmp_path / "news.db"
    _seed(db)
    out, _, _ = _export(tmp_path, db)
    stale = out / "data" / "issues" / "2020-01-01.json"
    stale.write_text("{}", encoding="utf-8")
    _export(tmp_path, db)
    assert not stale.exists()


def test_old_databases_get_the_content_column(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE digests (digest_date TEXT PRIMARY KEY, created_at TEXT NOT NULL, article_count "
                 "INTEGER NOT NULL, source_count INTEGER NOT NULL, top_story_count INTEGER NOT NULL, "
                 "mode TEXT NOT NULL, pdf_path TEXT NOT NULL)")
    conn.commit()
    conn.close()
    with storage.connect(db) as migrated:
        columns = {r["name"] for r in migrated.execute("PRAGMA table_info(digests)")}
    assert "content" in columns


def test_empty_database_exports_an_empty_dashboard(tmp_path):
    db = tmp_path / "news.db"
    with storage.connect(db):
        pass
    _, summary, read = _export(tmp_path, db)
    assert summary["issues"] == 0
    assert read("data/index.json")["latest"] is None


def test_articles_by_url_with_no_urls():
    conn = sqlite3.connect(":memory:")
    try:
        assert storage.articles_by_url(conn, []) == {}
    finally:
        conn.close()


def test_dashboard_url_setting(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://ai-news-digest.vercel.app")
    assert config.dashboard_url() == "https://ai-news-digest.vercel.app/"
    monkeypatch.setenv("DASHBOARD_URL", "javascript:alert(1)")
    assert config.dashboard_url() is None
    monkeypatch.delenv("DASHBOARD_URL")
    assert config.dashboard_url() is None


def test_build_site_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "local.db")
    monkeypatch.setattr(config, "SITE_DIR", tmp_path / "reports" / "local" / "site")
    assert build_site.main() == 1                                    # no database yet
    _seed(config.DB_PATH)
    assert build_site.main() == 0
    assert "Dashboard built: 1 issue(s)" in capsys.readouterr().out
    assert build_site.pdf_link("AI_Digest_x.pdf") == "../AI_Digest_x.pdf"   # local run: PDF next to site


@pytest.mark.parametrize("stored", ["reports\AI_Digest_2026-09-29.pdf", "reports/AI_Digest_2026-09-29.pdf",
                                    "AI_Digest_2026-09-29.pdf"])
def test_pdf_file_name_handles_windows_and_linux_paths(stored):
    assert site_export.pdf_file_name(stored) == "AI_Digest_2026-09-29.pdf"


def test_rebuilt_issue_caps_top_stories(tmp_path, monkeypatch):
    monkeypatch.setattr(site_export, "TOP_STORIES", 1)
    db = tmp_path / "news.db"
    _seed(db, with_content=False)
    _, _, read = _export(tmp_path, db)
    issue = read("data/issues/2026-09-29.json")
    assert [s["title"] for s in issue["top"]] == ["AI story number 0"]      # highest importance kept
    assert len(issue["also"]) == 3
