from datetime import timedelta

import pytest

from config import Source
from digest import collectors
from digest.http import FetchError
from tests.conftest import NOW, SAMPLE_ANTHROPIC_HTML, SAMPLE_HN, SAMPLE_RSS, make_article

pytestmark = pytest.mark.unit


def test_parse_feed_reads_items_and_skips_undated(rss_source):
    articles = collectors.parse_feed(SAMPLE_RSS, rss_source)
    assert [a.title for a in articles] == ["New open-weight model beats GPT on coding", "Old story from last month"]
    first = articles[0]
    assert first.snippet == "A lab released a new model."
    assert first.source == "Test Feed"
    assert first.published_at.tzinfo is not None


def test_parse_anthropic_news_scrapes_title_date_and_absolute_url():
    source = Source("Anthropic", "https://www.anthropic.com/news", "scrape")
    articles = collectors.parse_anthropic_news(SAMPLE_ANTHROPIC_HTML, source)
    assert len(articles) == 1
    assert articles[0].url == "https://www.anthropic.com/news/claude-new-feature"
    assert articles[0].title == "Claude gets a new feature"
    assert articles[0].published_at.day == 27


def test_parse_hn_drops_low_points_and_missing_urls():
    source = Source("Hacker News", "https://hn", "hn", ai_only=False)
    articles = collectors.parse_hn(SAMPLE_HN, source)
    assert [a.url for a in articles] == ["https://hn.example.com/a"]
    assert "300 points" in articles[0].snippet


def test_keep_relevant_filters_old_and_off_topic_for_mixed_sources():
    mixed = Source("Mixed", "u", "rss", ai_only=False)
    articles = [
        make_article(1, hours_ago=1),
        make_article(2, hours_ago=100),                          # too old
        make_article(3, hours_ago=2, title="Best pizza in town", snippet="cheese"),  # not AI
        make_article(4, hours_ago=3),
    ]
    kept = collectors.keep_relevant(articles, mixed, NOW - timedelta(hours=72), limit=5)
    assert [a.url[-1] for a in kept] == ["1", "4"]


def test_keep_relevant_respects_per_source_limit():
    source = Source("AI", "u", "rss")
    articles = [make_article(i, hours_ago=i) for i in range(1, 6)]
    assert len(collectors.keep_relevant(articles, source, NOW - timedelta(hours=72), limit=3)) == 3


def test_dedupe_matches_on_url_or_title():
    a = make_article(1)
    same_url = make_article(2, url="https://www.example.com/story-1/?ref=x")
    same_title = make_article(3, title="AI Story Number 1!")
    fresh = make_article(4)
    assert collectors.dedupe([a, same_url, same_title, fresh]) == [a, fresh]


def test_round_robin_interleaves_sources():
    g1 = [make_article(1), make_article(2)]
    g2 = [make_article(3)]
    assert collectors.round_robin([g1, g2], 10) == [g1[0], g2[0], g1[1]]
    assert len(collectors.round_robin([g1, g2], 2)) == 2


def test_collect_all_skips_broken_sources_and_reports_them(monkeypatch):
    good = Source("Good", "u1", "rss")
    broken = Source("Broken", "u2", "rss")

    def fake_fetch(source, since):
        if source is broken:
            raise FetchError("429 Too Many Requests")
        return [make_article(1, source="Good"), make_article(2, source="Good")]

    monkeypatch.setattr(collectors, "fetch_source", fake_fetch)
    errors = []
    articles, working = collectors.collect_all(
        [good, broken], lookback_hours=72, per_source_limit=8, max_articles=1, now=NOW, on_error=errors.append,
    )
    assert working == ["Good"]
    assert len(articles) == 1                     # max_articles cap
    assert "Broken skipped" in errors[0]


def test_fetch_source_dispatches_by_kind(monkeypatch):
    monkeypatch.setattr(collectors, "fetch_rss", lambda s: ["rss"])
    monkeypatch.setattr(collectors, "scrape_page", lambda s: ["scrape"])
    monkeypatch.setattr(collectors, "fetch_hn", lambda s, since: ["hn"])
    for kind in ("rss", "scrape", "hn"):
        assert collectors.fetch_source(Source("x", "u", kind), NOW) == [kind]


def test_fetch_functions_parse_http_responses(monkeypatch, rss_source):
    class Resp:
        content = SAMPLE_RSS
        text = SAMPLE_ANTHROPIC_HTML

        def json(self):
            return SAMPLE_HN

    calls = []
    monkeypatch.setattr(collectors, "get", lambda url, **kw: calls.append((url, kw)) or Resp())
    assert len(collectors.fetch_rss(rss_source)) == 2
    assert len(collectors.scrape_page(Source("Anthropic", "https://www.anthropic.com/news", "scrape"))) == 1
    assert len(collectors.fetch_hn(Source("HN", "https://hn", "hn"), NOW)) == 1
    assert calls[1][1] == {"check_robots": True}            # scraping checks robots.txt
    assert "created_at_i>" in calls[2][1]["params"]["numericFilters"]
