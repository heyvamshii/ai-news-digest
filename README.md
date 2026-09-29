# AI News Digest

Every morning this project collects the latest AI news from 14 sources, stores it in a
database, uses an LLM (Groq) to rank and summarise it, **emails an HTML newsletter** (SendGrid)
and saves a **one-page PDF briefing**. It runs automatically every day on GitHub Actions: no laptop needed.

```
 GitHub Actions (08:00 IST daily)  or  python run_digest.py
                 |
  [1] COLLECT    12 RSS feeds  +  anthropic.com/news (HTML scraping)  +  Hacker News API
                 -> last 72 hours, max 8 per source, max 70 per day
  [2] STORE      remove duplicates (URL + title), save to SQLite (data/news.db)
  [3] RATE       Groq LLM: category (Models/Research/Tools/Business/Policy) + importance 1-10
  [4] SCRAPE     download full article text for the top stories (robots.txt respected)
  [5] SUMMARISE  Groq LLM: 45-word summaries + 3 "Today in AI" bullets
  [6] PUBLISH    one-page PDF -> reports/AI_Digest_YYYY-MM-DD.pdf
  [7] EMAIL      HTML newsletter to your inbox via SendGrid (with a link to the PDF)
```

## What makes it more than a script

| Feature | How |
|---|---|
| Three data-collection methods | RSS parsing (`feedparser`), HTML scraping (`BeautifulSoup`), REST API (Hacker News) |
| Ethical scraping | Checks each site's `robots.txt`, identifies itself with a User-Agent, pauses between requests |
| Database with history | SQLite; duplicates blocked by a unique key; each story appears in only one day's digest |
| AI that fits the free tier | Articles are rated in batches of 20 and summaries are written in one call: about 5 LLM calls a day |
| Never breaks | A failing source is skipped. If Groq is down or the key is missing, keyword rules take over and the PDF is still produced |
| Always one page | The layout drops the least important items until the page fits |
| Safe email | All scraped text is HTML-escaped and only http(s) links are allowed; each recipient gets a private copy |
| Tested | 84 automated tests, 99% coverage, no network or API key needed |

## Setup (one time)

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env           # then fill in your keys (see comments inside)
```

Get a free Groq key at <https://console.groq.com/keys>.

### SendGrid (for the email)

1. Create a SendGrid account.
2. **Settings -> Sender Authentication -> Verify a Single Sender**: enter the address the emails
   come from, then click the link SendGrid emails you.
3. **Settings -> API Keys -> Create API Key -> Restricted Access**, and turn on only **Mail Send**.
4. Put `SENDGRID_API_KEY`, `EMAIL_FROM` (the verified address) and `EMAIL_TO` (comma-separated)
   in `.env`.

The first emails may land in spam, because the sender is a personal address rather than your
own domain. Mark one as "Not spam".

## Commands

| Command | What it does |
|---|---|
| `python run_digest.py` | Full daily run (up to 70 articles, 6 top stories) |
| `python run_digest.py --demo` | Quick run for a live demo (20 articles, 4 top stories, under a minute) |
| `python run_digest.py --no-llm` | Run without Groq (keyword rules). Works with no key at all |
| `python run_digest.py --email` | Also send the newsletter with SendGrid |
| `python run_digest.py --email-preview` | Save the newsletter as an `.html` file next to the PDF, without sending |
| `python show_db.py` | Show what your local runs stored |
| `python show_db.py --published` | Show the daily history built by GitHub Actions (after `git pull`) |
| `start reports\local\AI_Digest_YYYY-MM-DD.pdf` | Open a PDF from a local run (Windows) |
| `pytest --cov=.` | Run the tests with a coverage report |

Running twice on the same day is safe: the second run rebuilds the same day's digest.
Exit codes: `0` OK, `1` no source reachable, `2` digest built but the email failed.

**Local vs published output.** Runs on your laptop write to `data/local.db` and `reports/local/`
(ignored by git). Only GitHub Actions (which sets `DIGEST_PUBLISH=1`) writes `data/news.db` and
`reports/*.pdf`, the files that get committed. Local runs therefore never conflict with `git pull`.

## Automatic daily run (GitHub Actions)

The workflow in `.github/workflows/daily-digest.yml`:

1. runs every day at **08:00 IST** (and whenever you press **Run workflow** on the Actions tab),
2. builds the digest and emails the newsletter (manual runs have an "email" checkbox),
3. commits `reports/AI_Digest_<date>.pdf` and `data/news.db` back to the repository,
   even if the email failed, so no day is lost,
4. attaches the PDF to the run as a downloadable artifact.

One-time setup: repo **Settings -> Secrets and variables -> Actions -> New repository secret**.
Add four secrets:

| Secret | Value |
|---|---|
| `GROQ_API_KEY` | your Groq key |
| `SENDGRID_API_KEY` | your SendGrid key (Mail Send only) |
| `EMAIL_FROM` | the sender address you verified in SendGrid |
| `EMAIL_TO` | recipients, comma-separated |

Without the Groq secret the digest is built in offline mode. Without the SendGrid secrets the
digest and PDF are still saved, but the run is marked failed so you notice.

## Configuration

All settings live in `config.py`: sources, time window, article limits, number of top stories,
Groq model. To use a different Groq model, set `GROQ_MODEL` in `.env`, or as a repository
variable for GitHub Actions. If a model is retired, the code automatically tries the fallbacks
in `FALLBACK_MODELS`.

## Project structure

```
ai-news-digest/
├── run_digest.py          # main pipeline (steps 1-7)
├── show_db.py             # prints database statistics
├── config.py              # sources, limits, model settings
├── digest/
│   ├── collectors.py      # RSS, HTML scraping, Hacker News; filtering, dedupe
│   ├── http.py            # polite HTTP: robots.txt, User-Agent, delays
│   ├── fulltext.py        # scrapes article body text
│   ├── storage.py         # SQLite schema and queries
│   ├── llm.py             # Groq client, JSON replies, model fallback
│   ├── analysis.py        # rating, selection, summaries (+ offline fallback)
│   ├── pdf_report.py      # one-page PDF layout
│   ├── email_html.py      # HTML + plain-text newsletter
│   ├── mailer.py          # SendGrid API client
│   ├── models.py          # Article / Digest data classes
│   └── text.py            # text cleaning helpers
├── tests/                 # 84 tests (unit + integration)
├── data/news.db           # published database (committed by the daily run)
├── reports/               # published daily PDFs (local runs go to reports/local/)
└── .github/workflows/daily-digest.yml
```

## Database schema

```sql
articles(id, url_key UNIQUE, url, title, source, published_at, fetched_at,
         snippet, category, importance, summary, featured_on)
digests (digest_date PRIMARY KEY, created_at, article_count, source_count,
         top_story_count, mode, pdf_path)
```

## Planned improvements

- **Web dashboard** (Streamlit): search and filter every stored article by date, source and category.
- Weekly trend report: which companies and topics are rising, from the stored history.

These reuse the existing database, so each one is a new output rather than a rewrite.
