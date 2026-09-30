"""Turn a Digest into an HTML newsletter (plus a plain-text copy for old mail apps).

Email apps ignore <style> blocks and modern CSS, so this uses the old, reliable
recipe: tables for layout and inline styles on every element.
"""

from html import escape
from itertools import groupby

from config import CATEGORIES
from digest.models import Article, Digest

INK, MUTED, ACCENT = "#181c28", "#6e7482", "#e05624"
BAND, TINT, PAGE, CARD = "#141826", "#fdf3ed", "#eef0f4", "#ffffff"
FONT = "font-family:Helvetica,Arial,sans-serif;"
SUBJECT_MAX = 110
CATEGORY_ORDER = {c: i for i, c in enumerate(CATEGORIES)}


def safe_url(url: str) -> str:
    """Only real web links make it into the email (no javascript: or data: tricks)."""
    return escape(url, quote=True) if url.lower().startswith(("https://", "http://")) else "#"


def subject_line(digest: Digest) -> str:
    lead = digest.top_stories[0].title if digest.top_stories else "Today's AI news"
    subject = f"AI News Digest, {digest.date_label.split(',')[0][:3]} {digest.date_label.split(', ')[-1]}: {lead}"
    return subject if len(subject) <= SUBJECT_MAX else subject[:SUBJECT_MAX - 3].rstrip() + "..."


def _p(text: str, style: str) -> str:
    return f'<p style="margin:0;{FONT}{style}">{text}</p>'


def _header(digest: Digest) -> str:
    stats = (f"{digest.article_count} articles scanned &nbsp;|&nbsp; {len(digest.source_names)} sources "
             f"&nbsp;|&nbsp; top {len(digest.top_stories)} stories")
    return (
        f'<tr><td style="background:{BAND};padding:26px 28px 22px;">'
        + _p("AI NEWS DIGEST", "color:#ffffff;font-size:24px;font-weight:bold;letter-spacing:1px;")
        + _p(escape(digest.date_label), "color:#d7dae2;font-size:14px;padding-top:4px;")
        + _p(stats, f"color:{ACCENT};font-size:12px;padding-top:8px;")
        + "</td></tr>"
    )


def _overview(points: tuple[str, ...]) -> str:
    items = "".join(
        f'<tr><td style="width:14px;vertical-align:top;padding:6px 0 0;color:{ACCENT};font-size:14px;">&#9632;</td>'
        f'<td style="padding:3px 0;{FONT}color:{INK};font-size:15px;line-height:22px;">{escape(p)}</td></tr>'
        for p in points
    )
    return (
        f'<tr><td style="padding:22px 28px 0;"><table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" style="background:{TINT};border-radius:6px;"><tr><td style="padding:16px 18px;">'
        + _p("TODAY IN AI", f"color:{ACCENT};font-size:13px;font-weight:bold;letter-spacing:1px;padding-bottom:6px;")
        + f'<table role="presentation" cellpadding="0" cellspacing="0">{items}</table>'
        + "</td></tr></table></td></tr>"
    )


def _section_title(title: str) -> str:
    return (f'<tr><td style="padding:26px 28px 4px;">'
            + _p(escape(title.upper()), f"color:{ACCENT};font-size:13px;font-weight:bold;letter-spacing:1px;")
            + f'<div style="width:36px;height:3px;background:{ACCENT};margin-top:6px;"></div></td></tr>')


def _story(number: int, story: Article) -> str:
    meta = " &nbsp;|&nbsp; ".join(
        escape(str(part)) for part in (story.source, story.category, f"importance {story.importance}/10")
    )
    return (
        f'<tr><td style="padding:14px 28px 0;">'
        f'<a href="{safe_url(story.url)}" style="{FONT}color:{INK};font-size:17px;font-weight:bold;'
        f'line-height:23px;text-decoration:none;">{number}. {escape(story.title)}</a>'
        + _p(meta, f"color:{MUTED};font-size:12px;padding:4px 0 6px;")
        + _p(escape(story.summary or ""), f"color:{INK};font-size:15px;line-height:22px;")
        + f'<p style="margin:0;padding-top:6px;{FONT}font-size:13px;"><a href="{safe_url(story.url)}" '
        f'style="color:{ACCENT};text-decoration:none;font-weight:bold;">Read the article &rarr;</a></p>'
        + "</td></tr>"
    )


