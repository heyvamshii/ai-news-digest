import pytest
import requests

import config
from digest import mailer
from digest.email_html import render_html, render_text, safe_url, subject_line
from digest.models import Digest
from tests.conftest import make_article

pytestmark = pytest.mark.unit


def _digest(**overrides) -> Digest:
    fields = dict(
        date_label="Tuesday, 29 September 2026",
        file_date="2026-09-29",
        overview=("Open models had a big day.", "Regulators moved."),
        top_stories=(make_article(1, category="Models", importance=9, summary="A lab shipped a model."),
                     make_article(2, category="Policy", importance=7, summary="A new rule passed.")),
        also_worth_knowing=(make_article(3, category="Tools"), make_article(4, category="Business")),
        article_count=40,
        source_names=("OpenAI", "The Verge AI"),
        mode="Groq (openai/gpt-oss-120b)",
        notes=("Unavailable today: Wired AI.",),
    )
    fields.update(overrides)
    return Digest(**fields)


def _settings(**overrides) -> mailer.EmailSettings:
    fields = dict(api_key="SG.test", sender="digest@example.com", sender_name="AI News Digest",
                  recipients=("me@example.com", "me2@example.org"), url="https://sendgrid.test/send")
    fields.update(overrides)
    return mailer.EmailSettings(**fields)


# --- HTML newsletter -----------------------------------------------------------

def test_newsletter_contains_every_section_and_story():
    html = render_html(_digest())
    for text in ("TODAY IN AI", "TOP STORIES", "ALSO WORTH KNOWING", "Open models had a big day.",
                 "AI story number 1", "A lab shipped a model.", "importance 9/10", "Unavailable today: Wired AI."):
        assert text in html
    assert 'href="https://example.com/story-1"' in html


def test_scraped_text_is_escaped_and_bad_links_are_blocked():
    evil = make_article(1, title='<script>alert("x")</script>', url="javascript:alert(1)",
                        category="Models", importance=5, summary="<img src=x onerror=boom>")
    html = render_html(_digest(top_stories=(evil,)))
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html
    assert "javascript:" not in html
    assert safe_url("data:text/html,hi") == "#"


def test_pdf_link_only_when_available():
    assert "Download today" not in render_html(_digest())
    html = render_html(_digest(), pdf_url="https://github.com/me/repo/blob/main/reports/x.pdf")
    assert "Download today" in html and "reports/x.pdf" in html


def test_plain_text_version_has_links():
    text = render_text(_digest(), pdf_url="https://github.com/x.pdf")
    assert "1. AI story number 1" in text
    assert "https://example.com/story-1" in text
    assert "PDF: https://github.com/x.pdf" in text
    assert "ALSO WORTH KNOWING" in text
    assert "ALSO WORTH KNOWING" not in render_text(_digest(also_worth_knowing=()))


def test_subject_line_uses_lead_story_and_stays_short():
    assert subject_line(_digest()) == "AI News Digest, Tue 29 September 2026: AI story number 1"
    long_story = make_article(1, title="word " * 60)
    assert len(subject_line(_digest(top_stories=(long_story,)))) <= 110
    assert subject_line(_digest(top_stories=())).endswith("Today's AI news")


def test_published_pdf_url_only_inside_github_actions(monkeypatch):
    monkeypatch.setattr(config, "PUBLISH", True)
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/ai-news-digest")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    assert config.published_pdf_url("a.pdf") == "https://github.com/me/ai-news-digest/blob/main/reports/a.pdf"
    monkeypatch.setattr(config, "PUBLISH", False)
    assert config.published_pdf_url("a.pdf") is None


# --- SendGrid ------------------------------------------------------------------

class FakeReply:
    def __init__(self, status: int, body=None):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_payload_sends_a_private_copy_to_each_recipient():
    payload = mailer.build_payload(_settings(), "Subject", "<p>hi</p>", "hi")
    assert payload["personalizations"] == [{"to": [{"email": "me@example.com"}]},
                                           {"to": [{"email": "me2@example.org"}]}]
    assert payload["from"] == {"email": "digest@example.com", "name": "AI News Digest"}
    assert [c["type"] for c in payload["content"]] == ["text/plain", "text/html"]


def test_send_posts_to_sendgrid_with_the_key():
    calls = []
    mailer.send(_settings(), "S", "<p>h</p>", "t",
                post=lambda url, **kw: calls.append((url, kw)) or FakeReply(202))
    url, kw = calls[0]
    assert url == "https://sendgrid.test/send"
    assert kw["headers"]["Authorization"] == "Bearer SG.test"
    assert kw["json"]["subject"] == "S"


@pytest.mark.parametrize("settings, message", [
    (_settings(api_key=""), "SENDGRID_API_KEY"),
    (_settings(sender="", recipients=()), "EMAIL_FROM, EMAIL_TO"),
    (_settings(recipients=("not-an-email",)), r"Not a valid email address: no\*\*\*$"),
    (_settings(recipients=("jane.doe@gmail",)), r"Not a valid email address: ja\*\*\*@gmail$"),
])
def test_missing_or_bad_settings_fail_before_calling_sendgrid(settings, message):
    with pytest.raises(mailer.EmailError, match=message):
        mailer.send(settings, "S", "h", "t", post=lambda *a, **k: pytest.fail("must not call SendGrid"))


def test_sendgrid_errors_are_explained():
    body = {"errors": [{"message": "The from address does not match a verified Sender Identity."}]}
    with pytest.raises(mailer.EmailError, match="verified sender.*does not match a verified Sender"):
        mailer.send(_settings(), "S", "h", "t", post=lambda *a, **k: FakeReply(403, body))
    with pytest.raises(mailer.EmailError, match="HTTP 500: unexpected reply from SendGrid$"):
        mailer.send(_settings(), "S", "h", "t", post=lambda *a, **k: FakeReply(500))


def test_network_failure_is_reported():
    def down(*args, **kwargs):
        raise requests.ConnectionError("no route")

    with pytest.raises(mailer.EmailError, match="Could not reach SendGrid: ConnectionError"):
        mailer.send(_settings(), "S", "h", "t", post=down)


def test_mask_hides_most_of_the_address():
    assert mailer.mask(["jane.doe@gmail.com", "x@y.io"]) == "ja***@gmail.com, x***@y.io"


def test_addresses_echoed_by_sendgrid_are_masked_in_errors():
    body = {"errors": [{"message": "Does not contain a valid address: jane.doe@gmail.com"}]}
    with pytest.raises(mailer.EmailError) as caught:
        mailer.send(_settings(), "S", "h", "t", post=lambda *a, **k: FakeReply(400, body))
    assert "jane.doe" not in str(caught.value)
    assert "ja***@gmail.com" in str(caught.value)


def test_dashboard_link_appears_in_email_when_configured():
    url = "https://ai-news-digest.vercel.app/#2026-09-29"
    html = render_html(_digest(), dashboard_url=url)
    assert "Open in the dashboard" in html and url in html
    assert "Open in the dashboard" not in render_html(_digest())
    assert f"Dashboard: {url}" in render_text(_digest(), dashboard_url=url)
