"""Scrape the body text of an article page (used only for the top stories)."""

from bs4 import BeautifulSoup

from digest.http import FetchError, get, polite_pause
from digest.text import tidy, truncate_words

MIN_PARAGRAPH_WORDS = 8
NOISE_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "figure")


def extract_main_text(html: str) -> str:
    """Prefer <article>, then <main>, then the whole page; keep real paragraphs only."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = (p.get_text(" ", strip=True) for p in container.find_all("p"))
    return tidy(" ".join(p for p in paragraphs if len(p.split()) >= MIN_PARAGRAPH_WORDS))


def fetch_article_text(url: str, max_words: int) -> str | None:
    """Return up to max_words of the article, or None if the page can't be read."""
    try:
        html = get(url, check_robots=True).text
    except FetchError:
        return None
    finally:
        polite_pause()
    text = extract_main_text(html)
    return truncate_words(text, max_words) if text else None
