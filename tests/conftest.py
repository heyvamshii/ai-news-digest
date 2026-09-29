"""Shared fixtures: sample articles, feeds and a fake LLM (no network, no key)."""

import re
from datetime import datetime, timedelta, timezone

import pytest

from config import Source
from digest.llm import LLMError
from digest.models import Article

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)

SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test feed</title>
<item><title>New open-weight model beats GPT on coding</title>
  <link>https://news.example.com/model-launch?utm_source=rss</link>
  <pubDate>Sun, 27 Sep 2026 10:00:00 GMT</pubDate>
  <description>&lt;p&gt;A lab released a &lt;b&gt;new model&lt;/b&gt;.&lt;/p&gt;</description></item>
<item><title>Old story from last month</title>
  <link>https://news.example.com/old</link>
  <pubDate>Mon, 24 Aug 2026 10:00:00 GMT</pubDate>
  <description>Old news.</description></item>
<item><title>No date on this one</title><link>https://news.example.com/nodate</link></item>
</channel></rss>"""

SAMPLE_ANTHROPIC_HTML = """<html><body>
<a class="x_listItem" href="/news/claude-new-feature">
  <div><time class="x_date">Sep 27, 2026</time><span>Product</span></div>
  <span class="x__title body-3">Claude gets a new feature</span></a>
<a class="x_listItem" href="/news/claude-new-feature">duplicate link without time</a>
<a href="/news/bad-date"><time>someday</time><span class="title">Broken date</span></a>
<a href="/careers">Careers</a>
</body></html>"""

SAMPLE_HN = {
    "hits": [
        {"title": "OpenAI ships a new reasoning model", "url": "https://hn.example.com/a",
         "points": 300, "num_comments": 120, "created_at_i": int(NOW.timestamp()) - 3600},
        {"title": "Tiny AI story", "url": "https://hn.example.com/b",
         "points": 5, "num_comments": 1, "created_at_i": int(NOW.timestamp()) - 3600},
        {"title": "Ask HN: no url", "url": None, "points": 400, "created_at_i": int(NOW.timestamp())},
    ]
}


def make_article(n: int, *, source: str = "TechCrunch AI", hours_ago: int = 1, **overrides) -> Article:
    fields = dict(
        url=f"https://example.com/story-{n}",
        title=f"AI story number {n}",
        source=source,
        published_at=NOW - timedelta(hours=hours_ago),
        snippet=f"Snippet about AI story {n}. It has two sentences.",
    )
    fields.update(overrides)
    return Article(**fields)


@pytest.fixture
def rss_source() -> Source:
    return Source("Test Feed", "https://news.example.com/feed", "rss")


class FakeModel:
    """Answers like Groq would, based on which prompt it receives."""

    name = "fake-model"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []

    def ask(self, system: str, user: str) -> dict:
        self.calls.append(system[:30])
        if self.fail:
            raise LLMError("fake outage")
        ids = [int(m.group(1) or m.group(2)) for m in re.finditer(r"^(?:(\d+): \[|id (\d+) \|)", user, re.M)]
        if "editor" in system:
            return {"items": [{"id": str(i), "category": "models", "importance": 11 - (i % 10)} for i in ids]}
        return {
            "overview": ["Big day for open models.", "Regulators move.", "  "],
            "summaries": [{"id": i, "summary": f"AI summary {i}."} for i in ids],
        }


@pytest.fixture
def fake_model() -> FakeModel:
    return FakeModel()
