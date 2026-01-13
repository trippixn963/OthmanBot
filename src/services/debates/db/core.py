"""
OthmanBot - Database Core
===================================

Base database class with connection handling, schema, and migrations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.logger import logger


@dataclass
class UserKarma:
    """User karma data."""
    user_id: int
    total_karma: int
    upvotes_received: int
    downvotes_received: int


class DatabaseCore:
    """
    Base database class with connection handling and schema management.

    Uses a persistent connection with WAL mode for better concurrency.
    Thread-safe via a threading lock for all operations.
    """

    # Current schema version - increment when adding migrations
    SCHEMA_VERSION = 14

    # Valid table names for SQL injection prevention
    VALID_TABLES = frozenset({
        'votes', 'users', 'debate_threads', 'debate_bans',
        'debate_participation', 'debate_creators', 'case_logs',
        'analytics_messages', 'schema_version', 'user_streaks', 'linked_accounts',
        'appeals', 'debate_counter', 'audit_log', 'open_discussion', 'user_cache',
        'ban_history', 'closure_history'
    })

    def __init__(self, db_path: str = "data/othman.db") -> None:
        """Initialize database with persistent connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)

        # Thread lock for connection access
        self._lock = threading.Lock()

        # Create persistent connection
        self._connection: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_database()

    def _connect(self) -> None:
        """Create persistent connection with optimized settings."""
        self._connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
        )

        # Enable WAL mode for better concurrency
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA mmap_size=67108864")

        logger.tree("Database Connection Established", [
            ("Path", str(self.db_path)),
            ("Mode", "WAL"),
        ], emoji="🗄️")

    def _get_connection(self) -> sqlite3.Connection:
        """Get the persistent database connection."""
        if self._connection is None:
            self._connect()
        return self._connection

    def close(self) -> None:
        """Close the database connection and checkpoint WAL."""
        with self._lock:
            if self._connection:
                try:
                    self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._connection.close()
                    logger.tree("Database Connection Closed", [
                        ("WAL", "Checkpointed"),
                        ("Status", "Clean"),
                    ], emoji="🗄️")
                except sqlite3.Error as e:
                    logger.error("Database Checkpoint Failed", [("Error", str(e))])
                    try:
                        self._connection.close()
                    except sqlite3.Error:
                        pass
                finally:
                    self._connection = None

    def flush(self) -> None:
        """Flush pending writes to disk."""
        with self._lock:
            if self._connection:
                try:
                    self._connection.commit()
                    self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except sqlite3.Error as e:
                    logger.warning("Error Flushing Database", [("Error", str(e))])

    def health_check(self) -> bool:
        """Verify database connectivity."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()
                return True
            except sqlite3.Error:
                return False

    def _init_database(self) -> None:
        """Create database tables and run migrations."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Create schema version table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Get current version
            cursor.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cursor.fetchone()
            current_version = row[0] if row else 0

            if current_version == 0:
                cursor.execute("INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 0)")

            # Create base tables
            self._create_base_tables(cursor)

            # Run migrations
            migrations_run = self._run_migrations(cursor, current_version)

            conn.commit()

            if migrations_run > 0:
                logger.tree("Database Migrations Complete", [
                    ("From Version", str(current_version)),
                    ("To Version", str(self.SCHEMA_VERSION)),
                ], emoji="🗳️")

    def _create_base_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create all base tables (idempotent)."""
        # Users table - stores karma totals
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                total_karma INTEGER DEFAULT 0,
                upvotes_received INTEGER DEFAULT 0,
                downvotes_received INTEGER DEFAULT 0
            )
        """)

        # Votes table - tracks individual votes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voter_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                vote_type INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(voter_id, message_id)
            )
        """)

        # Debate threads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_threads (
                thread_id INTEGER PRIMARY KEY,
                analytics_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Debate bans table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                thread_id INTEGER,
                banned_by INTEGER NOT NULL,
                reason TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, thread_id)
            )
        """)

        # User cache for "(left)" tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_cache (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                display_name TEXT,
                is_member INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Debate participation tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_participation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(thread_id, user_id)
            )
        """)

        # Debate creators tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_creators (
                thread_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Case logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_logs (
                user_id INTEGER PRIMARY KEY,
                case_id INTEGER UNIQUE NOT NULL,
                thread_id INTEGER NOT NULL,
                ban_count INTEGER DEFAULT 1,
                last_unban_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # User streaks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_streaks (
                user_id INTEGER PRIMARY KEY,
                current_streak INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                last_active_date TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Ban history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ban_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                thread_id INTEGER,
                banned_by INTEGER NOT NULL,
                reason TEXT,
                duration_hours INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                removed_at TIMESTAMP,
                removed_by INTEGER,
                removal_reason TEXT
            )
        """)

        # Closure history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS closure_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                thread_name TEXT NOT NULL,
                closed_by INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reopened_at TIMESTAMP,
                reopened_by INTEGER
            )
        """)

        # Debate counter table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                counter INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_message ON votes(message_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_author ON votes(author_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_karma ON users(total_karma DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bans_user ON debate_bans(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bans_expires ON debate_bans(expires_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_participation_user ON debate_participation(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_creators_user ON debate_creators(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ban_history_user ON ban_history(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_closure_history_thread ON closure_history(thread_id)")

    def _run_migrations(self, cursor: sqlite3.Cursor, current_version: int) -> int:
        """Run all pending migrations."""
        migrations_run = 0

        # All migrations already applied via _create_base_tables
        # This handles incremental updates for existing databases

        if current_version < self.SCHEMA_VERSION:
            # Update schema version
            cursor.execute(
                "UPDATE schema_version SET version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (self.SCHEMA_VERSION,)
            )
            migrations_run = self.SCHEMA_VERSION - current_version

        return migrations_run

    def _column_exists(self, cursor: sqlite3.Cursor, table: str, column: str) -> bool:
        """Check if a column exists in a table."""
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        return column in columns
