"""Step 5: lay the digest out on exactly one A4 page."""

from dataclasses import replace
from itertools import groupby
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from config import CATEGORIES
from digest.models import Article, Digest
from digest.text import pdf_safe

MIN_TOP_STORIES = 3
MARGIN = 14
INK = (24, 28, 40)
MUTED = (110, 116, 130)
ACCENT = (224, 86, 36)          # orange: headings, rules, bullets
BAND = (20, 24, 38)             # dark header band
TINT = (253, 243, 237)          # light orange panel behind "Today in AI"
CATEGORY_ORDER = {c: i for i, c in enumerate(CATEGORIES)}


class DigestPDF(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=12)
        self.add_page()

    @property
    def width(self) -> float:
        return self.w - 2 * MARGIN

    def font(self, style: str = "", size: float = 9, color=INK):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)

    def section(self, title: str):
        self.ln(2.5)
        self.font("B", 11, ACCENT)
        self.cell(0, 6, pdf_safe(title.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.5)
        self.line(MARGIN, self.get_y(), MARGIN + 22, self.get_y())
        self.ln(2)

    def bullet(self, text: str, *, size: float = 9, link: str = "", indent: float = 0):
        x = MARGIN + indent
        self.set_fill_color(*ACCENT)
        self.rect(x + 0.6, self.get_y() + 1.7, 1.3, 1.3, style="F")
        self.set_x(x + 4)
        self.font("", size)
        self.multi_cell(self.width - indent - 4, 4.3, pdf_safe(text), link=link, align="L",
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _header(pdf: DigestPDF, digest: Digest):
    pdf.set_fill_color(*BAND)
    pdf.rect(0, 0, pdf.w, 27, style="F")
    pdf.set_xy(MARGIN, 7)
    pdf.font("B", 20, (255, 255, 255))
    pdf.cell(pdf.width / 2, 9, "AI NEWS DIGEST")
    pdf.font("", 10, (215, 218, 226))
    pdf.cell(pdf.width / 2, 9, pdf_safe(digest.date_label), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.font("", 8, ACCENT)
    how = "summarised by AI" if digest.mode.startswith("Groq") else "summarised offline"
    stats = (f"{digest.article_count} articles scanned  |  {len(digest.source_names)} sources  |  "
             f"top {len(digest.top_stories)} stories {how}")
    pdf.cell(0, 5, stats, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(31)


def _overview(pdf: DigestPDF, points: tuple[str, ...]):
    """Tinted panel: measure the wrapped bullets first so the box fits them."""
    pdf.font("", 9.5)
    line_count = sum(
        len(pdf.multi_cell(pdf.width - 4, 4.3, pdf_safe(p), dry_run=True, output=MethodReturnValue.LINES))
        for p in points
    )
    top, height = pdf.get_y(), 9 + 4.3 * line_count + 2
    pdf.set_fill_color(*TINT)
    pdf.rect(MARGIN - 3, top, pdf.width + 6, height, style="F")
    pdf.set_xy(MARGIN, top + 2)
    pdf.font("B", 11, ACCENT)
    pdf.cell(0, 5, "TODAY IN AI", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    for point in points:
        pdf.bullet(point, size=9.5)
    pdf.set_y(top + height)


def _top_stories(pdf: DigestPDF, stories: tuple[Article, ...]):
    pdf.section("Top stories")
    for number, story in enumerate(stories, start=1):
        pdf.font("B", 10)
        pdf.multi_cell(pdf.width, 4.8, pdf_safe(f"{number}. {story.title}"), link=story.url,
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.font("", 7.5, MUTED)
        meta = f"{story.source}  |  {story.category}  |  importance {story.importance}/10  |  " \
               f"{story.published_at:%d %b}"
        pdf.cell(0, 4, pdf_safe(meta), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.font("", 9)
        pdf.multi_cell(pdf.width, 4.3, pdf_safe(story.summary or ""), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.8)


def _also(pdf: DigestPDF, articles: tuple[Article, ...]):
    if not articles:
        return
    pdf.section("Also worth knowing")
    ordered = sorted(articles, key=lambda a: CATEGORY_ORDER.get(a.category or "", 99))
    for category, group in groupby(ordered, key=lambda a: a.category):
        pdf.font("B", 8.5)
        pdf.cell(0, 4.6, pdf_safe(category or "Other"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for article in group:
            pdf.bullet(f"{article.title}  ({article.source})", size=8.5, link=article.url, indent=2)


def _footer(pdf: DigestPDF, digest: Digest):
    pdf.ln(2)
    pdf.set_draw_color(*MUTED)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN, pdf.get_y(), pdf.w - MARGIN, pdf.get_y())
    pdf.ln(1)
    pdf.font("", 6.5, MUTED)
    lines = [f"Sources: {', '.join(digest.source_names)}.",
             f"Generated automatically | summaries: {digest.mode} | click any headline to open the article."]
    lines.extend(digest.notes)
    pdf.multi_cell(pdf.width, 3.2, pdf_safe("\n".join(lines)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def render(digest: Digest) -> DigestPDF:
    pdf = DigestPDF()
    _header(pdf, digest)
    _overview(pdf, digest.overview)
    _top_stories(pdf, digest.top_stories)
    _also(pdf, digest.also_worth_knowing)
    _footer(pdf, digest)
    return pdf


def fit_to_one_page(digest: Digest) -> tuple[DigestPDF, Digest]:
    """Drop the least important items until everything fits on a single page."""
    while True:
        pdf = render(digest)
        if pdf.page_no() <= 1:
            return pdf, digest
        if digest.also_worth_knowing:
            digest = replace(digest, also_worth_knowing=digest.also_worth_knowing[:-1])
        elif len(digest.top_stories) > MIN_TOP_STORIES:
            digest = replace(digest, top_stories=digest.top_stories[:-1])
        else:
            return pdf, digest            # can't shrink further; accept a second page


def write_pdf(digest: Digest, path: Path) -> Digest:
    """Save the PDF and return the digest exactly as printed (after any trimming)."""
    pdf, printed = fit_to_one_page(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return printed
