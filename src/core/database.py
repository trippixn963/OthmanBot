"""
OthmanBot - Unified Database
======================================

Central SQLite database manager for all bot data.

Consolidates:
- Debates, karma, bans, appeals (from debates.db)
- Daily stats, health tracking (from stats.db)
- AI cache (from JSON files)
- Posted URLs (from JSON files)

Single database file: data/othman.db

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, List, Tuple, Any

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

DATA_DIR: Path = Path(__file__).parent.parent.parent / "data"
DB_PATH: Path = DATA_DIR / "othman.db"

# Cache settings
AI_CACHE_EXPIRATION_DAYS: int = 30
AI_CACHE_MAX_ENTRIES: int = 5000
POSTED_URLS_MAX_PER_TYPE: int = 1000


# =============================================================================
# Database Manager (Singleton)
# =============================================================================

class DatabaseManager:
    """
    Centralized database manager with thread-safe operations.

    Uses WAL mode for better concurrency and persistent connection.
    """

    _instance: Optional["DatabaseManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "DatabaseManager":
        """Singleton pattern - only one instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize database connection and tables."""
        if self._initialized:
            return

        self._db_lock: threading.Lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._healthy: bool = False

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._connect()
        self._init_tables()
        self._healthy = True
        self._initialized = True

        logger.tree("Database Manager Initialized", [
            ("Path", str(DB_PATH)),
            ("WAL Mode", "Enabled"),
        ], emoji="🗄️")

    # =========================================================================
    # Health Check Methods
    # =========================================================================

    @property
    def is_healthy(self) -> bool:
        """Check if database connection is healthy."""
        if not self._healthy:
            return False
        try:
            with self._db_lock:
                if self._conn is None:
                    return False
                self._conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            self._healthy = False
            return False

    def require_healthy(self) -> None:
        """Raise RuntimeError if database is not healthy."""
        if not self.is_healthy:
            raise RuntimeError("Database is not healthy - connection lost or corrupted")

    def health_check(self) -> dict:
        """
        Perform comprehensive health check.

        Returns:
            Dict with health status and diagnostics
        """
        result = {
            "healthy": False,
            "connected": False,
            "wal_mode": False,
            "tables": 0,
            "db_size_mb": 0.0,
            "error": None,
        }

        try:
            # Check connection
            with self._db_lock:
                if self._conn is None:
                    result["error"] = "No connection"
                    return result

                # Test query
                self._conn.execute("SELECT 1")
                result["connected"] = True

                # Check WAL mode
                cursor = self._conn.execute("PRAGMA journal_mode")
                mode = cursor.fetchone()
                result["wal_mode"] = mode and mode[0].upper() == "WAL"

                # Count tables
                cursor = self._conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                )
                result["tables"] = cursor.fetchone()[0]

            # Get database file size
            if DB_PATH.exists():
                result["db_size_mb"] = round(DB_PATH.stat().st_size / (1024 * 1024), 2)

            result["healthy"] = result["connected"] and result["wal_mode"]
            self._healthy = result["healthy"]

        except sqlite3.Error as e:
            result["error"] = str(e)
            self._healthy = False

        return result

    def _connect(self) -> None:
        """Establish database connection with WAL mode."""
        try:
            self._conn = sqlite3.connect(
                str(DB_PATH),
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.row_factory = sqlite3.Row
            self._healthy = True
        except sqlite3.Error as e:
            self._healthy = False
            logger.error("Database Connection Failed", [("Error", str(e))])
            raise

    def _ensure_connection(self) -> sqlite3.Connection:
        """Ensure connection is valid, reconnect if needed."""
        if self._conn is None:
            self._connect()
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            self._connect()
        return self._conn

    def execute(
        self,
        query: str,
        params: Tuple = (),
        commit: bool = True
    ) -> sqlite3.Cursor:
        """Execute a query with thread safety."""
        with self._db_lock:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
            return cursor

    def executemany(
        self,
        query: str,
        params_list: List[Tuple],
        commit: bool = True
    ) -> sqlite3.Cursor:
        """Execute many queries with thread safety."""
        with self._db_lock:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            if commit:
                conn.commit()
            return cursor

    def fetchone(self, query: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        """Execute query and fetch one result."""
        cursor = self.execute(query, params, commit=False)
        return cursor.fetchone()

    def fetchall(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """Execute query and fetch all results."""
        cursor = self.execute(query, params, commit=False)
        return cursor.fetchall()

    def close(self) -> None:
        """Close database connection."""
        with self._db_lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                self._healthy = False
                logger.info("Database Connection Closed")

    # =========================================================================
    # Table Initialization
    # =========================================================================

    def _init_tables(self) -> None:
        """Initialize all database tables."""
        conn = self._ensure_connection()
        cursor = conn.cursor()

        # -----------------------------------------------------------------
        # AI Cache Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_type TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(cache_type, cache_key)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_cache_type_key
            ON ai_cache(cache_type, cache_key)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_cache_created
            ON ai_cache(created_at)
        """)

        # -----------------------------------------------------------------
        # Posted URLs Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posted_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_type TEXT NOT NULL,
                article_id TEXT NOT NULL,
                posted_at REAL NOT NULL,
                UNIQUE(content_type, article_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_posted_urls_type
            ON posted_urls(content_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_posted_urls_posted
            ON posted_urls(posted_at)
        """)

        # -----------------------------------------------------------------
        # Daily Activity Stats Table
        # -----------------------------------------------------------------
        cursor.execute("""
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_activity_date
            ON daily_activity(date)
        """)

        # -----------------------------------------------------------------
        # Bot Health Events Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_health_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL,
                reason TEXT,
                details TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_health_date
            ON bot_health_events(date)
        """)

        # -----------------------------------------------------------------
        # Downtime Periods Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS downtime_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disconnect_time TEXT NOT NULL,
                reconnect_time TEXT,
                downtime_minutes REAL,
                date TEXT NOT NULL,
                reason TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_downtime_date
            ON downtime_periods(date)
        """)

        # -----------------------------------------------------------------
        # Top Debaters Table
        # -----------------------------------------------------------------
        cursor.execute("""
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_debaters_date
            ON top_debaters(date)
        """)

        # -----------------------------------------------------------------
        # Debate Stats Table
        # -----------------------------------------------------------------
        cursor.execute("""
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_debate_stats_date
            ON debate_stats(date)
        """)

        # -----------------------------------------------------------------
        # Command Usage Table
        # -----------------------------------------------------------------
        cursor.execute("""
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_state (
                scheduler_name TEXT PRIMARY KEY,
                is_running INTEGER NOT NULL DEFAULT 0,
                extra_data TEXT,
                updated_at REAL NOT NULL
            )
        """)

        conn.commit()

    # =========================================================================
    # AI Cache Operations
    # =========================================================================

    def get_ai_cache(self, cache_type: str, cache_key: str) -> Optional[str]:
        """Get cached AI response if not expired."""
        expiry_time = time.time() - (AI_CACHE_EXPIRATION_DAYS * 86400)
        row = self.fetchone(
            """SELECT value FROM ai_cache
               WHERE cache_type = ? AND cache_key = ? AND created_at > ?""",
            (cache_type, cache_key, expiry_time)
        )
        return row["value"] if row else None

    def set_ai_cache(self, cache_type: str, cache_key: str, value: str) -> None:
        """Set AI cache value with timestamp."""
        self.execute(
            """INSERT OR REPLACE INTO ai_cache (cache_type, cache_key, value, created_at)
               VALUES (?, ?, ?, ?)""",
            (cache_type, cache_key, value, time.time())
        )

    def cleanup_ai_cache(self) -> int:
        """Remove expired and excess cache entries."""
        expiry_time = time.time() - (AI_CACHE_EXPIRATION_DAYS * 86400)

        # Remove expired entries
        cursor = self.execute(
            "DELETE FROM ai_cache WHERE created_at < ?",
            (expiry_time,)
        )
        expired_count = cursor.rowcount

        # Check if over limit and remove oldest
        row = self.fetchone("SELECT COUNT(*) as cnt FROM ai_cache")
        total = row["cnt"] if row else 0

        removed_oldest = 0
        if total > AI_CACHE_MAX_ENTRIES:
            to_remove = total - int(AI_CACHE_MAX_ENTRIES * 0.8)
            self.execute(
                """DELETE FROM ai_cache WHERE id IN (
                    SELECT id FROM ai_cache ORDER BY created_at ASC LIMIT ?
                )""",
                (to_remove,)
            )
            removed_oldest = to_remove

        total_removed = expired_count + removed_oldest
        if total_removed > 0:
            logger.info("Cleaned AI Cache", [
                ("Expired", str(expired_count)),
                ("Oldest", str(removed_oldest)),
                ("Remaining", str(total - total_removed)),
            ])
        return total_removed

    # =========================================================================
    # Posted URLs Operations
    # =========================================================================

    def is_url_posted(self, content_type: str, article_id: str) -> bool:
        """Check if URL has been posted."""
        row = self.fetchone(
            """SELECT 1 FROM posted_urls
               WHERE content_type = ? AND article_id = ?""",
            (content_type, article_id)
        )
        return row is not None

    def mark_url_posted(self, content_type: str, article_id: str) -> None:
        """Mark URL as posted."""
        self.execute(
            """INSERT OR IGNORE INTO posted_urls (content_type, article_id, posted_at)
               VALUES (?, ?, ?)""",
            (content_type, article_id, time.time())
        )

    def cleanup_posted_urls(self, content_type: str) -> int:
        """Keep only the most recent URLs per content type."""
        row = self.fetchone(
            "SELECT COUNT(*) as cnt FROM posted_urls WHERE content_type = ?",
            (content_type,)
        )
        total = row["cnt"] if row else 0

        if total <= POSTED_URLS_MAX_PER_TYPE:
            return 0

        to_remove = total - POSTED_URLS_MAX_PER_TYPE
        cursor = self.execute(
            """DELETE FROM posted_urls WHERE content_type = ? AND id IN (
                SELECT id FROM posted_urls WHERE content_type = ?
                ORDER BY posted_at ASC LIMIT ?
            )""",
            (content_type, content_type, to_remove)
        )
        return cursor.rowcount

    def get_posted_urls_set(self, content_type: str) -> set:
        """Get all posted article IDs as a set for O(1) lookup."""
        rows = self.fetchall(
            "SELECT article_id FROM posted_urls WHERE content_type = ?",
            (content_type,)
        )
        return {row["article_id"] for row in rows}

    # =========================================================================
    # Scheduler State Operations
    # =========================================================================

    def get_scheduler_state(self, scheduler_name: str) -> Optional[dict]:
        """
        Get scheduler state from database.

        Args:
            scheduler_name: Unique identifier for the scheduler

        Returns:
            Dict with is_running and extra_data, or None if not found
        """
        row = self.fetchone(
            "SELECT is_running, extra_data FROM scheduler_state WHERE scheduler_name = ?",
            (scheduler_name,)
        )
        if not row:
            return None

        import json
        extra_data = None
        if row["extra_data"]:
            try:
                extra_data = json.loads(row["extra_data"])
            except json.JSONDecodeError:
                extra_data = None

        return {
            "is_running": bool(row["is_running"]),
            "extra_data": extra_data
        }

    def set_scheduler_state(
        self,
        scheduler_name: str,
        is_running: bool,
        extra_data: Optional[dict] = None
    ) -> None:
        """
        Save scheduler state to database.

        Args:
            scheduler_name: Unique identifier for the scheduler
            is_running: Whether the scheduler is running
            extra_data: Additional state data (stored as JSON)
        """
        import json
        extra_json = json.dumps(extra_data) if extra_data else None

        self.execute(
            """INSERT OR REPLACE INTO scheduler_state
               (scheduler_name, is_running, extra_data, updated_at)
               VALUES (?, ?, ?, ?)""",
            (scheduler_name, int(is_running), extra_json, time.time())
        )


# =============================================================================
# Global Instance
# =============================================================================

def get_db() -> DatabaseManager:
    """Get the global database manager instance."""
    return DatabaseManager()


__all__ = ["DatabaseManager", "get_db", "DB_PATH", "DATA_DIR"]
