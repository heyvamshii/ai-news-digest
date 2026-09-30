"""Run the whole AI News Digest pipeline once.

    python run_digest.py                  full daily run (up to 70 articles)
    python run_digest.py --demo           quick run for a live demo (20 articles, ~1 minute)
    python run_digest.py --no-llm         skip Groq, use keyword rules (works without a key)
    python run_digest.py --email          also email the newsletter through SendGrid
    python run_digest.py --email-preview  save the newsletter as an .html file instead of sending
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from digest import analysis, collectors, mailer, storage
from digest.email_html import render_html, render_text, subject_line
from digest.fulltext import fetch_article_text
from digest.llm import GroqJSON, JSONModel, LLMError
from digest.models import Digest
from digest.pdf_report import write_pdf

log = logging.getLogger("digest")

EXIT_OK, EXIT_NO_SOURCES, EXIT_EMAIL_FAILED = 0, 1, 2


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build today's AI News Digest (PDF, optionally emailed).")
    parser.add_argument("--demo", action="store_true", help="small, fast run for a live demo")
    parser.add_argument("--no-llm", action="store_true", help="don't call Groq; use keyword rules")
    parser.add_argument("--email", action="store_true", help="send the newsletter with SendGrid")
    parser.add_argument("--email-preview", action="store_true", help="save the newsletter as HTML, don't send")
    return parser.parse_args(argv)


def build_model(no_llm: bool, warnings: list[str]) -> JSONModel | None:
    if no_llm:
        return None
    try:
        return GroqJSON(config.GROQ_API_KEY, config.GROQ_MODEL)
    except LLMError as exc:
        warnings.append(str(exc))
        return None


def skipped_sources_note(warnings: list[str]) -> tuple[str, ...]:
    """One footer line naming the sources that failed today, so the reader knows."""
    skipped = [w.split(collectors.SKIPPED_MARKER)[0] for w in warnings if collectors.SKIPPED_MARKER in w]
    return (f"Unavailable today: {', '.join(skipped)}.",) if skipped else ()


def email_settings() -> mailer.EmailSettings:
    return mailer.EmailSettings(
        api_key=config.SENDGRID_API_KEY, sender=config.EMAIL_FROM, sender_name=config.EMAIL_FROM_NAME,
        recipients=config.EMAIL_TO, url=config.SENDGRID_URL,
    )


def deliver(digest: Digest, pdf_path: Path, args: argparse.Namespace) -> int:
    """Email the newsletter (or save a preview). The PDF is already safe on disk."""
    pdf_url = config.published_pdf_url(pdf_path.name)
    base = config.dashboard_url()
    issue_url = f"{base}#{digest.file_date}" if base else None
    html, text = render_html(digest, pdf_url, issue_url), render_text(digest, pdf_url, issue_url)
    if args.email_preview:
        preview = pdf_path.with_suffix(".html")
        preview.write_text(html, encoding="utf-8")
        log.info(f"      newsletter preview saved -> {preview.relative_to(config.PROJECT_DIR)}")
    if not args.email:
        return EXIT_OK
    settings = email_settings()
    try:
        mailer.send(settings, subject_line(digest), html, text)
    except mailer.EmailError as exc:
        log.info(f"      ! Email NOT sent: {exc}")
        return EXIT_EMAIL_FAILED
    log.info(f"      emailed to {len(settings.recipients)} recipient(s): {mailer.mask(settings.recipients)}")
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    digest_date = now.date().isoformat()
    max_articles = config.DEMO_MAX_ARTICLES if args.demo else config.MAX_ARTICLES
    top_count = config.DEMO_TOP_STORIES if args.demo else config.TOP_STORIES
    since = datetime.now(timezone.utc) - timedelta(hours=config.LOOKBACK_HOURS)
    total_steps = 7 if (args.email or args.email_preview) else 6
    step = lambda n, text: log.info(f"[{n}/{total_steps}] {text}")  # noqa: E731
    warnings: list[str] = []
    llm_issues: list[str] = []
    warn = lambda message: (warnings.append(message), log.info(f"      ! {message}"))  # noqa: E731
    llm_warn = lambda message: (llm_issues.append(message), warn(message))  # noqa: E731

    step(1, f"Fetching AI news from {len(config.SOURCES)} sources...")
    fetched, reachable = collectors.collect_all(
        config.SOURCES, lookback_hours=config.LOOKBACK_HOURS, per_source_limit=config.PER_SOURCE_LIMIT,
        max_articles=max_articles, on_error=warn,
    )
    log.info(f"      {len(fetched)} recent articles from {len({a.source for a in fetched})} sources "
             f"({len(reachable)} of {len(config.SOURCES)} reachable)")

    with storage.connect(config.DB_PATH) as conn:
        step(2, "Removing duplicates and saving to the database...")
        new = storage.save_new(conn, fetched)
        candidates = storage.load_candidates(conn, since=since, digest_date=digest_date, limit=max_articles)
        log.info(f"      {new} new articles saved, {len(candidates)} ready for today's digest")
        if not candidates:
            if not reachable:        # every source failed: a real problem, fail the run
                log.info("No source could be reached. Check your internet connection and try again.")
                return EXIT_NO_SOURCES
            log.info("Nothing new to report today. New articles (if any) were saved; no digest made.")
            return EXIT_OK

        model = build_model(args.no_llm, llm_issues)
        for issue in llm_issues:
            warn(issue)
        mode_label = f"Groq ({model.name})" if model else "offline keyword rules"
        step(3, f"Rating and categorising articles with {mode_label}...")
        rated = analysis.triage(candidates, model, batch_size=config.TRIAGE_BATCH_SIZE, on_error=llm_warn)
        storage.save_analysis(conn, rated)
        top, also = analysis.select(rated, top_count, config.ALSO_WORTH_KNOWING)

        step(4, f"Scraping the full text of the top {len(top)} stories...")
        texts = [fetch_article_text(a.url, config.FULL_TEXT_WORDS) or a.snippet for a in top]

        step(5, "Writing summaries with AI..." if model else "Writing summaries from each article's opening lines...")
        top, overview = analysis.summarise(top, texts, model, on_error=llm_warn)
        storage.save_analysis(conn, top)

        step(6, "Generating the one-page PDF...")
        source_order = [s.name for s in config.SOURCES]
        used_sources = sorted({a.source for a in candidates}, key=source_order.index)
        final_mode = f"Groq ({model.name})" if model and not llm_issues else (
            f"Groq ({model.name}), partly offline" if model else "offline keyword rules")
        digest = Digest(
            date_label=f"{now:%A}, {now.day} {now:%B %Y}",
            file_date=digest_date,
            overview=tuple(overview),
            top_stories=tuple(top),
            also_worth_knowing=tuple(also),
            article_count=len(candidates),
            source_names=tuple(used_sources),
            mode=final_mode,
            notes=skipped_sources_note(warnings),
        )
        pdf_path = config.REPORTS_DIR / f"AI_Digest_{digest_date}.pdf"
        printed = write_pdf(digest, pdf_path)
        storage.mark_featured(conn, (*printed.top_stories, *printed.also_worth_knowing), digest_date)
        storage.record_digest(
            conn, digest_date=digest_date, article_count=len(candidates), source_count=len(used_sources),
            top_story_count=len(printed.top_stories), mode=final_mode,
            pdf_path=str(pdf_path.relative_to(config.PROJECT_DIR)),
            content=storage.digest_content(printed),
        )

    status = EXIT_OK
    if total_steps == 7:
        step(7, "Sending the email newsletter..." if args.email else "Saving the email newsletter preview...")
        status = deliver(printed, pdf_path, args)

    log.info(f"\nDone in {time.monotonic() - started:.0f}s -> {pdf_path.relative_to(config.PROJECT_DIR)}")
    if warnings:
        log.info(f"({len(warnings)} warning(s) above; the digest was still created)")
    return status


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
