"""All the settings for the AI News Digest in one place."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"

# GitHub Actions sets DIGEST_PUBLISH=1 and writes the files that get committed.
# Runs on your laptop use separate, git-ignored files, so `git pull` never conflicts.
PUBLISHED_DB_PATH = DATA_DIR / "news.db"
PUBLISH = os.getenv("DIGEST_PUBLISH") == "1"
DB_PATH = PUBLISHED_DB_PATH if PUBLISH else DATA_DIR / "local.db"
REPORTS_DIR = PROJECT_DIR / "reports" if PUBLISH else PROJECT_DIR / "reports" / "local"

# Digest dates follow Indian time, so "today" matches the reader's day.
TIMEZONE = "Asia/Kolkata"

# --- Collection limits -------------------------------------------------------
LOOKBACK_HOURS = 72          # company blogs post weekly, so look back 3 days
                             # (the database stops a story repeating on later days)
PER_SOURCE_LIMIT = 8         # no single source can flood the digest
MAX_ARTICLES = 70            # daily cap, keeps us inside Groq's free tier
DEMO_MAX_ARTICLES = 20       # smaller run for the live demo

# --- What goes on the one-page PDF ------------------------------------------
TOP_STORIES = 6
DEMO_TOP_STORIES = 4
ALSO_WORTH_KNOWING = 10      # extra one-line headlines under the top stories
FULL_TEXT_WORDS = 450        # words of each top story sent to the LLM

# --- Scraping manners --------------------------------------------------------
USER_AGENT = "Mozilla/5.0 (compatible; AI-News-Digest/1.0; student project)"
REQUEST_TIMEOUT = 15
POLITE_DELAY_SECONDS = 1.0

# --- LLM (Groq) --------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = (os.getenv("GROQ_MODEL") or "").strip() or "openai/gpt-oss-120b"   # blank = default
FALLBACK_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile")
TRIAGE_BATCH_SIZE = 20
LLM_PAUSE_SECONDS = 2.0
LLM_MAX_RETRIES = 4

CATEGORIES = ("Models", "Research", "Tools", "Business", "Policy")

# --- Email (SendGrid) -------------------------------------------------------
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()              # must be verified in SendGrid
EMAIL_TO = tuple(a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip())
EMAIL_FROM_NAME = "AI News Digest"


def published_pdf_url(file_name: str) -> str | None:
    """Link to the PDF on GitHub. Only known inside GitHub Actions (else None)."""
    server, repo = os.getenv("GITHUB_SERVER_URL"), os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME") or "main"
    if not (PUBLISH and server and repo):
        return None
    return f"{server}/{repo}/blob/{branch}/reports/{file_name}"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    kind: str                 # "rss", "scrape" or "hn"
    ai_only: bool = True      # False = mixed-topic source, filter by AI keywords
    weight: int = 5           # 1-10, used only when the LLM is unavailable


SOURCES: tuple[Source, ...] = (
    Source("OpenAI", "https://openai.com/news/rss.xml", "rss", weight=9),
    Source("Google DeepMind", "https://deepmind.google/blog/rss.xml", "rss", weight=9),
    Source("Anthropic", "https://www.anthropic.com/news", "scrape", weight=9),
    Source("Google AI Blog", "https://blog.google/technology/ai/rss/", "rss", weight=7),
    Source("Hugging Face", "https://huggingface.co/blog/feed.xml", "rss", weight=7),
    Source("NVIDIA Blog", "https://blogs.nvidia.com/feed/", "rss", ai_only=False, weight=6),
    Source("AWS ML Blog", "https://aws.amazon.com/blogs/machine-learning/feed/", "rss", weight=5),
    Source("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "rss", weight=7),
    Source("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "rss", weight=7),
    Source("MIT Tech Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "rss", weight=7),
    Source("Ars Technica AI", "https://arstechnica.com/ai/feed/", "rss", weight=6),
    Source("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss", "rss", weight=6),
    Source("arXiv cs.AI", "https://rss.arxiv.org/rss/cs.AI", "rss", weight=4),
    Source("Hacker News", "https://hn.algolia.com/api/v1/search_by_date", "hn", ai_only=False, weight=5),
)

AI_KEYWORDS = (
    "ai", "a.i.", "artificial intelligence", "llm", "gpt", "claude", "gemini", "llama",
    "openai", "anthropic", "deepmind", "machine learning", "neural network", "agi",
    "chatbot", "transformer", "diffusion model", "copilot", "mistral", "ai agent",
)
