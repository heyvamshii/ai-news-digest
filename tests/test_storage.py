from dataclasses import replace
from datetime import timedelta

import pytest

from digest import storage
from tests.conftest import NOW, make_article

pytestmark = pytest.mark.unit
SINCE = NOW - timedelta(hours=72)


@pytest.fixture
def conn(tmp_path):
    with storage.connect(tmp_path / "test.db") as connection:
        yield connection


def test_save_new_ignores_duplicates(conn):
    assert storage.save_new(conn, [make_article(1), make_article(2)]) == 2
    duplicate = make_article(9, url="https://www.example.com/story-1/?utm=x")
    assert storage.save_new(conn, [duplicate, make_article(3)]) == 1


def test_load_candidates_returns_recent_newest_first(conn):
    storage.save_new(conn, [make_article(1, hours_ago=5), make_article(2, hours_ago=1),
                            make_article(3, hours_ago=200)])
    got = storage.load_candidates(conn, since=SINCE, digest_date="2026-09-28", limit=10)
    assert [a.url[-1] for a in got] == ["2", "1"]
    assert got[0].published_at.tzinfo is not None


def test_featured_articles_are_hidden_on_later_days_but_not_the_same_day(conn):
    a, b = make_article(1), make_article(2)
    storage.save_new(conn, [a, b])
    storage.mark_featured(conn, [a], "2026-09-27")
    later = storage.load_candidates(conn, since=SINCE, digest_date="2026-09-28", limit=10)
    assert [x.url for x in later] == [b.url]
    storage.mark_featured(conn, [b], "2026-09-28")
    rerun = storage.load_candidates(conn, since=SINCE, digest_date="2026-09-28", limit=10)
    assert [x.url for x in rerun] == [b.url]           # a same-day re-run still has content


def test_save_analysis_keeps_existing_summary_when_new_one_is_empty(conn):
    a = make_article(1)
    storage.save_new(conn, [a])
    storage.save_analysis(conn, [replace(a, category="Models", importance=8, summary="Great.")])
    storage.save_analysis(conn, [replace(a, category="Models", importance=9, summary=None)])
    [stored] = storage.load_candidates(conn, since=SINCE, digest_date="x", limit=1)
    assert (stored.category, stored.importance, stored.summary) == ("Models", 9, "Great.")


def test_record_digest_and_stats(conn):
    storage.save_new(conn, [make_article(1), make_article(2, source="Wired AI")])
    storage.record_digest(conn, digest_date="2026-09-28", article_count=2, source_count=2,
                          top_story_count=1, mode="offline keyword rules", pdf_path="reports/x.pdf")
    storage.record_digest(conn, digest_date="2026-09-28", article_count=3, source_count=2,
                          top_story_count=1, mode="offline keyword rules", pdf_path="reports/x.pdf")
    s = storage.stats(conn)
    assert (s["articles"], s["sources"], s["digests"]) == (2, 2, 1)
    assert s["recent_digests"][0]["article_count"] == 3
    assert s["by_category"][0]["category"] == "Not yet rated"
