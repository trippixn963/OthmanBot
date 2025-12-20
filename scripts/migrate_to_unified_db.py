#!/usr/bin/env python3
"""
Database Migration Script
=========================

Migrates existing data to the unified othman.db:
1. stats.db -> othman.db (daily_activity, bot_health, etc.)
2. news_ai_cache.json -> othman.db ai_cache table
3. soccer_ai_cache.json -> othman.db ai_cache table
4. posted_urls.json -> othman.db posted_urls table
5. posted_soccer_urls.json -> othman.db posted_urls table

Run with: python scripts/migrate_to_unified_db.py
"""

import json
import sqlite3
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OTHMAN_DB = DATA_DIR / "othman.db"
STATS_DB = DATA_DIR / "stats.db"
DEBATES_DB = DATA_DIR / "debates.db"


def migrate_stats_db():
    """Migrate stats.db tables to othman.db."""
    if not STATS_DB.exists():
        print("  [SKIP] stats.db not found")
        return

    print("  [INFO] Migrating stats.db...")
    src = sqlite3.connect(str(STATS_DB))
    dst = sqlite3.connect(str(OTHMAN_DB))
    src.row_factory = sqlite3.Row

    # Tables to migrate
    tables = [
        "daily_activity",
        "bot_health_events",
        "downtime_periods",
        "top_debaters",
        "debate_stats",
        "command_usage",
    ]

    for table in tables:
        try:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"    {table}: 0 rows (empty)")
                continue

            # Get column names
            columns = [desc[0] for desc in src.execute(f"SELECT * FROM {table} LIMIT 1").description]

            # Filter out 'id' column for autoincrement tables
            insert_columns = [c for c in columns if c != "id"]
            placeholders = ",".join(["?" for _ in insert_columns])
            col_str = ",".join(insert_columns)

            count = 0
            for row in rows:
                values = tuple(row[c] for c in insert_columns)
                try:
                    dst.execute(
                        f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})",
                        values
                    )
                    count += 1
                except sqlite3.Error:
                    pass  # Skip duplicates

            dst.commit()
            print(f"    {table}: {count} rows migrated")

        except sqlite3.Error as e:
            print(f"    {table}: ERROR - {e}")

    src.close()
    dst.close()


def migrate_ai_cache(filename: str, cache_type: str):
    """Migrate AI cache JSON to SQLite."""
    json_path = DATA_DIR / filename
    if not json_path.exists():
        print(f"  [SKIP] {filename} not found")
        return

    print(f"  [INFO] Migrating {filename}...")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"    ERROR reading {filename}: {e}")
        return

    if not cache_data:
        print(f"    {filename}: 0 entries (empty)")
        return

    dst = sqlite3.connect(str(OTHMAN_DB))
    count = 0

    for key, entry in cache_data.items():
        try:
            # Handle both old format (string) and new format (dict with timestamp)
            if isinstance(entry, dict):
                value = entry.get("value", "")
                timestamp = entry.get("timestamp", time.time())
            else:
                value = entry
                timestamp = time.time()

            if value:
                dst.execute(
                    """INSERT OR IGNORE INTO ai_cache (cache_type, cache_key, value, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (cache_type, key, value, timestamp)
                )
                count += 1
        except sqlite3.Error:
            pass  # Skip errors

    dst.commit()
    dst.close()
    print(f"    {filename}: {count} entries migrated")


def migrate_posted_urls(filename: str, content_type: str):
    """Migrate posted URLs JSON to SQLite."""
    json_path = DATA_DIR / filename
    if not json_path.exists():
        print(f"  [SKIP] {filename} not found")
        return

    print(f"  [INFO] Migrating {filename}...")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            urls = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"    ERROR reading {filename}: {e}")
        return

    if not urls:
        print(f"    {filename}: 0 URLs (empty)")
        return

    # Handle both list and set-like formats
    if isinstance(urls, dict):
        url_list = list(urls.keys())
    elif isinstance(urls, list):
        url_list = urls
    else:
        url_list = list(urls)

    dst = sqlite3.connect(str(OTHMAN_DB))
    count = 0
    now = time.time()

    for url in url_list:
        try:
            dst.execute(
                """INSERT OR IGNORE INTO posted_urls (content_type, article_id, posted_at)
                   VALUES (?, ?, ?)""",
                (content_type, url, now)
            )
            count += 1
        except sqlite3.Error:
            pass

    dst.commit()
    dst.close()
    print(f"    {filename}: {count} URLs migrated")


def copy_debates_db():
    """Copy debates.db to othman.db (keeping all debate tables)."""
    if not DEBATES_DB.exists():
        print("  [SKIP] debates.db not found")
        return

    print("  [INFO] Copying debates.db structure...")

    # List all tables from debates.db
    src = sqlite3.connect(str(DEBATES_DB))
    tables = src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()

    # The debates tables will stay in debates.db (renamed to othman.db)
    # We just need to add the new tables on top
    print(f"    debates.db has {len(tables)} tables")
    src.close()


def main():
    print("=" * 60)
    print("OthmanBot Database Migration")
    print("=" * 60)
    print()

    # Ensure othman.db exists with tables (import will create it)
    print("[1/5] Initializing unified database...")
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.core.database import get_db
    db = get_db()
    print("    othman.db initialized with new tables")
    print()

    # Migrate stats.db
    print("[2/5] Migrating stats database...")
    migrate_stats_db()
    print()

    # Migrate AI caches
    print("[3/5] Migrating AI cache files...")
    migrate_ai_cache("news_ai_cache.json", "news")
    migrate_ai_cache("soccer_ai_cache.json", "soccer")
    print()

    # Migrate posted URLs
    print("[4/5] Migrating posted URLs...")
    migrate_posted_urls("posted_urls.json", "news")
    migrate_posted_urls("posted_soccer_urls.json", "soccer")
    print()

    # Summary
    print("[5/5] Migration complete!")
    print()

    # Show final stats
    conn = sqlite3.connect(str(OTHMAN_DB))
    tables = [
        ("ai_cache", "AI cache entries"),
        ("posted_urls", "Posted URLs"),
        ("daily_activity", "Daily activity records"),
        ("bot_health_events", "Health events"),
        ("top_debaters", "Top debater records"),
    ]

    print("Final database stats:")
    for table, desc in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  - {desc}: {count}")
        except sqlite3.Error:
            print(f"  - {desc}: ERROR")

    conn.close()
    print()
    print("=" * 60)
    print("NEXT STEPS:")
    print("1. Update code to use unified database")
    print("2. Test bot locally")
    print("3. Deploy to VPS and run migration there")
    print("4. Remove old files: stats.db, *_ai_cache.json, posted_*_urls.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
