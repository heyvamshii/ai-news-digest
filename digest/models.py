"""The data shapes passed between pipeline steps."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Article:
    """One news item. Frozen: every step returns a new copy instead of editing."""

    url: str
    title: str
    source: str
    published_at: datetime          # always timezone-aware (UTC)
    snippet: str = ""
    category: str | None = None
    importance: int | None = None
    summary: str | None = None


@dataclass(frozen=True)
class Digest:
    """Everything the PDF needs for one day."""

    date_label: str                 # e.g. "Monday, 28 September 2026"
    file_date: str                  # e.g. "2026-09-28"
    overview: tuple[str, ...]       # "Today in AI" bullets
    top_stories: tuple[Article, ...]
    also_worth_knowing: tuple[Article, ...]
    article_count: int
    source_names: tuple[str, ...]
    mode: str                       # "groq:<model>" or "offline"
    notes: tuple[str, ...] = field(default_factory=tuple)
