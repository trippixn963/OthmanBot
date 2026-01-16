"""
OthmanBot - Database Core
=========================

Base database class with connection management and table initialization.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

DATA_DIR: Path = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH: Path = DATA_DIR / "othman.db"

# Cache settings
AI_CACHE_EXPIRATION_DAYS: int = 30
AI_CACHE_MAX_ENTRIES: int = 5000
POSTED_URLS_MAX_PER_TYPE: int = 1000

# Dead letter queue settings
DEAD_LETTER_MAX_FAILURES: int = 3
DEAD_LETTER_QUARANTINE_HOURS: int = 24

# Content similarity settings
CONTENT_HASH_RETENTION_DAYS: int = 7
CONTENT_HASH_MAX_ENTRIES: int = 500


# =============================================================================
# Exceptions
# =============================================================================

class DatabaseUnavailableError(Exception):
    """Raised when the database is unhealthy and operations cannot proceed."""
    pass


# =============================================================================
# Database Core
# =============================================================================

class DatabaseCore:
    """Base database class with connection management."""

    def __init__(self) -> None:
        """Initialize database connection and create tables if needed."""
        self.db_path = str(DB_PATH)
        self._healthy = True
        self._corruption_reason: Optional[str] = None

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # =========================================================================
    # Health Check
    # =========================================================================

    @property
    def is_healthy(self) -> bool:
        """Check if database is healthy and operational."""
        return self._healthy

    @property
    def corruption_reason(self) -> Optional[str]:
        """Get the reason for database corruption if unhealthy."""
        return self._corruption_reason

    def require_healthy(self) -> None:
        """Raise RuntimeError if database is unhealthy."""
        if not self._healthy:
            raise RuntimeError(
                f"Database is unhealthy: {self._corruption_reason or 'Unknown error'}. "
                "Manual intervention required."
            )

    def health_check(self) -> dict:
        """Perform comprehensive health check."""
        result = {
            "healthy": False,
            "connected": False,
            "wal_mode": False,
            "tables": 0,
            "db_size_mb": 0.0,
            "error": None,
        }

        try:
            with self._get_conn() as conn:
                if conn is None:
                    result["error"] = "No connection"
                    return result

                cur = conn.cursor()

                # Test query
                cur.execute("SELECT 1")
                result["connected"] = True

                # Check WAL mode
                cur.execute("PRAGMA journal_mode")
                mode = cur.fetchone()
                result["wal_mode"] = mode and mode[0].upper() == "WAL"

                # Count tables
                cur.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                )
                result["tables"] = cur.fetchone()[0]

            # Get database file size
            if os.path.exists(self.db_path):
                result["db_size_mb"] = round(
                    os.path.getsize(self.db_path) / (1024 * 1024), 2
                )

            result["healthy"] = result["connected"] and result["wal_mode"]
            self._healthy = result["healthy"]

        except sqlite3.Error as e:
            result["error"] = str(e)
            self._healthy = False

        return result

    # =========================================================================
    # Connection Management
    # =========================================================================

    def _check_integrity(self) -> bool:
        """Check database integrity. Returns True if healthy."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check")
            result = cur.fetchone()
            conn.close()
            return result[0] == "ok"
        except Exception as e:
            logger.tree("DB Integrity Check Failed", [
                ("Error", str(e)[:100]),
            ], emoji="❌")
            return False

    def _backup_corrupted(self) -> None:
        """Backup corrupted database file."""
        import shutil
        backup_path = f"{self.db_path}.corrupted.{int(time.time())}"
        try:
            shutil.copy2(self.db_path, backup_path)
            logger.tree("Corrupted DB Backed Up", [
                ("Backup", backup_path),
            ], emoji="💾")
        except Exception as e:
            logger.tree("DB Backup Failed", [
                ("Error", str(e)[:100]),
            ], emoji="❌")

    @contextmanager
    def _get_conn(self):
        """Get database connection context manager."""
        if not self._healthy:
            logger.tree("Database Unhealthy", [
                ("Status", "Operation rejected"),
                ("Reason", self._corruption_reason or "Unknown"),
            ], emoji="⚠️")
            raise DatabaseUnavailableError(
                f"Database is unavailable: {self._corruption_reason or 'unhealthy'}"
            )

        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        except sqlite3.DatabaseError as e:
            error_msg = str(e).lower()
            is_corruption = any(x in error_msg for x in [
                "disk i/o error",
                "database disk image is malformed",
                "file is not a database",
                "file is encrypted",
                "unable to open database",
            ])
            if is_corruption:
                self._healthy = False
                self._corruption_reason = str(e)
                logger.tree("Database Corruption Detected", [
                    ("Error", str(e)[:100]),
                ], emoji="🚨")
                self._backup_corrupted()
            else:
                logger.tree("Database Error", [
                    ("Type", type(e).__name__),
                    ("Message", str(e)[:100]),
                ], emoji="⚠️")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # =========================================================================
    # Table Initialization
    # =========================================================================

    def _init_db(self) -> None:
        """Initialize all database tables."""
        logger.tree("Database Init", [
            ("Path", self.db_path),
            ("Status", "Starting"),
        ], emoji="🗄️")

        # Check integrity on startup
        if os.path.exists(self.db_path) and not self._check_integrity():
            self._corruption_reason = "PRAGMA integrity_check failed on startup"
            logger.tree("DATABASE CORRUPTION DETECTED", [
                ("Path", self.db_path),
                ("Action", "Creating backup"),
            ], emoji="🚨")
            self._backup_corrupted()
            self._healthy = False
            return

        with self._get_conn() as conn:
            if conn is None:
                logger.tree("Database Init Failed", [
                    ("Reason", "Could not establish connection"),
                ], emoji="❌")
                return

            cur = conn.cursor()

            # -----------------------------------------------------------------
            # AI Cache Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ai_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_type TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(cache_type, cache_key)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_ai_cache_type_key
                ON ai_cache(cache_type, cache_key)
            """)

            # -----------------------------------------------------------------
            # Posted URLs Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS posted_urls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    posted_at REAL NOT NULL,
                    UNIQUE(content_type, article_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_posted_urls_type
                ON posted_urls(content_type)
            """)

            # -----------------------------------------------------------------
            # Daily Activity Stats Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    debates_created INTEGER DEFAULT 0,
                    debates_deleted INTEGER DEFAULT 0,
                    messages_in_debates INTEGER DEFAULT 0,
                    upvotes_given INTEGER DEFAULT 0,
                    downvotes_given INTEGER DEFAULT 0,
                    net_karma INTEGER DEFAULT 0,
                    news_posted INTEGER DEFAULT 0,
                    soccer_posted INTEGER DEFAULT 0,
                    commands_used INTEGER DEFAULT 0,
                    users_banned INTEGER DEFAULT 0,
                    users_unbanned INTEGER DEFAULT 0,
                    auto_unbans INTEGER DEFAULT 0,
                    hot_debates INTEGER DEFAULT 0,
                    unique_participants INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -----------------------------------------------------------------
            # Bot Health Events Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_health_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    reason TEXT,
                    details TEXT
                )
            """)

            # -----------------------------------------------------------------
            # Downtime Periods Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS downtime_periods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    disconnect_time TEXT NOT NULL,
                    reconnect_time TEXT,
                    downtime_minutes REAL,
                    date TEXT NOT NULL,
                    reason TEXT
                )
            """)

            # -----------------------------------------------------------------
            # Top Debaters Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS top_debaters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    messages INTEGER DEFAULT 0,
                    karma_received INTEGER DEFAULT 0,
                    debates_started INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, user_id)
                )
            """)

            # -----------------------------------------------------------------
            # Debate Stats Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS debate_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    thread_id INTEGER NOT NULL,
                    thread_name TEXT,
                    creator_id INTEGER,
                    creator_name TEXT,
                    messages INTEGER DEFAULT 0,
                    participants INTEGER DEFAULT 0,
                    upvotes INTEGER DEFAULT 0,
                    downvotes INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, thread_id)
                )
            """)

            # -----------------------------------------------------------------
            # Command Usage Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS command_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    command_name TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    UNIQUE(date, command_name)
                )
            """)

            # -----------------------------------------------------------------
            # Scheduler State Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scheduler_state (
                    scheduler_name TEXT PRIMARY KEY,
                    is_running INTEGER NOT NULL DEFAULT 0,
                    extra_data TEXT,
                    updated_at REAL NOT NULL
                )
            """)

            # -----------------------------------------------------------------
            # Scraper Metrics Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scraper_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    recorded_at REAL NOT NULL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_scraper_metrics_type_name
                ON scraper_metrics(content_type, metric_name)
            """)

            # -----------------------------------------------------------------
            # Dead Letter Queue Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dead_letter_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    article_url TEXT NOT NULL,
                    failure_count INTEGER DEFAULT 1,
                    last_error TEXT,
                    first_failure_at REAL NOT NULL,
                    last_failure_at REAL NOT NULL,
                    quarantined_until REAL,
                    UNIQUE(content_type, article_id)
                )
            """)

            # -----------------------------------------------------------------
            # Content Hashes Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS content_hashes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(content_type, article_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_content_hashes_type
                ON content_hashes(content_type)
            """)

            # -----------------------------------------------------------------
            # Article Engagement Table
            # -----------------------------------------------------------------
            cur.execute("""
                CREATE TABLE IF NOT EXISTS article_engagement (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    thread_id INTEGER NOT NULL,
                    thread_url TEXT,
                    title TEXT,
                    upvotes INTEGER DEFAULT 0,
                    downvotes INTEGER DEFAULT 0,
                    replies INTEGER DEFAULT 0,
                    posted_at REAL NOT NULL,
                    last_checked_at REAL,
                    UNIQUE(content_type, article_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_article_engagement_type
                ON article_engagement(content_type)
            """)

            logger.tree("Database Initialized", [
                ("Tables", "All created/verified"),
                ("Status", "Ready"),
            ], emoji="✅")
