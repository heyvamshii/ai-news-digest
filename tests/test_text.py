import pytest

from digest.text import html_to_text, is_ai_related, normalize_title, normalize_url, pdf_safe, truncate_words

pytestmark = pytest.mark.unit


def test_html_to_text_strips_tags_and_whitespace():
    assert html_to_text("<p>Hello <b>AI</b>\n\n world</p>") == "Hello AI world"


def test_html_to_text_passes_plain_text_through():
    assert html_to_text("  plain   text ") == "plain text"
    assert html_to_text("") == ""


def test_truncate_words_adds_ellipsis_only_when_cut():
    assert truncate_words("one two three", 5) == "one two three"
    assert truncate_words("one two three four", 2) == "one two..."


def test_normalize_url_ignores_tracking_www_and_trailing_slash():
    a = normalize_url("https://www.Example.com/post/?utm_source=rss#top")
    b = normalize_url("https://example.com/post")
    assert a == b


def test_normalize_title_ignores_case_and_punctuation():
    assert normalize_title("OpenAI's New Model!") == normalize_title("openais new model")


@pytest.mark.parametrize("text, expected", [
    ("OpenAI releases GPT-6", True),
    ("New AI chip from NVIDIA", True),
    ("Researchers train an LLM", True),
    ("The mayor said it would rain", False),     # 'ai' inside 'said' / 'rain' must not match
    ("Best pizza in Chicago", False),
])
def test_is_ai_related_uses_whole_words(text, expected):
    assert is_ai_related(text) is expected


def test_pdf_safe_converts_typography_and_drops_unsupported():
    assert pdf_safe("“Smart” — it’s café \U0001F680") == '"Smart"  -  it\'s cafe '
    pdf_safe("中文").encode("latin-1")   # never raises


def test_html_to_text_decodes_entities_in_plain_titles():
    assert html_to_text("The SaaSpocalypse that wasn&#8217;t &amp; more") == "The SaaSpocalypse that wasn’t & more"
