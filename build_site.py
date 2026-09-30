"""Build the web dashboard from the database.

    python build_site.py     writes reports/local/site/  (open index.html via a local server)
    In GitHub Actions (DIGEST_PUBLISH=1) it writes docs/, which Vercel publishes.

Preview locally:
    python -m http.server 8000 --directory reports/local/site
    then open http://localhost:8000
"""

import logging
import sys

import config
from digest.site_export import export_site

log = logging.getLogger("digest")


def pdf_link(file_name: str) -> str:
    """Published: the PDF on GitHub. Local: the PDF sitting next to the site folder."""
    return config.published_pdf_url(file_name) or f"../{file_name}"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)
    if not config.DB_PATH.exists():
        log.info(f"No database at {config.DB_PATH.name} yet. Run: python run_digest.py")
        return 1
    summary = export_site(config.DB_PATH, config.SITE_DIR, pdf_link)
    log.info(f"Dashboard built: {summary['issues']} issue(s), {summary['articles']} searchable articles "
             f"-> {config.SITE_DIR.relative_to(config.PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
