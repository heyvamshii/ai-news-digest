"""Small text helpers shared by the collectors, the LLM step and the PDF."""

import re
import unicodedata
from html import unescape
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from config import AI_KEYWORDS

_SPACES = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?)])")
_KEYWORD_PATTERNS = tuple(
    re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])") for word in AI_KEYWORDS
)

# fpdf2's built-in fonts only know Latin-1, so map the usual typography first.
_PDF_REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": " - ", "…": "...", " ": " ",
    "•": "-", "→": "->", "™": "(TM)",
}


def html_to_text(html: str) -> str:
    """Strip tags and collapse whitespace."""
    if not html:
        return ""
    if "<" not in html:                       # plain text already: only decode &#8217; etc.
        return tidy(unescape(html))
    return tidy(BeautifulSoup(html, "html.parser").get_text(" "))


def tidy(text: str) -> str:
    """Collapse whitespace and remove the space get_text(" ") leaves before punctuation."""
    return _SPACE_BEFORE_PUNCT.sub(r"\1", _SPACES.sub(" ", text)).strip()


def truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]) + "..."


def normalize_url(url: str) -> str:
    """Same article, same key: drop query strings, fragments and trailing slashes."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), path, "", ""))


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def is_ai_related(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.search(lowered) for pattern in _KEYWORD_PATTERNS)


def pdf_safe(text: str) -> str:
    """Make any string printable with the PDF's Latin-1 fonts."""
    for bad, good in _PDF_REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = unicodedata.normalize("NFKD", text)
    return text.encode("latin-1", "ignore").decode("latin-1")
