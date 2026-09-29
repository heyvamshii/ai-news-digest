# Live demo script (Google Meet, about 5 minutes)

## Before the call (10 minutes earlier)

1. Open a terminal in the project folder and activate the environment:
   ```
   cd D:\AIThinkers\ai-news-digest
   .venv\Scripts\activate
   ```
2. Do one practice run so everything is warm: `python run_digest.py --demo`
3. Open these browser tabs: your GitHub repo's **Actions** tab, and its **reports/** folder.
4. Make the terminal text bigger (Ctrl + mouse wheel).
5. In Meet, choose **Present -> Your entire screen**, so you can switch windows freely.

Also run `git pull` before the call to download the latest daily PDFs and database from GitHub.

Backup plan: if the internet or Groq fails during the call, open this morning's PDF from
`reports\` (after `git pull`) or on GitHub. It was built automatically at 12:15 PM.

## During the call

**1. Explain in one sentence (30 s)**
> "Every morning it scrapes AI news from 14 sources, stores it in a database, uses an LLM
> to rank and summarise it, and emails me a newsletter plus a one-page PDF, automatically
> on GitHub Actions."

**2. Run it live (1 min)**
```
python run_digest.py --demo --email
```
Point at each step as it prints: fetching, database, AI rating, scraping full text, summaries,
PDF, email.

**2b. Show the email (1 min)**: open your inbox (it arrives within seconds). Show it on your
phone too if you like: the layout adapts. Click a headline to show the links work.

**3. Open the PDF (1 min)**
```
start reports\local\AI_Digest_2026-09-28.pdf
```
(use the file name printed at the end). Show "Today in AI", the top stories with importance
scores, the categories, and click a headline to show the links work.

**4. Show the database (30 s)**
```
python show_db.py --published
```
This shows the history the daily GitHub runs have built up. (`python show_db.py` without the
flag shows only your local runs.)
> "Everything is stored, so no story is ever repeated on a later day."

**5. Show the automation (1 min)**: GitHub -> **Actions** tab
- The list of daily runs (green ticks) proves it runs on its own at 12:15 PM IST.
- Click **Daily AI News Digest -> Run workflow** to start one live.
- Open the **reports/** folder to show one PDF per day.

**6. Next steps (30 s)**
> "Because everything is in the database, the next output is a web dashboard to search
> all past articles. It reuses the same data."

## Likely questions

| Question | Answer |
|---|---|
| Is scraping legal? | It reads public RSS feeds and APIs, checks `robots.txt` before scraping a page, identifies itself, and pauses between requests. No logins, no personal data. |
| Why RSS instead of scraping everything? | RSS is the site's official machine-readable feed. It's more reliable and polite. HTML scraping is used where there's no feed (Anthropic) and for full article text. |
| Why Groq? | It's free, very fast, and its API follows the OpenAI standard. About 5 calls a day keeps it inside the free tier. |
| How is the email sent? | SendGrid's Web API. Each recipient gets a private copy, scraped text is HTML-escaped, and if the email fails the PDF and database are still saved. |
| What if the LLM fails? | Keyword rules take over and the PDF is still created. The footer says which mode was used. |
| How do you avoid duplicates? | Normalised URL + title matching, and a UNIQUE key in the database. |
| How is it tested? | 84 automated tests with a fake network and fake LLM, 99% coverage (`pytest --cov=.`). |