def _also(articles: tuple[Article, ...]) -> str:
    if not articles:
        return ""
    ordered = sorted(articles, key=lambda a: CATEGORY_ORDER.get(a.category or "", 99))
    blocks = []
    for category, group in groupby(ordered, key=lambda a: a.category):
        links = "".join(
            f'<li style="margin:0 0 6px;{FONT}font-size:14px;line-height:20px;color:{INK};">'
            f'<a href="{safe_url(a.url)}" style="color:{INK};text-decoration:underline;">{escape(a.title)}</a>'
            f' <span style="color:{MUTED};">({escape(a.source)})</span></li>'
            for a in group
        )
        blocks.append(_p(escape(category or "Other"), f"color:{INK};font-size:14px;font-weight:bold;padding-top:10px;")
                      + f'<ul style="margin:6px 0 0;padding-left:20px;">{links}</ul>')
    return _section_title("Also worth knowing") + f'<tr><td style="padding:0 28px;">{"".join(blocks)}</td></tr>'


def _link_line(url: str | None, text: str) -> str:
    if not url:
        return ""
    return (f'<p style="margin:0 0 10px;{FONT}font-size:13px;"><a href="{safe_url(url)}" '
            f'style="color:{ACCENT};font-weight:bold;text-decoration:none;">{text} &rarr;</a></p>')


def _footer(digest: Digest, pdf_url: str | None, dashboard_url: str | None = None) -> str:
    lines = [f"Sources: {escape(', '.join(digest.source_names))}.",
             f"Summaries: {escape(digest.mode)}.",
             *(escape(n) for n in digest.notes)]
    links = (_link_line(dashboard_url, "Open in the dashboard: past issues, search, charts")
             + _link_line(pdf_url, "Download today's one-page PDF"))
    return (f'<tr><td style="padding:28px 28px 26px;border-top:1px solid #e3e5ea;">{links}'
            + _p("<br>".join(lines), f"color:{MUTED};font-size:12px;line-height:18px;")
            + "</td></tr>")


def render_html(digest: Digest, pdf_url: str | None = None, dashboard_url: str | None = None) -> str:
    stories = "".join(_story(i, s) for i, s in enumerate(digest.top_stories, start=1))
    preheader = escape(digest.overview[0]) if digest.overview else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>AI News Digest</title></head>
<body style="margin:0;padding:0;background:{PAGE};">
<div style="display:none;max-height:0;overflow:hidden;">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE};">
<tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:620px;background:{CARD};border-radius:8px;overflow:hidden;">
{_header(digest)}{_overview(digest.overview)}{_section_title("Top stories")}{stories}{_also(digest.also_worth_knowing)}{_footer(digest, pdf_url, dashboard_url)}
</table></td></tr></table></body></html>"""


def render_text(digest: Digest, pdf_url: str | None = None, dashboard_url: str | None = None) -> str:
    """Plain-text version; spam filters like emails that include one."""
    lines = [f"AI NEWS DIGEST - {digest.date_label}", "", "TODAY IN AI"]
    lines += [f"- {p}" for p in digest.overview]
    lines += ["", "TOP STORIES"]
    for i, s in enumerate(digest.top_stories, start=1):
        lines += [f"{i}. {s.title}", f"   {s.source} | {s.category} | importance {s.importance}/10",
                  f"   {s.summary or ''}", f"   {s.url}", ""]
    if digest.also_worth_knowing:
        lines += ["ALSO WORTH KNOWING"] + [f"- {a.title} ({a.source}) {a.url}" for a in digest.also_worth_knowing]
    if dashboard_url or pdf_url:
        lines.append("")
    if dashboard_url:
        lines.append(f"Dashboard: {dashboard_url}")
    if pdf_url:
        lines.append(f"PDF: {pdf_url}")
    lines += ["", f"Sources: {', '.join(digest.source_names)}."]
    return "\n".join(lines)
