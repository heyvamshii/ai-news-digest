"""Print what is stored in the database (handy during the demo).

    python show_db.py              your local runs (data/local.db)
    python show_db.py --published  the daily GitHub Actions history (data/news.db, after git pull)
"""

import argparse
import sys

import config
from digest import storage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show database statistics.")
    parser.add_argument("--published", action="store_true", help="show the database built by GitHub Actions")
    args = parser.parse_args(argv)
    db_path = config.PUBLISHED_DB_PATH if args.published else config.DB_PATH

    if not db_path.exists():
        hint = "git pull" if args.published else "python run_digest.py"
        print(f"No database at {db_path.name} yet. Run: {hint}")
        return 1
    with storage.connect(db_path) as conn:
        s = storage.stats(conn)

    print(f"\nAI NEWS DIGEST - DATABASE ({db_path.name})")
    print("=" * 44)
    print(f"Articles stored     : {s['articles']}")
    print(f"Sources             : {s['sources']}")
    print(f"Summarised stories  : {s['summarised']}")
    print(f"Digests created     : {s['digests']}")
    print(f"Collecting since    : {(s['first_fetch'] or '-')[:10]}")

    print("\nArticles per source")
    for row in s["by_source"]:
        print(f"  {row['source']:<18} {row['n']:>4}  {'#' * min(row['n'], 30)}")

    print("\nArticles per category")
    for row in s["by_category"]:
        print(f"  {row['category']:<18} {row['n']:>4}")

    print("\nRecent digests")
    for row in s["recent_digests"]:
        print(f"  {row['digest_date']}  {row['article_count']:>3} articles  "
              f"{row['source_count']:>2} sources  {row['mode']}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
