"""Whole pipeline, end to end, with fake network and a fake LLM."""

from datetime import datetime, timedelta, timezone

import pytest

import config
import run_digest
import show_db
from digest import collectors, storage
from tests.conftest import FakeModel, make_article

pytestmark = pytest.mark.integration


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "local.db")
    monkeypatch.setattr(config, "PUBLISHED_DB_PATH", tmp_path / "data" / "news.db")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "GROQ_API_KEY", "test-key")
    recent = datetime.now(timezone.utc) - timedelta(hours=2)

    def fake_fetch(source, since):
        if source.name == "Wired AI":
            raise collectors.FetchError("503")
        return [make_article(i, source=source.name, url=f"https://{source.name.replace(' ', '')}.com/{i}",
                             title=f"{source.name} AI news {i}", published_at=recent - timedelta(minutes=i))
                for i in range(4)]

    monkeypatch.setattr(collectors, "fetch_source", fake_fetch)
    monkeypatch.setattr(run_digest, "fetch_article_text", lambda url, words: "Full article text. More text.")
    return tmp_path


def _pdfs(project):
    return list((project / "reports").glob("AI_Digest_*.pdf"))


def test_demo_run_with_ai_builds_pdf_and_fills_database(project, monkeypatch, capsys):
    monkeypatch.setattr(run_digest, "GroqJSON", lambda key, model: FakeModel())
    assert run_digest.main(["--demo"]) == 0

    out = capsys.readouterr().out
    assert "[6/6] Generating the one-page PDF" in out
    assert "Wired AI skipped" in out
    assert len(_pdfs(project)) == 1
    with storage.connect(config.DB_PATH) as conn:
        s = storage.stats(conn)
        mode = conn.execute("SELECT mode FROM digests").fetchone()[0]
    assert s["articles"] == config.DEMO_MAX_ARTICLES
    assert s["summarised"] == config.DEMO_TOP_STORIES
    assert mode == "Groq (fake-model)"


def test_same_day_rerun_still_produces_a_full_digest(project, monkeypatch, capsys):
    monkeypatch.setattr(run_digest, "GroqJSON", lambda key, model: FakeModel())
    run_digest.main(["--demo"])
    assert run_digest.main(["--demo"]) == 0
    assert "0 new articles saved" in capsys.readouterr().out
    with storage.connect(config.DB_PATH) as conn:
        assert storage.stats(conn)["digests"] == 1


def test_no_llm_flag_runs_fully_offline(project, monkeypatch):
    monkeypatch.setattr(run_digest, "GroqJSON", lambda *a: pytest.fail("Groq must not be called"))
    assert run_digest.main(["--no-llm"]) == 0
    with storage.connect(config.DB_PATH) as conn:
        assert conn.execute("SELECT mode FROM digests").fetchone()[0] == "offline keyword rules"


def test_missing_key_falls_back_to_offline_with_a_warning(project, monkeypatch, capsys):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    assert run_digest.main([]) == 0
    assert "GROQ_API_KEY is missing" in capsys.readouterr().out


def test_llm_outage_still_creates_the_pdf(project, monkeypatch):
    monkeypatch.setattr(run_digest, "GroqJSON", lambda key, model: FakeModel(fail=True))
    assert run_digest.main(["--demo"]) == 0
    with storage.connect(config.DB_PATH) as conn:
        assert "partly offline" in conn.execute("SELECT mode FROM digests").fetchone()[0]


def test_quiet_news_day_is_not_an_error(project, monkeypatch, capsys):
    monkeypatch.setattr(collectors, "fetch_source", lambda source, since: [])
    assert run_digest.main(["--no-llm"]) == 0
    assert "Nothing new to report today" in capsys.readouterr().out
    assert _pdfs(project) == []


def test_every_source_down_fails_the_run(project, monkeypatch, capsys):
    def down(source, since):
        raise collectors.FetchError("offline")

    monkeypatch.setattr(collectors, "fetch_source", down)
    assert run_digest.main(["--no-llm"]) == 1
    assert "No source could be reached" in capsys.readouterr().out


def test_skipped_sources_are_named_in_the_pdf_footer():
    warnings = ["Wired AI skipped: 503", "AI rating failed", "OpenAI skipped: timeout"]
    assert run_digest.skipped_sources_note(warnings) == ("Unavailable today: Wired AI, OpenAI.",)
    assert run_digest.skipped_sources_note(["AI rating failed"]) == ()


def test_show_db_prints_summary(project, monkeypatch, capsys):
    assert show_db.main([]) == 1                     # before any run
    run_digest.main(["--no-llm", "--demo"])
    capsys.readouterr()
    assert show_db.main([]) == 0
    out = capsys.readouterr().out
    assert "Articles stored     : 20" in out
    assert "Recent digests" in out
    assert show_db.main(["--published"]) == 1        # GitHub's database not pulled yet
    assert "git pull" in capsys.readouterr().out


@pytest.fixture
def email_config(monkeypatch):
    monkeypatch.setattr(config, "SENDGRID_API_KEY", "SG.test")
    monkeypatch.setattr(config, "EMAIL_FROM", "digest@example.com")
    monkeypatch.setattr(config, "EMAIL_TO", ("me@example.com", "me2@example.org"))


def test_email_flag_sends_the_newsletter(project, email_config, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(run_digest.mailer, "send", lambda settings, subject, html, text: sent.append(
        (settings.recipients, subject, html)))
    assert run_digest.main(["--no-llm", "--demo", "--email"]) == 0
    recipients, subject, html = sent[0]
    assert recipients == ("me@example.com", "me2@example.org")
    assert subject.startswith("AI News Digest, ")
    assert "TOP STORIES" in html
    out = capsys.readouterr().out
    assert "[7/7] Sending the email newsletter" in out
    assert "emailed to 2 recipient(s): me***@example.com, me***@example.org" in out


def test_email_failure_keeps_the_pdf_and_database_but_exits_2(project, email_config, monkeypatch, capsys):
    def broken(*args):
        raise run_digest.mailer.EmailError("HTTP 401: the SendGrid API key is wrong")

    monkeypatch.setattr(run_digest.mailer, "send", broken)
    assert run_digest.main(["--no-llm", "--demo", "--email"]) == run_digest.EXIT_EMAIL_FAILED
    assert "Email NOT sent: HTTP 401" in capsys.readouterr().out
    assert len(_pdfs(project)) == 1
    with storage.connect(config.DB_PATH) as conn:
        assert storage.stats(conn)["digests"] == 1


def test_email_preview_saves_html_without_sending(project, monkeypatch):
    monkeypatch.setattr(run_digest.mailer, "send", lambda *a: pytest.fail("preview must not send"))
    assert run_digest.main(["--no-llm", "--demo", "--email-preview"]) == 0
    [preview] = (project / "reports").glob("AI_Digest_*.html")
    assert "TODAY IN AI" in preview.read_text(encoding="utf-8")
