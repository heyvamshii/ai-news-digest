import pytest

from digest.models import Digest
from digest.pdf_report import MIN_TOP_STORIES, render, write_pdf
from tests.conftest import make_article

pytestmark = pytest.mark.unit


def _digest(top: int, also: int, summary_words: int = 40) -> Digest:
    summary = " ".join(["word"] * summary_words)
    return Digest(
        date_label="Monday, 28 September 2026",
        file_date="2026-09-28",
        overview=("Point one about “AI” — today.", "Point two.", "Point three."),
        top_stories=tuple(make_article(i, category="Models", importance=8, summary=summary) for i in range(top)),
        also_worth_knowing=tuple(make_article(100 + i, category=("Tools", "Policy")[i % 2]) for i in range(also)),
        article_count=55,
        source_names=("OpenAI", "TechCrunch AI"),
        mode="Groq (openai/gpt-oss-120b)",
    )


def test_normal_digest_fits_on_one_page(tmp_path):
    path = tmp_path / "digest.pdf"
    printed = write_pdf(_digest(top=6, also=10), path)
    assert path.read_bytes().startswith(b"%PDF")
    assert len(printed.top_stories) == 6
    assert render(printed).page_no() == 1


def test_overlong_digest_is_trimmed_to_one_page(tmp_path):
    printed = write_pdf(_digest(top=12, also=30, summary_words=60), tmp_path / "long.pdf")
    assert render(printed).page_no() == 1
    assert len(printed.also_worth_knowing) < 30
    assert len(printed.top_stories) >= MIN_TOP_STORIES


def test_unicode_and_offline_mode_render(tmp_path):
    digest = _digest(top=3, also=0)
    digest = type(digest)(**{**digest.__dict__, "mode": "offline keyword rules",
                             "notes": ("Emoji \U0001F680 and 中文 are dropped safely",)})
    write_pdf(digest, tmp_path / "offline.pdf")
    assert (tmp_path / "offline.pdf").stat().st_size > 1000
