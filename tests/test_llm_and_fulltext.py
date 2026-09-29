import json

import httpx
import pytest
from groq import APIConnectionError, NotFoundError, RateLimitError

from digest import fulltext, llm
from digest.http import FetchError
from digest.llm import GroqJSON, LLMError

pytestmark = pytest.mark.unit
REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _status_error(cls, code):
    return cls("boom", response=httpx.Response(code, request=REQUEST), body=None)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def test_missing_key_gives_a_clear_message():
    with pytest.raises(LLMError, match="GROQ_API_KEY is missing"):
        GroqJSON("", "any-model")


def test_falls_back_to_next_model_when_one_is_retired(monkeypatch):
    model = GroqJSON("test-key", "retired-model", fallbacks=("good-model",))
    tried = []

    def fake_call(name, system, user):
        tried.append(name)
        if name == "retired-model":
            raise _status_error(NotFoundError, 404)
        return {"ok": True}

    monkeypatch.setattr(model, "_call", fake_call)
    assert model.ask("s", "u") == {"ok": True}
    assert tried == ["retired-model", "good-model"]
    assert model.name == "good-model"


def test_raises_llm_error_when_every_model_fails(monkeypatch):
    model = GroqJSON("test-key", "a", fallbacks=("b",))
    errors = iter([_status_error(RateLimitError, 429), APIConnectionError(request=REQUEST)])

    def fail(*args):
        raise next(errors)

    monkeypatch.setattr(model, "_call", fail)
    with pytest.raises(LLMError, match="a: HTTP 429; b: APIConnectionError"):
        model.ask("s", "u")


def test_bad_json_counts_as_a_failure(monkeypatch):
    model = GroqJSON("test-key", "a", fallbacks=())
    monkeypatch.setattr(model, "_call", lambda *a: json.loads("not json"))
    with pytest.raises(LLMError, match="JSONDecodeError"):
        model.ask("s", "u")


def test_call_requests_json_and_low_reasoning_for_gpt_oss(monkeypatch):
    model = GroqJSON("test-key", "openai/gpt-oss-120b", fallbacks=())
    seen = {}

    class Message:
        content = '{"items": []}'

    class Response:
        choices = [type("Choice", (), {"message": Message()})()]

    def create(**kwargs):
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr(model._client.chat.completions, "create", create)
    assert model.ask("sys", "user") == {"items": []}
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["reasoning_effort"] == "low"


# --- full-text scraping --------------------------------------------------------

ARTICLE_HTML = """<html><body><nav><p>Home About Contact Subscribe to our newsletter today now</p></nav>
<article><p>Short.</p>
<p>The company announced a new language model that is twice as fast as the previous one.</p>
<p>It will be available to developers through the API starting next week, pricing unchanged.</p>
<script>var x = 1;</script></article>
<footer><p>Copyright notice with enough words to count as a paragraph here.</p></footer></body></html>"""


def test_extract_main_text_keeps_article_paragraphs_only():
    text = fulltext.extract_main_text(ARTICLE_HTML)
    assert text.startswith("The company announced")
    assert "developers" in text
    assert "Short." not in text and "newsletter" not in text and "Copyright" not in text


def test_fetch_article_text_truncates_and_handles_failures(monkeypatch):
    monkeypatch.setattr(fulltext, "polite_pause", lambda: None)
    monkeypatch.setattr(fulltext, "get", lambda url, **kw: type("R", (), {"text": ARTICLE_HTML})())
    assert fulltext.fetch_article_text("https://x", max_words=5) == "The company announced a new..."

    def blocked(url, **kw):
        raise FetchError("robots.txt disallows")

    monkeypatch.setattr(fulltext, "get", blocked)
    assert fulltext.fetch_article_text("https://x", max_words=5) is None
