"""
Othman Discord Bot - Debates Database
======================================

SQLite database operations for karma tracking and debate statistics.

Features:
- Vote tracking with karma calculations
- Debate participation statistics
- Ban/unban management with expiry
- Thread closure history
- WAL mode for concurrent access

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from src.core.logger import logger


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class UserKarma:
    """User karma data."""
    user_id: int
    total_karma: int
    upvotes_received: int
    downvotes_received: int


# =============================================================================
# Database Class
# =============================================================================

class DebatesDatabase:
    """
    SQLite database for debate karma tracking.

    Uses a persistent connection with WAL mode for better concurrency.
    Thread-safe via a threading lock for all operations.
    """

    def __init__(self, db_path: str = "data/othman.db") -> None:
        """
        Initialize database with persistent connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)

        # Thread lock for connection access
        self._lock = threading.Lock()

        # Create persistent connection with optimized settings
        self._connection: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_database()

    def _connect(self) -> None:
        """Create persistent connection with optimized settings."""
        self._connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,  # Allow multi-thread access (protected by lock)
            timeout=30.0,  # Wait up to 30s for locks
        )

        # Enable WAL mode for better concurrency (readers don't block writers)
        self._connection.execute("PRAGMA journal_mode=WAL")
        # Enable foreign keys
        self._connection.execute("PRAGMA foreign_keys=ON")
        # Synchronous NORMAL is safe with WAL and faster than FULL
        self._connection.execute("PRAGMA synchronous=NORMAL")
        # Use memory-mapped I/O for better read performance (64MB)
        self._connection.execute("PRAGMA mmap_size=67108864")

        logger.tree("Database Connection Established", [
            ("Path", str(self.db_path)),
            ("Mode", "WAL"),
            ("Timeout", "30s"),
            ("MMAP", "64MB"),
        ], emoji="🗄️")

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get the persistent database connection.

        If connection is closed, reconnect automatically.

        Returns:
            Active database connection
        """
        if self._connection is None:
            self._connect()
        return self._connection

    def close(self) -> None:
        """
        Close the database connection and ensure all data is persisted.

        Should be called during graceful shutdown.
        Raises sqlite3.Error if checkpoint fails (data may be at risk).
        """
        with self._lock:
            if self._connection:
                checkpoint_success = False
                try:
                    # Checkpoint WAL before closing to ensure all data is persisted
                    self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    checkpoint_success = True
                    self._connection.close()
                    logger.tree("Database Connection Closed", [
                        ("WAL", "Checkpointed"),
                        ("Status", "Clean"),
                    ], emoji="🗄️")
                except sqlite3.Error as e:
                    logger.error("CRITICAL: Database Checkpoint Failed", [
                        ("Error", str(e)),
                        ("Risk", "Recent data may not be persisted"),
                    ])
                    # Still try to close connection to prevent corruption
                    try:
                        self._connection.close()
                    except sqlite3.Error:
                        pass
                    if not checkpoint_success:
                        raise  # Re-raise so caller knows data may be at risk
                finally:
                    self._connection = None

    def flush(self) -> None:
        """
        Flush pending writes to disk without closing connection.

        Commits any pending transactions and checkpoints WAL.
        Use for graceful shutdown preparation or before backup.
        """
        with self._lock:
            if self._connection:
                try:
                    self._connection.commit()
                    self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    logger.info("Database Flushed", [
                        ("Status", "OK"),
                    ])
                except sqlite3.Error as e:
                    logger.warning("Error Flushing Database", [
                        ("Error", str(e)),
                    ])

    def health_check(self) -> bool:
        """
        Verify database connectivity with a simple query.

        Returns:
            True if database is accessible, False otherwise
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()
                return True
            except sqlite3.Error:
                return False

    # Current schema version - increment when adding migrations
    SCHEMA_VERSION = 13

    # Valid table names for SQL injection prevention
    VALID_TABLES = frozenset({
        'votes', 'users', 'debate_threads', 'debate_bans',
        'debate_participation', 'debate_creators', 'case_logs',
        'analytics_messages', 'schema_version', 'user_streaks', 'linked_accounts',
        'appeals',
        'debate_counter', 'audit_log'
    })

    # Audit action types for consistency
    AUDIT_ACTIONS = frozenset({
        'ban_add', 'ban_remove', 'ban_expire',
        'vote_add', 'vote_remove', 'vote_change',
        'karma_adjust', 'karma_reset',
        'debate_create', 'debate_deprecate',
        'account_link', 'account_unlink',
        'case_create', 'case_update',
        'counter_set', 'counter_reset',
    })

    def _init_database(self) -> None:
        """Create database tables and run migrations."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Create schema version table first
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
                # Insert initial version record
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
                    ("Migrations Run", str(migrations_run)),
                ], emoji="🗳️")
            else:
                logger.tree("Debates Database Initialized", [
                    ("Schema Version", str(self.SCHEMA_VERSION)),
                    ("Tables", "9 created/verified"),
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

        # Debate threads table - tracks debate threads and their analytics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_threads (
                thread_id INTEGER PRIMARY KEY,
                analytics_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Debate bans table - users banned from specific threads or all debates
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

        # Leaderboard thread tracking (single row)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard_thread (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                thread_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Monthly leaderboard embeds
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard_embeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(year, month)
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

        # Case logs table - tracks user moderation cases
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

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_message ON votes(message_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_author ON votes(author_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_karma ON users(total_karma DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bans_user ON debate_bans(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_participation_user ON debate_participation(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_creators_user ON debate_creators(user_id)")

    def _run_migrations(self, cursor: sqlite3.Cursor, current_version: int) -> int:
        """
        Run all pending migrations.

        Args:
            cursor: Database cursor
            current_version: Current schema version

        Returns:
            Number of migrations run
        """
        migrations_run = 0

        # Migration 1: Add expires_at to debate_bans
        if current_version < 1:
            if not self._column_exists(cursor, "debate_bans", "expires_at"):
                cursor.execute("ALTER TABLE debate_bans ADD COLUMN expires_at TIMESTAMP")
                logger.info("Migration 1: Added expires_at to debate_bans")
            migrations_run += 1

        # Migration 2: Add ban_count and last_unban_at to case_logs
        if current_version < 2:
            if not self._column_exists(cursor, "case_logs", "ban_count"):
                cursor.execute("ALTER TABLE case_logs ADD COLUMN ban_count INTEGER DEFAULT 1")
                logger.info("Migration 2: Added ban_count to case_logs")
            if not self._column_exists(cursor, "case_logs", "last_unban_at"):
                cursor.execute("ALTER TABLE case_logs ADD COLUMN last_unban_at TIMESTAMP")
                logger.info("Migration 2: Added last_unban_at to case_logs")
            migrations_run += 1

        # Migration 3: Add index on debate_bans expires_at for auto-unban queries
        if current_version < 3:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bans_expires ON debate_bans(expires_at)")
            logger.info("Migration 3: Added index on debate_bans.expires_at")
            migrations_run += 1

        # Migration 4: Add user_streaks table for tracking daily participation streaks
        if current_version < 4:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_streaks (
                    user_id INTEGER PRIMARY KEY,
                    current_streak INTEGER DEFAULT 0,
                    longest_streak INTEGER DEFAULT 0,
                    last_active_date TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Migration 4: Added user_streaks table")
            migrations_run += 1

        # Migration 5: Add linked_accounts table for alt account tracking
        if current_version < 5:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS linked_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    main_user_id INTEGER NOT NULL,
                    alt_user_id INTEGER NOT NULL UNIQUE,
                    linked_by INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_linked_main ON linked_accounts(main_user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_linked_alt ON linked_accounts(alt_user_id)")
            logger.info("Migration 5: Added linked_accounts table")
            migrations_run += 1

        # Migration 6: Add debate_counter table for atomic debate numbering
        if current_version < 6:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS debate_counter (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    counter INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migrate existing counter from JSON file if it exists
            try:
                import json
                counter_file = Path("data/debate_counter.json")
                if counter_file.exists():
                    with open(counter_file, "r") as f:
                        data = json.load(f)
                        # Check both "count" and "counter" keys for backwards compatibility
                        existing_count = data.get("count", data.get("counter", 0))
                    cursor.execute(
                        "INSERT OR REPLACE INTO debate_counter (id, counter) VALUES (1, ?)",
                        (existing_count,)
                    )
                    logger.info("Migration 6: Migrated debate counter from JSON", [
                        ("Count", str(existing_count)),
                    ])
                else:
                    cursor.execute("INSERT OR IGNORE INTO debate_counter (id, counter) VALUES (1, 0)")
            except Exception as e:
                cursor.execute("INSERT OR IGNORE INTO debate_counter (id, counter) VALUES (1, 0)")
                logger.warning("Migration 6: Could not migrate JSON counter", [
                    ("Error", str(e)),
                ])
            logger.info("Migration 6: Added debate_counter table")
            migrations_run += 1

        # Migration 7: Add audit_log table for accountability tracking
        if current_version < 7:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    actor_id INTEGER,
                    target_id INTEGER,
                    target_type TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Index for querying by actor (who did what)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id)")
            # Index for querying by target (what happened to whom)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_id, target_type)")
            # Index for querying by action type
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")
            # Index for time-based queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at)")
            logger.info("Migration 7: Added audit_log table")
            migrations_run += 1

        # Migration 8: Add performance indexes for frequently-queried columns
        if current_version < 8:
            # Index on votes.voter_id - for checking if user has voted, removing user's votes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_voter ON votes(voter_id)")
            # Index on votes.author_id - for calculating karma (SUM WHERE author_id = ?)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_author ON votes(author_id)")
            # Index on votes.message_id - for getting votes on specific message
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_message ON votes(message_id)")
            # Index on debate_participation.user_id - for user analytics queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_participation_user ON debate_participation(user_id)")
            # Index on debate_bans.user_id - for checking if user is banned
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bans_user ON debate_bans(user_id)")
            # Index on debate_bans.expires_at - for finding expired bans
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bans_expiry ON debate_bans(expires_at)")
            # Index on debate_creators.user_id - for counting debates created by user
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_creators_user ON debate_creators(user_id)")
            # Index on user_streaks.user_id - for streak lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_streaks_user ON user_streaks(user_id)")
            logger.info("Migration 8: Added performance indexes")
            migrations_run += 1

        # Migration 9: Add appeals table for disallow/close appeals
        if current_version < 9:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS appeals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    action_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    additional_context TEXT,
                    status TEXT DEFAULT 'pending',
                    reviewed_by INTEGER,
                    reviewed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, action_type, action_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_appeals_user ON appeals(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals(status)")
            logger.info("Migration 9: Added appeals table")
            migrations_run += 1

        # Migration 10: Add ban_history table for tracking all bans (even after removal)
        if current_version < 10:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ban_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    banned_by INTEGER NOT NULL,
                    reason TEXT,
                    duration TEXT,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    removed_at TIMESTAMP,
                    removed_by INTEGER,
                    removal_reason TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ban_history_user ON ban_history(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ban_history_time ON ban_history(created_at)")
            logger.info("Migration 10: Added ban_history table")
            migrations_run += 1

        # Migration 11: Add closure_history table for tracking thread closures
        if current_version < 11:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS closure_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    thread_name TEXT,
                    closed_by INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reopened_at TIMESTAMP,
                    reopened_by INTEGER
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_closure_history_user ON closure_history(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_closure_history_time ON closure_history(created_at)")
            logger.info("Migration 11: Added closure_history table")
            migrations_run += 1

        # Migration 12: Add denial_reason to appeals table
        if current_version < 12:
            if not self._column_exists(cursor, "appeals", "denial_reason"):
                cursor.execute("ALTER TABLE appeals ADD COLUMN denial_reason TEXT")
                logger.info("Migration 12: Added denial_reason to appeals")
            migrations_run += 1

        # Migration 13: Add case_message_id to appeals table (for editing the embed)
        if current_version < 13:
            if not self._column_exists(cursor, "appeals", "case_message_id"):
                cursor.execute("ALTER TABLE appeals ADD COLUMN case_message_id INTEGER")
                logger.info("Migration 13: Added case_message_id to appeals")
            migrations_run += 1

        # Update schema version
        if migrations_run > 0:
            cursor.execute(
                "UPDATE schema_version SET version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (self.SCHEMA_VERSION,)
            )

        return migrations_run

    def _column_exists(self, cursor: sqlite3.Cursor, table: str, column: str) -> bool:
        """Check if a column exists in a table."""
        # Validate table name to prevent SQL injection
        if table not in self.VALID_TABLES:
            raise ValueError(f"Invalid table name: {table}")
        # Additional validation: ensure table name is a valid identifier
        if not table.isidentifier():
            raise ValueError(f"Invalid table name format: {table}")
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in cursor.fetchall()]
        return column in columns

    # -------------------------------------------------------------------------
    # Vote Operations
    # -------------------------------------------------------------------------

    def add_vote(
        self,
        voter_id: int,
        message_id: int,
        author_id: int,
        vote_type: int
    ) -> bool:
        """
        Add or update a vote.

        Args:
            voter_id: ID of user voting
            message_id: ID of message being voted on
            author_id: ID of message author (receives karma)
            vote_type: +1 for upvote, -1 for downvote

        Returns:
            True if vote was added/updated, False if unchanged

        DESIGN: Uses BEGIN IMMEDIATE to acquire write lock immediately,
        preventing race conditions when multiple users vote concurrently.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                # BEGIN IMMEDIATE acquires write lock immediately to prevent race conditions
                cursor.execute("BEGIN IMMEDIATE")

                # Check existing vote
                cursor.execute(
                    "SELECT vote_type FROM votes WHERE voter_id = ? AND message_id = ?",
                    (voter_id, message_id)
                )
                existing = cursor.fetchone()

                if existing:
                    old_vote = existing[0]
                    if old_vote == vote_type:
                        conn.rollback()
                        return False  # Same vote, no change

                    # Update vote
                    cursor.execute(
                        "UPDATE votes SET vote_type = ? WHERE voter_id = ? AND message_id = ?",
                        (vote_type, voter_id, message_id)
                    )

                    # Update author karma (reverse old, apply new)
                    karma_change = vote_type - old_vote
                    self._update_user_karma(cursor, author_id, karma_change, vote_type)
                else:
                    # Insert new vote
                    cursor.execute(
                        """INSERT INTO votes (voter_id, message_id, author_id, vote_type)
                           VALUES (?, ?, ?, ?)""",
                        (voter_id, message_id, author_id, vote_type)
                    )

                    # Update author karma
                    self._update_user_karma(cursor, author_id, vote_type, vote_type)

                conn.commit()

                # Log successful vote with full context
                if existing:
                    logger.info("DB: Vote Updated", [
                        ("Voter", str(voter_id)),
                        ("Message", str(message_id)),
                        ("Author", str(author_id)),
                        ("Old Vote", "+1" if old_vote > 0 else "-1"),
                        ("New Vote", "+1" if vote_type > 0 else "-1"),
                        ("Karma Change", str(vote_type - old_vote)),
                    ])
                else:
                    logger.info("DB: Vote Added", [
                        ("Voter", str(voter_id)),
                        ("Message", str(message_id)),
                        ("Author", str(author_id)),
                        ("Vote", "+1" if vote_type > 0 else "-1"),
                    ])
                return True
            except sqlite3.OperationalError as e:
                conn.rollback()
                logger.warning("Vote Transaction Failed (Retryable)", [
                    ("Voter", str(voter_id)),
                    ("Message", str(message_id)),
                    ("Error", str(e)),
                ])
                raise
            except sqlite3.IntegrityError as e:
                conn.rollback()
                logger.warning("Vote Integrity Error", [
                    ("Voter", str(voter_id)),
                    ("Message", str(message_id)),
                    ("Error", str(e)),
                ])
                return False

    async def add_vote_async(
        self,
        voter_id: int,
        message_id: int,
        author_id: int,
        vote_type: int,
        max_retries: int = 3
    ) -> bool:
        """
        Async wrapper for add_vote with retry logic.
        Retries on OperationalError (lock contention) with exponential backoff.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(
                    self.add_vote, voter_id, message_id, author_id, vote_type
                )
            except sqlite3.OperationalError as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = 0.1 * (2 ** attempt)  # 0.1s, 0.2s, 0.4s
                    logger.warning("Vote Transaction Retry", [
                        ("Attempt", f"{attempt + 1}/{max_retries}"),
                        ("Delay", f"{delay}s"),
                        ("Voter", str(voter_id)),
                    ])
                    await asyncio.sleep(delay)

        # All retries failed
        logger.error("Vote Transaction Failed After Retries", [
            ("Voter", str(voter_id)),
            ("Message", str(message_id)),
            ("Error", str(last_error)),
        ])
        return False

    def remove_vote(
        self,
        voter_id: int,
        message_id: int
    ) -> Optional[int]:
        """
        Remove a vote.

        Args:
            voter_id: ID of user who voted
            message_id: ID of message

        Returns:
            Author ID if vote was removed, None otherwise

        DESIGN: Uses BEGIN IMMEDIATE to acquire write lock immediately,
        preventing race conditions when multiple users vote concurrently.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                # BEGIN IMMEDIATE acquires write lock immediately to prevent race conditions
                cursor.execute("BEGIN IMMEDIATE")

                # Get existing vote
                cursor.execute(
                    """SELECT author_id, vote_type FROM votes
                       WHERE voter_id = ? AND message_id = ?""",
                    (voter_id, message_id)
                )
                existing = cursor.fetchone()

                if not existing:
                    conn.rollback()
                    return None

                author_id, vote_type = existing

                # Delete vote
                cursor.execute(
                    "DELETE FROM votes WHERE voter_id = ? AND message_id = ?",
                    (voter_id, message_id)
                )

                # Reverse karma and decrement vote counter
                self._update_user_karma(cursor, author_id, -vote_type, vote_type, is_removal=True)

                conn.commit()

                logger.info("DB: Vote Removed", [
                    ("Voter", str(voter_id)),
                    ("Message", str(message_id)),
                    ("Author", str(author_id)),
                    ("Was Vote", "+1" if vote_type > 0 else "-1"),
                    ("Karma Reversed", str(-vote_type)),
                ])
                return author_id
            except sqlite3.OperationalError as e:
                conn.rollback()
                logger.warning("Remove Vote Transaction Failed (Retryable)", [
                    ("Voter", str(voter_id)),
                    ("Message", str(message_id)),
                    ("Error", str(e)),
                ])
                raise

    async def remove_vote_async(
        self,
        voter_id: int,
        message_id: int
    ) -> Optional[int]:
        """Async wrapper for remove_vote - runs in thread pool."""
        return await asyncio.to_thread(self.remove_vote, voter_id, message_id)

    def get_message_votes(self, message_id: int) -> dict[int, int]:
        """
        Get all votes for a specific message.

        Args:
            message_id: Discord message ID

        Returns:
            Dict of voter_id -> vote_type (+1 or -1)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT voter_id, vote_type FROM votes WHERE message_id = ?",
                    (message_id,)
                )
                return {row[0]: row[1] for row in cursor.fetchall()}
            finally:
                cursor.close()

    async def get_message_votes_async(self, message_id: int) -> dict[int, int]:
        """Async wrapper for get_message_votes - runs in thread pool."""
        return await asyncio.to_thread(self.get_message_votes, message_id)

    def _update_user_karma(
        self,
        cursor: sqlite3.Cursor,
        user_id: int,
        karma_change: int,
        vote_type: int,
        is_removal: bool = False
    ) -> None:
        """
        Update user karma totals.

        Args:
            cursor: Database cursor
            user_id: User to update
            karma_change: Net karma change
            vote_type: Type of vote (+1 for upvote, -1 for downvote)
            is_removal: True if removing a vote (decrements counter)
        """
        # Ensure user exists
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )

        # Determine counter change (+1 for add, -1 for remove)
        counter_change = -1 if is_removal else 1

        # Update karma and appropriate counter
        if vote_type > 0:
            cursor.execute(
                """UPDATE users SET
                   total_karma = total_karma + ?,
                   upvotes_received = MAX(0, upvotes_received + ?)
                   WHERE user_id = ?""",
                (karma_change, counter_change, user_id)
            )
        elif vote_type < 0:
            cursor.execute(
                """UPDATE users SET
                   total_karma = total_karma + ?,
                   downvotes_received = MAX(0, downvotes_received + ?)
                   WHERE user_id = ?""",
                (karma_change, counter_change, user_id)
            )

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    def get_user_karma(self, user_id: int) -> UserKarma:
        """
        Get karma data for a user.

        Args:
            user_id: User ID

        Returns:
            UserKarma data (defaults to 0 if not found)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """SELECT user_id, total_karma, upvotes_received, downvotes_received
                       FROM users WHERE user_id = ?""",
                    (user_id,)
                )
                row = cursor.fetchone()

                if row:
                    return UserKarma(*row)
                return UserKarma(user_id, 0, 0, 0)
            finally:
                cursor.close()

    async def get_user_karma_async(self, user_id: int) -> UserKarma:
        """Async wrapper for get_user_karma - runs in thread pool."""
        return await asyncio.to_thread(self.get_user_karma, user_id)

    def reset_user_karma(self, user_id: int) -> dict:
        """
        Reset karma for a user without deleting participation history.

        Removes:
        - User's karma record (total_karma, upvotes, downvotes)
        - All votes cast BY this user (reversing karma effects on recipients)
        - All votes received ON this user's messages

        Preserves:
        - debate_participation records (so user can be recognized on rejoin)
        - debate_creators records
        - Case log records
        - Any active bans

        Args:
            user_id: User ID to reset karma for

        Returns:
            Dict with counts of affected records
        """
        logger.info("Starting User Karma Reset", [
            ("User ID", str(user_id)),
        ])

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            result = {"karma_reset": False, "votes_cast_removed": 0, "votes_received_removed": 0}

            try:
                # Begin transaction
                cursor.execute("BEGIN IMMEDIATE")

                # Get current karma before reset
                cursor.execute(
                    "SELECT total_karma FROM users WHERE user_id = ?",
                    (user_id,)
                )
                row = cursor.fetchone()
                old_karma = row[0] if row else 0

                # Reset user's karma record to 0
                cursor.execute(
                    """UPDATE users SET
                       total_karma = 0,
                       upvotes_received = 0,
                       downvotes_received = 0
                       WHERE user_id = ?""",
                    (user_id,)
                )
                result["karma_reset"] = cursor.rowcount > 0
                result["old_karma"] = old_karma

                # Get all votes this user made to reverse karma effects
                cursor.execute(
                    "SELECT author_id, vote_type FROM votes WHERE voter_id = ?",
                    (user_id,)
                )
                votes_made = cursor.fetchall()
                for author_id, vote_type in votes_made:
                    # Reverse the karma effect on recipients
                    if vote_type > 0:
                        cursor.execute(
                            """UPDATE users SET
                               total_karma = total_karma - 1,
                               upvotes_received = MAX(0, upvotes_received - 1)
                               WHERE user_id = ?""",
                            (author_id,)
                        )
                    else:
                        cursor.execute(
                            """UPDATE users SET
                               total_karma = total_karma + 1,
                               downvotes_received = MAX(0, downvotes_received - 1)
                               WHERE user_id = ?""",
                            (author_id,)
                        )

                # Delete votes cast by this user
                cursor.execute("DELETE FROM votes WHERE voter_id = ?", (user_id,))
                result["votes_cast_removed"] = cursor.rowcount

                # Delete votes received on this user's messages
                cursor.execute("DELETE FROM votes WHERE author_id = ?", (user_id,))
                result["votes_received_removed"] = cursor.rowcount

                conn.commit()

                logger.info("User Karma Reset Complete", [
                    ("User ID", str(user_id)),
                    ("Old Karma", str(old_karma)),
                    ("Votes Cast Removed", str(result["votes_cast_removed"])),
                    ("Votes Received Removed", str(result["votes_received_removed"])),
                ])

                return result

            except sqlite3.Error as e:
                conn.rollback()
                logger.error("User Karma Reset Failed - Rolled Back", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)),
                ])
                return {"error": str(e), "karma_reset": False, "votes_cast_removed": 0, "votes_received_removed": 0}
            finally:
                cursor.close()

    async def reset_user_karma_async(self, user_id: int) -> dict:
        """Async wrapper for reset_user_karma - runs in thread pool."""
        return await asyncio.to_thread(self.reset_user_karma, user_id)

    def get_votes_by_user(self, user_id: int) -> list[dict]:
        """
        Get all votes cast by a user.

        Args:
            user_id: The voter's user ID

        Returns:
            List of dicts with message_id, author_id, vote_type
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """SELECT message_id, author_id, vote_type
                       FROM votes WHERE voter_id = ?""",
                    (user_id,)
                )
                return [
                    {"message_id": row[0], "author_id": row[1], "vote_type": row[2]}
                    for row in cursor.fetchall()
                ]
            finally:
                cursor.close()

    def get_votes_today(self) -> int:
        """
        Get total number of votes cast today.

        Returns:
            Count of votes cast today
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """SELECT COUNT(*) FROM votes
                       WHERE DATE(created_at) = DATE('now')"""
                )
                return cursor.fetchone()[0]
            finally:
                cursor.close()

    def get_active_debate_count(self) -> int:
        """
        Get count of tracked debate threads.

        Returns:
            Count of debate threads
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """SELECT COUNT(*) FROM debate_threads"""
                )
                return cursor.fetchone()[0]
            finally:
                cursor.close()

    def remove_votes_by_user(self, user_id: int) -> dict:
        """
        Remove all votes cast by a user and reverse karma effects.

        Args:
            user_id: The voter's user ID

        Returns:
            Dict with count of votes removed and karma changes
        """
        logger.info("Removing All Votes By User", [
            ("User ID", str(user_id)),
        ])

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            result = {"votes_removed": 0, "karma_reversed": []}

            try:
                cursor.execute("BEGIN IMMEDIATE")

                # Get all votes this user made
                cursor.execute(
                    "SELECT message_id, author_id, vote_type FROM votes WHERE voter_id = ?",
                    (user_id,)
                )
                votes = cursor.fetchall()

                # Reverse karma for each affected user
                for message_id, author_id, vote_type in votes:
                    if vote_type > 0:
                        cursor.execute(
                            """UPDATE users SET
                               total_karma = total_karma - 1,
                               upvotes_received = MAX(0, upvotes_received - 1)
                               WHERE user_id = ?""",
                            (author_id,)
                        )
                    else:
                        cursor.execute(
                            """UPDATE users SET
                               total_karma = total_karma + 1,
                               downvotes_received = MAX(0, downvotes_received - 1)
                               WHERE user_id = ?""",
                            (author_id,)
                        )
                    result["karma_reversed"].append({
                        "author_id": author_id,
                        "change": -vote_type  # Reverse the vote effect
                    })

                # Delete all votes by this user
                cursor.execute("DELETE FROM votes WHERE voter_id = ?", (user_id,))
                result["votes_removed"] = cursor.rowcount

                conn.commit()

                logger.info("Votes Removed Successfully", [
                    ("User ID", str(user_id)),
                    ("Votes Removed", str(result["votes_removed"])),
                    ("Users Affected", str(len(result["karma_reversed"]))),
                ])

                return result

            except sqlite3.Error as e:
                conn.rollback()
                logger.error("Failed To Remove Votes By User", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)),
                ])
                return {"error": str(e), "votes_removed": 0, "karma_reversed": []}
            finally:
                cursor.close()

    def get_leaderboard(self, limit: int = 10) -> list[UserKarma]:
        """
        Get top users by karma.

        Args:
            limit: Number of users to return

        Returns:
            List of UserKarma sorted by total_karma desc
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """SELECT user_id, total_karma, upvotes_received, downvotes_received
                       FROM users
                       ORDER BY total_karma DESC
                       LIMIT ?""",
                    (limit,)
                )
                return [UserKarma(*row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    async def get_leaderboard_async(self, limit: int = 10) -> list[UserKarma]:
        """Async wrapper for get_leaderboard - runs in thread pool."""
        return await asyncio.to_thread(self.get_leaderboard, limit)

    def get_user_rank(self, user_id: int) -> int:
        """
        Get user's rank on leaderboard.

        Args:
            user_id: User ID

        Returns:
            Rank (1-indexed), or 0 if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """SELECT COUNT(*) + 1 FROM users
                       WHERE total_karma > (
                           SELECT COALESCE(total_karma, 0) FROM users WHERE user_id = ?
                       )""",
                    (user_id,)
                )
                return cursor.fetchone()[0]
            finally:
                cursor.close()

    async def get_user_rank_async(self, user_id: int) -> int:
        """Async wrapper for get_user_rank - runs in thread pool."""
        return await asyncio.to_thread(self.get_user_rank, user_id)

    def get_user_analytics(self, user_id: int) -> dict:
        """
        Get detailed analytics for a user's debate participation.

        Args:
            user_id: Discord user ID

        Returns:
            Dict with debates_participated, debates_created, total_messages
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                # Count debates participated in
                cursor.execute(
                    "SELECT COUNT(*) FROM debate_participation WHERE user_id = ?",
                    (user_id,)
                )
                debates_participated = cursor.fetchone()[0] or 0

                # Count debates created
                cursor.execute(
                    "SELECT COUNT(*) FROM debate_creators WHERE user_id = ?",
                    (user_id,)
                )
                debates_created = cursor.fetchone()[0] or 0

                # Sum total messages across all debates
                cursor.execute(
                    "SELECT COALESCE(SUM(message_count), 0) FROM debate_participation WHERE user_id = ?",
                    (user_id,)
                )
                total_messages = cursor.fetchone()[0] or 0

                return {
                    "debates_participated": debates_participated,
                    "debates_created": debates_created,
                    "total_messages": total_messages,
                }
            finally:
                cursor.close()

    async def get_user_analytics_async(self, user_id: int) -> dict:
        """Async wrapper for get_user_analytics - runs in thread pool."""
        return await asyncio.to_thread(self.get_user_analytics, user_id)

    def has_debate_participation(self, user_id: int) -> bool:
        """
        Check if a user has ever participated in debates.

        Args:
            user_id: Discord user ID

        Returns:
            True if user has participated in at least one debate or created a debate
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                # Check debate_participation table
                cursor.execute(
                    "SELECT 1 FROM debate_participation WHERE user_id = ? LIMIT 1",
                    (user_id,)
                )
                if cursor.fetchone():
                    return True

                # Check debate_creators table
                cursor.execute(
                    "SELECT 1 FROM debate_creators WHERE user_id = ? LIMIT 1",
                    (user_id,)
                )
                if cursor.fetchone():
                    return True

                # Check users table (they might have received karma)
                cursor.execute(
                    "SELECT 1 FROM users WHERE user_id = ? AND total_karma != 0 LIMIT 1",
                    (user_id,)
                )
                if cursor.fetchone():
                    return True

                return False
            finally:
                cursor.close()

    # -------------------------------------------------------------------------
    # Streak Operations
    # -------------------------------------------------------------------------

    def update_user_streak(self, user_id: int) -> dict:
        """
        Update a user's daily participation streak.

        Called when user participates in a debate. Checks if they've
        already been active today, and updates streak accordingly.

        Args:
            user_id: Discord user ID

        Returns:
            Dict with current_streak, longest_streak, streak_extended (bool)
        """
        from datetime import datetime
        from src.core.config import NY_TZ

        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                # Get current streak data
                cursor.execute(
                    "SELECT current_streak, longest_streak, last_active_date FROM user_streaks WHERE user_id = ?",
                    (user_id,)
                )
                row = cursor.fetchone()

                if row:
                    current_streak, longest_streak, last_active_date = row

                    if last_active_date == today:
                        # Already active today, no change
                        return {
                            "current_streak": current_streak,
                            "longest_streak": longest_streak,
                            "streak_extended": False,
                        }

                    # Check if yesterday was active (streak continues)
                    yesterday = (datetime.now(NY_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

                    if last_active_date == yesterday:
                        # Streak continues
                        new_streak = current_streak + 1
                    else:
                        # Streak broken, start fresh
                        new_streak = 1

                    new_longest = max(longest_streak, new_streak)

                    cursor.execute(
                        """UPDATE user_streaks
                           SET current_streak = ?, longest_streak = ?, last_active_date = ?,
                               updated_at = CURRENT_TIMESTAMP
                           WHERE user_id = ?""",
                        (new_streak, new_longest, today, user_id)
                    )
                else:
                    # First time participation
                    new_streak = 1
                    new_longest = 1
                    cursor.execute(
                        """INSERT INTO user_streaks (user_id, current_streak, longest_streak, last_active_date)
                           VALUES (?, 1, 1, ?)""",
                        (user_id, today)
                    )

                conn.commit()

                return {
                    "current_streak": new_streak,
                    "longest_streak": new_longest,
                    "streak_extended": True,
                }
            finally:
                cursor.close()

    async def update_user_streak_async(self, user_id: int) -> dict:
        """Async wrapper for update_user_streak - runs in thread pool."""
        return await asyncio.to_thread(self.update_user_streak, user_id)

    def get_user_streak(self, user_id: int) -> dict:
        """
        Get a user's current streak data.

        Args:
            user_id: Discord user ID

        Returns:
            Dict with current_streak, longest_streak
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    "SELECT current_streak, longest_streak, last_active_date FROM user_streaks WHERE user_id = ?",
                    (user_id,)
                )
                row = cursor.fetchone()

                if row:
                    current_streak, longest_streak, last_active_date = row

                    # Check if streak is still active (was active yesterday or today)
                    from datetime import datetime
                    from src.core.config import NY_TZ

                    today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
                    yesterday = (datetime.now(NY_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

                    if last_active_date not in (today, yesterday):
                        # Streak has expired
                        current_streak = 0

                    return {
                        "current_streak": current_streak,
                        "longest_streak": longest_streak,
                    }

                return {
                    "current_streak": 0,
                    "longest_streak": 0,
                }
            finally:
                cursor.close()

    async def get_user_streak_async(self, user_id: int) -> dict:
        """Async wrapper for get_user_streak - runs in thread pool."""
        return await asyncio.to_thread(self.get_user_streak, user_id)

    def get_top_streaks(self, limit: int = 3) -> list[dict]:
        """
        Get users with the highest current streaks.

        Args:
            limit: Maximum number of users to return

        Returns:
            List of dicts with user_id, current_streak, longest_streak
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                # Only include users with active streaks (participated today or yesterday)
                from src.core.config import NY_TZ
                today = datetime.now(NY_TZ).strftime('%Y-%m-%d')
                yesterday = (datetime.now(NY_TZ) - timedelta(days=1)).strftime('%Y-%m-%d')

                cursor.execute(
                    """SELECT user_id, current_streak, longest_streak
                       FROM user_streaks
                       WHERE current_streak > 0
                       AND last_active_date IN (?, ?)
                       ORDER BY current_streak DESC, longest_streak DESC
                       LIMIT ?""",
                    (today, yesterday, limit)
                )
                rows = cursor.fetchall()

                return [
                    {
                        'user_id': row[0],
                        'current_streak': row[1],
                        'longest_streak': row[2]
                    }
                    for row in rows
                ]
            except Exception as e:
                logger.error("DB: Failed To Get Top Streaks", [
                    ("Error", str(e)),
                ])
                return []
            finally:
                cursor.close()

    # -------------------------------------------------------------------------
    # Debate Thread Operations
    # -------------------------------------------------------------------------

    def set_analytics_message(self, thread_id: int, message_id: int) -> None:
        """
        Set the analytics message ID for a debate thread.

        Args:
            thread_id: Discord thread ID
            message_id: Discord message ID of the analytics embed
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO debate_threads (thread_id, analytics_message_id)
                   VALUES (?, ?)""",
                (thread_id, message_id)
            )
            conn.commit()
            logger.info("DB: Analytics Message Set", [
                ("Thread ID", str(thread_id)),
                ("Message ID", str(message_id)),
            ])

    async def set_analytics_message_async(self, thread_id: int, message_id: int) -> None:
        """Async wrapper for set_analytics_message - runs in thread pool."""
        await asyncio.to_thread(self.set_analytics_message, thread_id, message_id)

    def get_analytics_message(self, thread_id: int) -> Optional[int]:
        """
        Get the analytics message ID for a debate thread.

        Args:
            thread_id: Discord thread ID

        Returns:
            Message ID if found, None otherwise
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT analytics_message_id FROM debate_threads WHERE thread_id = ?",
                (thread_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    async def get_analytics_message_async(self, thread_id: int) -> Optional[int]:
        """Async wrapper for get_analytics_message - runs in thread pool."""
        return await asyncio.to_thread(self.get_analytics_message, thread_id)

    def clear_analytics_message(self, thread_id: int) -> None:
        """
        Clear the analytics message reference for a debate thread.

        Used when the Discord message is deleted but our DB still has a reference.
        This prevents repeated NotFound errors on future interactions.

        Args:
            thread_id: Discord thread ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE debate_threads SET analytics_message_id = NULL WHERE thread_id = ?",
                (thread_id,)
            )
            rows_affected = cursor.rowcount
            conn.commit()
            logger.info("DB: Analytics Message Cleared", [
                ("Thread ID", str(thread_id)),
                ("Rows Affected", str(rows_affected)),
            ])

    async def clear_analytics_message_async(self, thread_id: int) -> None:
        """Async wrapper for clear_analytics_message - runs in thread pool."""
        await asyncio.to_thread(self.clear_analytics_message, thread_id)

    # -------------------------------------------------------------------------
    # Debate Ban Operations
    # -------------------------------------------------------------------------

    def add_debate_ban(
        self,
        user_id: int,
        thread_id: Optional[int],
        banned_by: int,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None
    ) -> bool:
        """
        Ban a user from a specific thread or all debates.

        Args:
            user_id: User to ban
            thread_id: Thread ID to ban from (None = all debates)
            banned_by: User ID who issued the ban
            reason: Optional reason for the ban
            expires_at: Optional ISO format timestamp when ban expires

        Returns:
            True if ban was added, False if already exists
        """
        success = False
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """INSERT OR REPLACE INTO debate_bans (user_id, thread_id, banned_by, reason, expires_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, thread_id, banned_by, reason, expires_at)
                )
                conn.commit()
                success = True
            except sqlite3.IntegrityError as e:
                # User already banned (unique constraint violation)
                logger.debug("Ban Already Exists (Integrity Constraint)", [
                    ("User ID", str(user_id)),
                    ("Thread ID", str(thread_id) if thread_id else "all"),
                    ("Error", str(e)),
                ])
            except sqlite3.OperationalError as e:
                logger.warning("Database Operational Error In add_debate_ban", [
                    ("User ID", str(user_id)),
                    ("Thread ID", str(thread_id) if thread_id else "all"),
                    ("Error", str(e)),
                ])

        # Audit log and ban history OUTSIDE the lock to prevent deadlock
        if success:
            self.audit_log(
                action='ban_add',
                actor_id=banned_by,
                target_id=user_id,
                target_type='user',
                new_value=str(thread_id) if thread_id else 'all',
                metadata={'reason': reason, 'expires_at': expires_at}
            )
            # Also record to ban_history for permanent tracking
            self._add_to_ban_history(
                user_id=user_id,
                thread_id=thread_id,
                banned_by=banned_by,
                reason=reason,
                expires_at=expires_at
            )
        return success

    async def add_debate_ban_async(
        self,
        user_id: int,
        thread_id: Optional[int],
        banned_by: int,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None
    ) -> bool:
        """Async wrapper for add_debate_ban - runs in thread pool."""
        return await asyncio.to_thread(
            self.add_debate_ban, user_id, thread_id, banned_by, reason, expires_at
        )

    def remove_debate_ban(self, user_id: int, thread_id: Optional[int]) -> bool:
        """
        Remove a debate ban.

        Args:
            user_id: User to unban
            thread_id: Thread ID (None = remove ALL bans for this user)

        Returns:
            True if ban was removed, False if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if thread_id is None:
                # Remove ALL bans for this user (both global and thread-specific)
                cursor.execute(
                    "DELETE FROM debate_bans WHERE user_id = ?",
                    (user_id,)
                )
            else:
                cursor.execute(
                    "DELETE FROM debate_bans WHERE user_id = ? AND thread_id = ?",
                    (user_id, thread_id)
                )
            removed = cursor.rowcount > 0
            conn.commit()

        # Audit log OUTSIDE the lock to prevent deadlock
        if removed:
            self.audit_log(
                action='ban_remove',
                target_id=user_id,
                target_type='user',
                old_value=str(thread_id) if thread_id else 'all',
            )
        return removed

    async def remove_debate_ban_async(self, user_id: int, thread_id: Optional[int]) -> bool:
        """Async wrapper for remove_debate_ban - runs in thread pool."""
        return await asyncio.to_thread(self.remove_debate_ban, user_id, thread_id)

    def is_user_banned(self, user_id: int, thread_id: int) -> bool:
        """
        Check if user is banned from a specific thread.

        Args:
            user_id: User to check
            thread_id: Thread ID to check

        Returns:
            True if user is banned from this thread or all debates (and ban hasn't expired)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Check for specific thread ban OR global debates ban (thread_id IS NULL)
            # Exclude expired bans (expires_at IS NULL means permanent)
            cursor.execute(
                """SELECT 1 FROM debate_bans
                   WHERE user_id = ? AND (thread_id = ? OR thread_id IS NULL)
                   AND (expires_at IS NULL OR expires_at > datetime('now'))
                   LIMIT 1""",
                (user_id, thread_id)
            )
            return cursor.fetchone() is not None

    async def is_user_banned_async(self, user_id: int, thread_id: int) -> bool:
        """Async wrapper for is_user_banned - runs in thread pool."""
        return await asyncio.to_thread(self.is_user_banned, user_id, thread_id)

    def get_user_bans(self, user_id: int) -> list[dict]:
        """
        Get all active bans for a user.

        Args:
            user_id: User ID

        Returns:
            List of ban records (excludes expired bans)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT thread_id, banned_by, reason, expires_at, created_at
                   FROM debate_bans
                   WHERE user_id = ?
                   AND (expires_at IS NULL OR expires_at > datetime('now'))""",
                (user_id,)
            )
            return [
                {
                    "thread_id": row[0],
                    "banned_by": row[1],
                    "reason": row[2],
                    "expires_at": row[3],
                    "created_at": row[4]
                }
                for row in cursor.fetchall()
            ]

    def get_all_banned_users(self) -> list[int]:
        """
        Get all unique user IDs that have active bans.

        Returns:
            List of user IDs with active bans (excludes expired)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT DISTINCT user_id FROM debate_bans
                   WHERE expires_at IS NULL OR expires_at > datetime('now')"""
            )
            return [row[0] for row in cursor.fetchall()]

    def get_banned_users_with_info(self) -> list[dict]:
        """
        Get all banned users with their ban details for autocomplete.

        Returns:
            List of dicts with user_id, expires_at, thread_id
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, expires_at, thread_id FROM debate_bans
                   WHERE expires_at IS NULL OR expires_at > datetime('now')
                   ORDER BY expires_at ASC NULLS LAST"""
            )
            return [
                {"user_id": row[0], "expires_at": row[1], "thread_id": row[2]}
                for row in cursor.fetchall()
            ]

    def get_expired_bans(self) -> list[dict]:
        """
        Get all expired bans that need to be removed.

        Returns:
            List of expired ban records with full details
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, thread_id, banned_by, reason, expires_at, created_at
                   FROM debate_bans
                   WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"""
            )
            return [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "thread_id": row[2],
                    "banned_by": row[3],
                    "reason": row[4],
                    "expires_at": row[5],
                    "created_at": row[6],
                }
                for row in cursor.fetchall()
            ]

    def _add_to_ban_history(
        self,
        user_id: int,
        thread_id: Optional[int],
        banned_by: int,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None,
        duration: Optional[str] = None
    ) -> None:
        """
        Add a ban record to the permanent ban_history table.

        Args:
            user_id: User who was banned
            thread_id: Thread ID (None = global ban)
            banned_by: Moderator who banned
            reason: Ban reason
            expires_at: Expiry timestamp
            duration: Human-readable duration (e.g., "1 Week")
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO ban_history
                       (user_id, thread_id, banned_by, reason, duration, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (user_id, thread_id, banned_by, reason, duration, expires_at)
                )
                conn.commit()
            except Exception as e:
                logger.debug("Failed to add ban to history", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)),
                ])

    def update_ban_history_removal(
        self,
        user_id: int,
        removed_by: int,
        removal_reason: str = "Appeal approved"
    ) -> bool:
        """
        Update ban_history to mark ban as removed (e.g., via appeal).

        Args:
            user_id: User whose ban was removed
            removed_by: Moderator who approved the removal
            removal_reason: Reason for removal

        Returns:
            True if updated, False otherwise
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # Update the most recent unremoved ban for this user
                cursor.execute(
                    """UPDATE ban_history
                       SET removed_at = CURRENT_TIMESTAMP,
                           removed_by = ?,
                           removal_reason = ?
                       WHERE user_id = ? AND removed_at IS NULL
                       ORDER BY created_at DESC LIMIT 1""",
                    (removed_by, removal_reason, user_id)
                )
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.debug("Failed to update ban history removal", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)),
                ])
                return False

    def get_user_ban_count(self, user_id: int) -> int:
        """
        Get the total number of times a user has been banned (from ban_history).

        Args:
            user_id: User ID to check

        Returns:
            Total ban count across all time
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM ban_history WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_user_ban_history(self, user_id: int, limit: int = 10) -> list[dict]:
        """
        Get a user's ban history.

        Args:
            user_id: User ID to check
            limit: Maximum number of records to return

        Returns:
            List of ban history records, most recent first
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, thread_id, banned_by, reason, duration, expires_at,
                          created_at, removed_at, removed_by, removal_reason
                   FROM ban_history
                   WHERE user_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, limit)
            )
            return [
                {
                    "id": row[0],
                    "thread_id": row[1],
                    "banned_by": row[2],
                    "reason": row[3],
                    "duration": row[4],
                    "expires_at": row[5],
                    "created_at": row[6],
                    "removed_at": row[7],
                    "removed_by": row[8],
                    "removal_reason": row[9]
                }
                for row in cursor.fetchall()
            ]

    def get_ban_history_at_time(
        self,
        user_id: int,
        appeal_created_at: str
    ) -> Optional[dict]:
        """
        Get the ban from ban_history that was active at the time of an appeal.

        Finds the most recent ban created before the appeal was submitted.

        Args:
            user_id: User ID to check
            appeal_created_at: ISO timestamp of when the appeal was submitted

        Returns:
            Ban history record dict or None if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Get the most recent ban that was created before or at the appeal time
            cursor.execute(
                """SELECT id, thread_id, banned_by, reason, duration, expires_at,
                          created_at, removed_at, removed_by, removal_reason
                   FROM ban_history
                   WHERE user_id = ? AND created_at <= ?
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (user_id, appeal_created_at)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "thread_id": row[1],
                    "banned_by": row[2],
                    "reason": row[3],
                    "duration": row[4],
                    "expires_at": row[5],
                    "created_at": row[6],
                    "removed_at": row[7],
                    "removed_by": row[8],
                    "removal_reason": row[9]
                }
            return None

    # -------------------------------------------------------------------------
    # Closure History Operations
    # -------------------------------------------------------------------------

    def add_to_closure_history(
        self,
        user_id: int,
        thread_id: int,
        thread_name: str,
        closed_by: int,
        reason: Optional[str] = None
    ) -> None:
        """
        Add a closure record to the permanent closure_history table.

        Args:
            user_id: Thread owner who had their thread closed
            thread_id: The closed thread ID
            thread_name: Thread name at time of closure
            closed_by: Moderator who closed it
            reason: Closure reason
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO closure_history
                       (user_id, thread_id, thread_name, closed_by, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, thread_id, thread_name, closed_by, reason)
                )
                conn.commit()
            except Exception as e:
                logger.debug("Failed to add closure to history", [
                    ("User ID", str(user_id)),
                    ("Thread ID", str(thread_id)),
                    ("Error", str(e)),
                ])

    def get_user_closure_count(self, user_id: int) -> int:
        """
        Get the total number of times a user has had threads closed.

        Args:
            user_id: User ID to check

        Returns:
            Total closure count across all time
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM closure_history WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_user_closure_history(self, user_id: int, limit: int = 10) -> list[dict]:
        """
        Get a user's thread closure history.

        Args:
            user_id: User ID to check
            limit: Maximum number of records to return

        Returns:
            List of closure history records, most recent first
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, thread_id, thread_name, closed_by, reason,
                          created_at, reopened_at, reopened_by
                   FROM closure_history
                   WHERE user_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, limit)
            )
            return [
                {
                    "id": row[0],
                    "thread_id": row[1],
                    "thread_name": row[2],
                    "closed_by": row[3],
                    "reason": row[4],
                    "created_at": row[5],
                    "reopened_at": row[6],
                    "reopened_by": row[7]
                }
                for row in cursor.fetchall()
            ]

    def get_closure_by_thread_id(self, thread_id: int) -> Optional[dict]:
        """
        Get the most recent closure record for a specific thread.

        Args:
            thread_id: The thread ID to look up

        Returns:
            Closure history record dict or None if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, thread_name, closed_by, reason,
                          created_at, reopened_at, reopened_by
                   FROM closure_history
                   WHERE thread_id = ?
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (thread_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "thread_name": row[2],
                    "closed_by": row[3],
                    "reason": row[4],
                    "created_at": row[5],
                    "reopened_at": row[6],
                    "reopened_by": row[7]
                }
            return None

    def update_closure_history_reopened(
        self,
        thread_id: int,
        reopened_by: int
    ) -> bool:
        """
        Update closure_history to mark thread as reopened (e.g., via appeal).

        Args:
            thread_id: The thread that was reopened
            reopened_by: Moderator who approved the reopening

        Returns:
            True if updated, False otherwise
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # Update the most recent unresolved closure for this thread
                cursor.execute(
                    """UPDATE closure_history
                       SET reopened_at = CURRENT_TIMESTAMP,
                           reopened_by = ?
                       WHERE thread_id = ? AND reopened_at IS NULL
                       ORDER BY created_at DESC LIMIT 1""",
                    (reopened_by, thread_id)
                )
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.debug("Failed to update closure history reopened", [
                    ("Thread ID", str(thread_id)),
                    ("Error", str(e)),
                ])
                return False

    def remove_expired_bans(self) -> int:
        """
        Remove all expired bans from the database.

        Returns:
            Number of bans removed
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """DELETE FROM debate_bans
                   WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"""
            )
            conn.commit()
            return cursor.rowcount

    # -------------------------------------------------------------------------
    # User Data Cleanup (Member Leave)
    # -------------------------------------------------------------------------

    def delete_user_data(self, user_id: int) -> dict:
        """
        Delete all data for a user who left the server.

        This removes:
        - User karma record
        - All votes cast BY this user
        - All votes received ON this user's messages
        - Any debate bans

        Args:
            user_id: User ID to purge

        Returns:
            Dict with counts of deleted records
        """
        logger.info("Starting User Data Deletion", [
            ("User ID", str(user_id)),
        ])

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            deleted = {}

            try:
                # Begin explicit transaction for atomicity
                cursor.execute("BEGIN IMMEDIATE")

                # Delete from users table (karma)
                cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                deleted["karma"] = cursor.rowcount

                # Delete votes cast by this user (and update affected users' karma)
                # First, get all votes this user made to reverse them
                cursor.execute(
                    "SELECT author_id, vote_type FROM votes WHERE voter_id = ?",
                    (user_id,)
                )
                votes_made = cursor.fetchall()
                for author_id, vote_type in votes_made:
                    # Reverse the karma effect
                    if vote_type > 0:
                        cursor.execute(
                            """UPDATE users SET
                               total_karma = total_karma - 1,
                               upvotes_received = MAX(0, upvotes_received - 1)
                               WHERE user_id = ?""",
                            (author_id,)
                        )
                    else:
                        cursor.execute(
                            """UPDATE users SET
                               total_karma = total_karma + 1,
                               downvotes_received = MAX(0, downvotes_received - 1)
                               WHERE user_id = ?""",
                            (author_id,)
                        )

                cursor.execute("DELETE FROM votes WHERE voter_id = ?", (user_id,))
                deleted["votes_cast"] = cursor.rowcount

                # Delete votes received on this user's messages
                cursor.execute("DELETE FROM votes WHERE author_id = ?", (user_id,))
                deleted["votes_received"] = cursor.rowcount

                # Delete debate bans
                cursor.execute("DELETE FROM debate_bans WHERE user_id = ?", (user_id,))
                deleted["bans"] = cursor.rowcount

                conn.commit()

                logger.info("User Data Deletion Complete", [
                    ("User ID", str(user_id)),
                    ("Karma Records", str(deleted.get("karma", 0))),
                    ("Votes Cast", str(deleted.get("votes_cast", 0))),
                    ("Votes Received", str(deleted.get("votes_received", 0))),
                    ("Bans", str(deleted.get("bans", 0))),
                ])

                return deleted

            except sqlite3.Error as e:
                conn.rollback()
                logger.error("User Data Deletion Failed - Rolled Back", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)),
                ])
                return {"error": str(e), "karma": 0, "votes_cast": 0, "votes_received": 0, "bans": 0}

    async def delete_user_data_async(self, user_id: int) -> dict:
        """Async wrapper for delete_user_data - runs in thread pool."""
        return await asyncio.to_thread(self.delete_user_data, user_id)

    def delete_thread_data(self, thread_id: int) -> dict:
        """
        Delete all database records associated with a thread.

        Called when a debate thread is deleted.

        Args:
            thread_id: Discord thread ID

        Returns:
            Dict with counts of deleted records
        """
        deleted = {
            "debate_threads": 0,
            "debate_bans": 0,
            "debate_participation": 0,
            "debate_creators": 0,
        }

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                # Begin explicit transaction for atomicity
                cursor.execute("BEGIN IMMEDIATE")

                # Delete from debate_threads (analytics message reference)
                cursor.execute("DELETE FROM debate_threads WHERE thread_id = ?", (thread_id,))
                deleted["debate_threads"] = cursor.rowcount

                # Delete thread-specific bans (where thread_id matches)
                cursor.execute("DELETE FROM debate_bans WHERE thread_id = ?", (thread_id,))
                deleted["debate_bans"] = cursor.rowcount

                # Delete participation records for this thread
                cursor.execute("DELETE FROM debate_participation WHERE thread_id = ?", (thread_id,))
                deleted["debate_participation"] = cursor.rowcount

                # Delete creator record for this thread
                cursor.execute("DELETE FROM debate_creators WHERE thread_id = ?", (thread_id,))
                deleted["debate_creators"] = cursor.rowcount

                conn.commit()

                logger.info("DB: Thread Data Deleted", [
                    ("Thread ID", str(thread_id)),
                    ("Threads Table", str(deleted["debate_threads"])),
                    ("Bans", str(deleted["debate_bans"])),
                    ("Participation", str(deleted["debate_participation"])),
                    ("Creators", str(deleted["debate_creators"])),
                ])

                return deleted

            except sqlite3.Error as e:
                conn.rollback()
                logger.error("Thread Data Deletion Failed - Rolled Back", [
                    ("Thread ID", str(thread_id)),
                    ("Error", str(e)),
                ])
                return {"error": str(e), **deleted}

    # -------------------------------------------------------------------------
    # Leaderboard Thread Operations
    # -------------------------------------------------------------------------

    def get_leaderboard_thread(self) -> Optional[int]:
        """
        Get saved leaderboard thread ID.

        Returns:
            Thread ID if found, None otherwise
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT thread_id FROM leaderboard_thread WHERE id = 1")
            row = cursor.fetchone()
            return row[0] if row else None

    def set_leaderboard_thread(self, thread_id: int) -> None:
        """
        Save leaderboard thread ID.

        Args:
            thread_id: Discord thread ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO leaderboard_thread (id, thread_id)
                   VALUES (1, ?)""",
                (thread_id,)
            )
            conn.commit()

    def clear_leaderboard_thread(self) -> None:
        """Clear saved leaderboard thread ID and all month embeds."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM leaderboard_thread WHERE id = 1")
            cursor.execute("DELETE FROM leaderboard_embeds")
            conn.commit()
            logger.info("📊 Cleared leaderboard thread and month embeds from database")

    # -------------------------------------------------------------------------
    # Monthly Leaderboard Operations
    # -------------------------------------------------------------------------

    def get_monthly_leaderboard(
        self,
        year: int,
        month: int,
        limit: int = 3
    ) -> list[UserKarma]:
        """
        Get top users by karma for a specific month.

        Args:
            year: Year (e.g., 2024)
            month: Month (1-12)
            limit: Number of users to return

        Returns:
            List of UserKarma sorted by monthly karma desc
        """
        # Validate month is in valid range
        if not 1 <= month <= 12:
            logger.warning("Invalid month for leaderboard query", [
                ("Month", str(month)),
                ("Expected", "1-12"),
            ])
            return []

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Calculate karma from votes in the specified month
            cursor.execute(
                """SELECT
                       author_id,
                       SUM(vote_type) as monthly_karma,
                       SUM(CASE WHEN vote_type > 0 THEN 1 ELSE 0 END) as upvotes,
                       SUM(CASE WHEN vote_type < 0 THEN 1 ELSE 0 END) as downvotes
                   FROM votes
                   WHERE strftime('%Y', created_at) = ?
                     AND strftime('%m', created_at) = ?
                   GROUP BY author_id
                   ORDER BY monthly_karma DESC
                   LIMIT ?""",
                (str(year), f"{month:02d}", limit)
            )
            return [
                UserKarma(
                    user_id=row[0],
                    total_karma=row[1],
                    upvotes_received=row[2],
                    downvotes_received=row[3]
                )
                for row in cursor.fetchall()
            ]

    # -------------------------------------------------------------------------
    # Leaderboard Embed Operations
    # -------------------------------------------------------------------------

    def get_month_embed(self, year: int, month: int) -> Optional[int]:
        """
        Get message ID for a month's embed.

        Args:
            year: Year
            month: Month (1-12)

        Returns:
            Message ID if found, None otherwise
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT message_id FROM leaderboard_embeds WHERE year = ? AND month = ?",
                (year, month)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def set_month_embed(self, year: int, month: int, message_id: int) -> None:
        """
        Save message ID for a month's embed.

        Args:
            year: Year
            month: Month (1-12)
            message_id: Discord message ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO leaderboard_embeds (year, month, message_id)
                   VALUES (?, ?, ?)""",
                (year, month, message_id)
            )
            conn.commit()

    def get_all_month_embeds(self) -> list[dict]:
        """
        Get all monthly embed message IDs.

        Returns:
            List of dicts with year, month, message_id
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT year, month, message_id FROM leaderboard_embeds
                   ORDER BY year DESC, month DESC"""
            )
            return [
                {"year": row[0], "month": row[1], "message_id": row[2]}
                for row in cursor.fetchall()
            ]

    def delete_month_embed(self, year: int, month: int) -> None:
        """
        Delete a monthly embed record (when message is deleted/not found).

        Args:
            year: Year
            month: Month (1-12)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM leaderboard_embeds WHERE year = ? AND month = ?",
                (year, month)
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # User Cache Operations (for "(left)" tracking)
    # -------------------------------------------------------------------------

    def cache_user(
        self,
        user_id: int,
        username: str,
        display_name: Optional[str] = None
    ) -> None:
        """
        Cache user info when they vote or receive karma.

        Args:
            user_id: Discord user ID
            username: Discord username
            display_name: Display name (nickname)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Check if user exists first
            cursor.execute("SELECT 1 FROM user_cache WHERE user_id = ?", (user_id,))
            is_new_user = cursor.fetchone() is None

            cursor.execute(
                """INSERT INTO user_cache (user_id, username, display_name, is_member, updated_at)
                   VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                       username = excluded.username,
                       display_name = excluded.display_name,
                       is_member = 1,
                       updated_at = CURRENT_TIMESTAMP""",
                (user_id, username, display_name)
            )
            conn.commit()

            if is_new_user:
                logger.info("DB: New User Cached", [
                    ("User ID", str(user_id)),
                    ("Username", username),
                ])

    def get_cached_user(self, user_id: int) -> Optional[dict]:
        """
        Get cached user info.

        Args:
            user_id: Discord user ID

        Returns:
            Dict with user info or None
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT username, display_name, is_member, updated_at
                   FROM user_cache WHERE user_id = ?""",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "user_id": user_id,
                    "username": row[0],
                    "display_name": row[1],
                    "is_member": bool(row[2]),
                    "updated_at": row[3]
                }
            return None

    def mark_user_left(self, user_id: int) -> None:
        """
        Mark user as left in cache.

        Args:
            user_id: Discord user ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE user_cache
                   SET is_member = 0, updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (user_id,)
            )
            rows_affected = cursor.rowcount
            conn.commit()
            logger.info("DB: User Marked As Left", [
                ("User ID", str(user_id)),
                ("Rows Affected", str(rows_affected)),
            ])

    def mark_user_rejoined(self, user_id: int) -> None:
        """
        Mark user as rejoined (update is_member = 1).

        Args:
            user_id: Discord user ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE user_cache
                   SET is_member = 1, updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (user_id,)
            )
            rows_affected = cursor.rowcount
            conn.commit()
            logger.info("DB: User Rejoined", [
                ("User ID", str(user_id)),
                ("Rows Affected", str(rows_affected)),
            ])

    def get_leaderboard_users_in_cache(self) -> list[int]:
        """
        Get all user IDs from leaderboard that are in the user cache.

        Returns:
            List of user IDs
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT DISTINCT u.user_id FROM users u
                   JOIN user_cache c ON u.user_id = c.user_id"""
            )
            return [row[0] for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Leaderboard Stats Operations
    # -------------------------------------------------------------------------

    def get_monthly_stats(self, year: int, month: int) -> dict:
        """
        Get community stats for a specific month.

        Args:
            year: Year (e.g., 2024)
            month: Month (1-12)

        Returns:
            Dict with total_debates, total_votes, most_active_day
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Total debates created this month
            cursor.execute(
                """SELECT COUNT(*) FROM debate_threads
                   WHERE strftime('%Y', created_at) = ?
                     AND strftime('%m', created_at) = ?""",
                (str(year), f"{month:02d}")
            )
            total_debates = cursor.fetchone()[0]

            # Total votes cast this month
            cursor.execute(
                """SELECT COUNT(*) FROM votes
                   WHERE strftime('%Y', created_at) = ?
                     AND strftime('%m', created_at) = ?""",
                (str(year), f"{month:02d}")
            )
            total_votes = cursor.fetchone()[0]

            # Most active day (by votes)
            cursor.execute(
                """SELECT strftime('%d', created_at) as day, COUNT(*) as cnt
                   FROM votes
                   WHERE strftime('%Y', created_at) = ?
                     AND strftime('%m', created_at) = ?
                   GROUP BY day
                   ORDER BY cnt DESC
                   LIMIT 1""",
                (str(year), f"{month:02d}")
            )
            row = cursor.fetchone()
            most_active_day = int(row[0]) if row else None

            return {
                "total_debates": total_debates,
                "total_votes": total_votes,
                "most_active_day": most_active_day
            }

    def get_most_active_participants(self, limit: int = 3) -> list[dict]:
        """
        Get users with highest message count in debates (all-time).

        Args:
            limit: Number of users to return

        Returns:
            List of dicts with user_id, message_count
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Use debate_participation table for accurate counts
            cursor.execute(
                """SELECT user_id, SUM(message_count) as total_messages
                   FROM debate_participation
                   GROUP BY user_id
                   ORDER BY total_messages DESC
                   LIMIT ?""",
                (limit,)
            )
            return [
                {"user_id": row[0], "message_count": row[1]}
                for row in cursor.fetchall()
            ]

    def get_most_active_debates(self, limit: int = 3) -> list[dict]:
        """
        Get debates with highest message count (all-time).

        Args:
            limit: Number of debates to return

        Returns:
            List of dicts with thread_id, message_count
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Get threads with most messages from debate_participation
            cursor.execute(
                """SELECT thread_id, SUM(message_count) as total_messages
                   FROM debate_participation
                   GROUP BY thread_id
                   ORDER BY total_messages DESC
                   LIMIT ?""",
                (limit,)
            )
            return [
                {"thread_id": row[0], "message_count": row[1]}
                for row in cursor.fetchall()
            ]

    def get_top_debate_starters(self, limit: int = 3) -> list[dict]:
        """
        Get users who started the most debates (all-time).

        Args:
            limit: Number of users to return

        Returns:
            List of dicts with user_id, debate_count
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Use debate_creators table for accurate counts
            cursor.execute(
                """SELECT user_id, COUNT(*) as debate_count
                   FROM debate_creators
                   GROUP BY user_id
                   ORDER BY debate_count DESC
                   LIMIT ?""",
                (limit,)
            )
            return [
                {"user_id": row[0], "debate_count": row[1]}
                for row in cursor.fetchall()
            ]

    def get_all_debate_thread_ids(self) -> list[int]:
        """
        Get all unique thread IDs from the database.

        Returns:
            List of thread IDs
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Get thread IDs from multiple tables
            cursor.execute(
                """SELECT DISTINCT thread_id FROM (
                       SELECT thread_id FROM debate_participation
                       UNION
                       SELECT thread_id FROM debate_creators
                       UNION
                       SELECT thread_id FROM debate_threads WHERE thread_id IS NOT NULL
                   )"""
            )
            return [row[0] for row in cursor.fetchall() if row[0] is not None]

    # -------------------------------------------------------------------------
    # Debate Participation Operations
    # -------------------------------------------------------------------------

    def increment_participation(self, thread_id: int, user_id: int) -> None:
        """
        Increment message count for a user in a debate thread.

        Args:
            thread_id: Discord thread ID
            user_id: Discord user ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO debate_participation (thread_id, user_id, message_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(thread_id, user_id) DO UPDATE SET
                       message_count = message_count + 1""",
                (thread_id, user_id)
            )
            conn.commit()

    async def increment_participation_async(self, thread_id: int, user_id: int) -> None:
        """Async wrapper for increment_participation - runs in thread pool."""
        await asyncio.to_thread(self.increment_participation, thread_id, user_id)

    def set_debate_creator(self, thread_id: int, user_id: int) -> None:
        """
        Record who created a debate thread.

        Args:
            thread_id: Discord thread ID
            user_id: Discord user ID of creator
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR IGNORE INTO debate_creators (thread_id, user_id)
                   VALUES (?, ?)""",
                (thread_id, user_id)
            )
            rows_affected = cursor.rowcount
            conn.commit()

            if rows_affected > 0:
                logger.info("DB: Debate Creator Recorded", [
                    ("Thread ID", str(thread_id)),
                    ("Creator ID", str(user_id)),
                ])

    async def set_debate_creator_async(self, thread_id: int, user_id: int) -> None:
        """Async wrapper for set_debate_creator - runs in thread pool."""
        await asyncio.to_thread(self.set_debate_creator, thread_id, user_id)

    def bulk_set_participation(self, thread_id: int, user_id: int, count: int) -> None:
        """
        Set message count for a user in a debate thread (for backfill).

        Unlike increment_participation, this sets an absolute count.
        Used during initial backfill of historical data.

        Args:
            thread_id: The debate thread ID
            user_id: The user's Discord ID
            count: Total message count to set
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO debate_participation (thread_id, user_id, message_count)
                   VALUES (?, ?, ?)
                   ON CONFLICT(thread_id, user_id) DO UPDATE SET
                       message_count = ?""",
                (thread_id, user_id, count, count)
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Case Log Operations
    # -------------------------------------------------------------------------

    def get_case_log(self, user_id: int) -> Optional[dict]:
        """
        Get case log info for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Dict with case_id, thread_id, ban_count, etc. or None if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT case_id, thread_id, ban_count, last_unban_at, created_at FROM case_logs WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "user_id": user_id,
                    "case_id": row[0],
                    "thread_id": row[1],
                    "ban_count": row[2] or 1,
                    "last_unban_at": row[3],
                    "created_at": row[4]
                }
            return None

    def create_case_log(self, user_id: int, case_id: int, thread_id: int) -> None:
        """
        Create a new case log entry.

        Args:
            user_id: Discord user ID
            case_id: The case number (4-digit)
            thread_id: The forum thread ID in mods server
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO case_logs (user_id, case_id, thread_id)
                   VALUES (?, ?, ?)""",
                (user_id, case_id, thread_id)
            )
            conn.commit()
            logger.info("DB: Case Log Created", [
                ("User ID", str(user_id)),
                ("Case ID", str(case_id)),
                ("Thread ID", str(thread_id)),
            ])

        # Audit log OUTSIDE the lock to prevent deadlock
        self.audit_log(
            action='case_create',
            target_id=user_id,
            target_type='user',
            new_value=str(case_id),
            metadata={'thread_id': thread_id}
        )

    def get_next_case_id(self) -> int:
        """
        Get the next available case ID.

        Returns:
            Next case ID (max + 1, starting at 1)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(case_id) FROM case_logs")
            row = cursor.fetchone()
            max_id = row[0] if row and row[0] else 0
            return max_id + 1

    # =========================================================================
    # Debate Counter (Atomic)
    # =========================================================================

    def get_next_debate_number(self) -> int:
        """
        Atomically increment and return the next debate number.

        Uses a single UPDATE...RETURNING pattern to prevent race conditions
        when multiple threads are created simultaneously.

        Returns:
            Next debate number (guaranteed unique)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Atomic increment: UPDATE and get new value in one operation
            cursor.execute("""
                UPDATE debate_counter
                SET counter = counter + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            """)

            # Get the new value
            cursor.execute("SELECT counter FROM debate_counter WHERE id = 1")
            row = cursor.fetchone()

            if row is None:
                # Table might be empty (shouldn't happen after migration)
                cursor.execute("INSERT INTO debate_counter (id, counter) VALUES (1, 1)")
                conn.commit()
                return 1

            conn.commit()
            return row[0]

    def set_debate_counter(self, value: int) -> None:
        """
        Set the debate counter to a specific value.

        Used during numbering reconciliation to update the counter
        after renumbering threads.

        Args:
            value: The new counter value
        """
        # Get old value and update counter within lock
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get old value for audit
            cursor.execute("SELECT counter FROM debate_counter WHERE id = 1")
            row = cursor.fetchone()
            old_value = row[0] if row else 0

            cursor.execute(
                "UPDATE debate_counter SET counter = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (value,)
            )
            conn.commit()
            logger.info("DB: Debate Counter Updated", [
                ("New Value", str(value)),
            ])

        # Audit log OUTSIDE the lock to prevent deadlock
        # (audit_log also acquires self._lock)
        self.audit_log(
            action='counter_set',
            target_type='debate_counter',
            old_value=str(old_value),
            new_value=str(value),
        )

    def get_debate_counter(self) -> int:
        """
        Get the current debate counter value.

        Returns:
            Current counter value
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT counter FROM debate_counter WHERE id = 1")
            row = cursor.fetchone()
            return row[0] if row else 0

    def increment_ban_count(self, user_id: int) -> int:
        """
        Increment the ban count for a user's case.

        Args:
            user_id: Discord user ID

        Returns:
            The new ban count
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE case_logs
                   SET ban_count = COALESCE(ban_count, 0) + 1
                   WHERE user_id = ?""",
                (user_id,)
            )
            conn.commit()

            # Get and return the new count
            cursor.execute(
                "SELECT ban_count FROM case_logs WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            new_count = row[0] if row else 1

            logger.info("DB: Ban Count Incremented", [
                ("User ID", str(user_id)),
                ("New Ban Count", str(new_count)),
            ])

            return new_count

    def update_last_unban(self, user_id: int) -> None:
        """
        Update the last_unban_at timestamp for a user's case.

        Args:
            user_id: Discord user ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE case_logs
                   SET last_unban_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (user_id,)
            )
            rows_affected = cursor.rowcount
            conn.commit()

            logger.info("DB: Last Unban Timestamp Updated", [
                ("User ID", str(user_id)),
                ("Rows Affected", str(rows_affected)),
            ])

    def get_all_case_logs(self) -> list[dict]:
        """
        Get all case logs (for /cases command and archiving).

        Returns:
            List of all case log records
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, case_id, thread_id, ban_count, last_unban_at, created_at
                   FROM case_logs
                   ORDER BY case_id DESC"""
            )
            results = [
                {
                    "user_id": row[0],
                    "case_id": row[1],
                    "thread_id": row[2],
                    "ban_count": row[3] or 1,
                    "last_unban_at": row[4],
                    "created_at": row[5]
                }
                for row in cursor.fetchall()
            ]

            logger.info("DB: Retrieved All Case Logs", [
                ("Total Cases", str(len(results))),
            ])

            return results

    def search_case_logs(self, query: str) -> list[dict]:
        """
        Search case logs by user ID or case ID.

        Args:
            query: Search query (user ID or case ID)

        Returns:
            List of matching case log records
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Try to parse as integer for exact ID match
            try:
                query_int = int(query)
                cursor.execute(
                    """SELECT user_id, case_id, thread_id, ban_count, last_unban_at, created_at
                       FROM case_logs
                       WHERE user_id = ? OR case_id = ?
                       ORDER BY case_id DESC""",
                    (query_int, query_int)
                )
            except ValueError:
                # Not a number, return empty list
                logger.info("DB: Case Log Search - Invalid Query", [
                    ("Query", query),
                    ("Reason", "Not a valid number"),
                ])
                return []

            results = [
                {
                    "user_id": row[0],
                    "case_id": row[1],
                    "thread_id": row[2],
                    "ban_count": row[3] or 1,
                    "last_unban_at": row[4],
                    "created_at": row[5]
                }
                for row in cursor.fetchall()
            ]

            logger.info("DB: Case Log Search Complete", [
                ("Query", query),
                ("Results Found", str(len(results))),
            ])

            return results

    # -------------------------------------------------------------------------
    # Linked Accounts (Alt Account Tracking)
    # -------------------------------------------------------------------------

    def link_accounts(
        self,
        main_user_id: int,
        alt_user_id: int,
        linked_by: int,
        reason: Optional[str] = None
    ) -> bool:
        """
        Link an alt account to a main account.

        Args:
            main_user_id: The main account's user ID
            alt_user_id: The alt account's user ID
            linked_by: Moderator who confirmed the link
            reason: Optional reason/evidence for the link

        Returns:
            True if linked successfully, False if already linked
        """
        success = False
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """INSERT INTO linked_accounts (main_user_id, alt_user_id, linked_by, reason)
                       VALUES (?, ?, ?, ?)""",
                    (main_user_id, alt_user_id, linked_by, reason)
                )
                conn.commit()
                success = True

                logger.info("DB: Accounts Linked", [
                    ("Main Account", str(main_user_id)),
                    ("Alt Account", str(alt_user_id)),
                    ("Linked By", str(linked_by)),
                ])

            except sqlite3.IntegrityError:
                # Alt already linked to someone
                logger.warning("DB: Alt Account Already Linked", [
                    ("Alt Account", str(alt_user_id)),
                ])

        # Audit log OUTSIDE the lock to prevent deadlock
        if success:
            self.audit_log(
                action='account_link',
                actor_id=linked_by,
                target_id=alt_user_id,
                target_type='user',
                new_value=str(main_user_id),
                metadata={'reason': reason}
            )
        return success

    def unlink_account(self, alt_user_id: int) -> bool:
        """
        Unlink an alt account.

        Args:
            alt_user_id: The alt account's user ID

        Returns:
            True if unlinked, False if not found
        """
        main_user_id = None
        deleted = False
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get main account before deleting for audit
            cursor.execute(
                "SELECT main_user_id FROM linked_accounts WHERE alt_user_id = ?",
                (alt_user_id,)
            )
            row = cursor.fetchone()
            main_user_id = row[0] if row else None

            cursor.execute(
                "DELETE FROM linked_accounts WHERE alt_user_id = ?",
                (alt_user_id,)
            )
            deleted = cursor.rowcount > 0
            conn.commit()

            if deleted:
                logger.info("DB: Account Unlinked", [
                    ("Alt Account", str(alt_user_id)),
                ])

        # Audit log OUTSIDE the lock to prevent deadlock
        if deleted:
            self.audit_log(
                action='account_unlink',
                target_id=alt_user_id,
                target_type='user',
                old_value=str(main_user_id) if main_user_id else None,
            )

        return deleted

    def get_linked_accounts(self, user_id: int) -> list[dict]:
        """
        Get all accounts linked to a user (whether they're the main or an alt).

        Args:
            user_id: User ID to check

        Returns:
            List of linked account records
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Check if user_id is a main account
            cursor.execute(
                """SELECT alt_user_id, linked_by, reason, created_at
                   FROM linked_accounts
                   WHERE main_user_id = ?""",
                (user_id,)
            )
            alts = [
                {
                    "user_id": row[0],
                    "is_alt": True,
                    "linked_by": row[1],
                    "reason": row[2],
                    "created_at": row[3]
                }
                for row in cursor.fetchall()
            ]

            # Check if user_id is an alt account
            cursor.execute(
                """SELECT main_user_id, linked_by, reason, created_at
                   FROM linked_accounts
                   WHERE alt_user_id = ?""",
                (user_id,)
            )
            row = cursor.fetchone()
            main_account = None
            if row:
                main_account = {
                    "user_id": row[0],
                    "is_alt": False,  # This is the main account
                    "linked_by": row[1],
                    "reason": row[2],
                    "created_at": row[3]
                }

            # Combine results
            linked = []
            if main_account:
                linked.append(main_account)
                # Also get any other alts of the main account
                cursor.execute(
                    """SELECT alt_user_id, linked_by, reason, created_at
                       FROM linked_accounts
                       WHERE main_user_id = ? AND alt_user_id != ?""",
                    (main_account["user_id"], user_id)
                )
                for r in cursor.fetchall():
                    linked.append({
                        "user_id": r[0],
                        "is_alt": True,
                        "linked_by": r[1],
                        "reason": r[2],
                        "created_at": r[3]
                    })
            else:
                linked.extend(alts)

            return linked

    def get_main_account(self, alt_user_id: int) -> Optional[int]:
        """
        Get the main account for an alt.

        Args:
            alt_user_id: The alt account's user ID

        Returns:
            Main account user ID, or None if not an alt
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT main_user_id FROM linked_accounts WHERE alt_user_id = ?",
                (alt_user_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    # -------------------------------------------------------------------------
    # Orphan Vote Cleanup Operations
    # -------------------------------------------------------------------------

    def get_all_voted_message_ids(self) -> set[int]:
        """
        Get all unique message IDs that have votes in the database.

        Returns:
            Set of message IDs with votes
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT DISTINCT message_id FROM votes")
                return {row[0] for row in cursor.fetchall()}
            finally:
                cursor.close()

    def cleanup_orphaned_votes(self, orphan_message_ids: set[int]) -> dict:
        """
        Remove votes for messages that no longer exist and reverse karma effects.

        This properly decrements the karma for each author whose message votes
        are being removed, maintaining karma consistency.

        Args:
            orphan_message_ids: Set of message IDs that no longer exist

        Returns:
            Dict with cleanup stats: votes_deleted, users_affected, errors
        """
        stats = {
            "votes_deleted": 0,
            "users_affected": 0,
            "karma_reversed": 0,
            "errors": 0,
        }

        if not orphan_message_ids:
            return stats

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("BEGIN IMMEDIATE")

                affected_authors: set[int] = set()

                # Process each orphaned message
                for message_id in orphan_message_ids:
                    try:
                        # Get all votes for this message before deleting
                        cursor.execute(
                            """SELECT author_id, vote_type, COUNT(*) as cnt
                               FROM votes
                               WHERE message_id = ?
                               GROUP BY author_id, vote_type""",
                            (message_id,)
                        )
                        vote_groups = cursor.fetchall()

                        # Reverse karma for each author/vote_type combo
                        for author_id, vote_type, count in vote_groups:
                            karma_reversal = -vote_type * count  # Negate the karma
                            counter_field = "upvotes_received" if vote_type > 0 else "downvotes_received"

                            cursor.execute(
                                f"""UPDATE users SET
                                    total_karma = total_karma + ?,
                                    {counter_field} = MAX(0, {counter_field} - ?)
                                    WHERE user_id = ?""",
                                (karma_reversal, count, author_id)
                            )
                            affected_authors.add(author_id)
                            stats["karma_reversed"] += abs(karma_reversal)

                        # Delete votes for this message
                        cursor.execute(
                            "DELETE FROM votes WHERE message_id = ?",
                            (message_id,)
                        )
                        stats["votes_deleted"] += cursor.rowcount

                    except Exception as e:
                        logger.error("Error Cleaning Up Votes For Message", [
                            ("Message ID", str(message_id)),
                            ("Error", str(e)),
                        ])
                        stats["errors"] += 1

                stats["users_affected"] = len(affected_authors)
                conn.commit()

                if stats["votes_deleted"] > 0:
                    logger.success("DB: Orphan Votes Cleaned Up", [
                        ("Votes Deleted", str(stats["votes_deleted"])),
                        ("Users Affected", str(stats["users_affected"])),
                        ("Karma Reversed", str(stats["karma_reversed"])),
                        ("Errors", str(stats["errors"])),
                    ])

                return stats

            except sqlite3.Error as e:
                conn.rollback()
                logger.error("Orphan Vote Cleanup Failed - Rolled Back", [
                    ("Error", str(e)),
                ])
                stats["errors"] += 1
                return stats

    def get_vote_count(self) -> int:
        """
        Get total number of votes in the database.

        Returns:
            Total vote count
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM votes")
            return cursor.fetchone()[0]

    # -------------------------------------------------------------------------
    # Audit Log Operations
    # -------------------------------------------------------------------------

    def audit_log(
        self,
        action: str,
        actor_id: Optional[int] = None,
        target_id: Optional[int] = None,
        target_type: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Record an action in the audit log for accountability.

        Args:
            action: Action type (e.g., 'ban_add', 'vote_remove', 'karma_adjust')
            actor_id: User ID who performed the action (None for system actions)
            target_id: ID of the affected entity (user_id, thread_id, etc.)
            target_type: Type of target ('user', 'thread', 'message', etc.)
            old_value: Previous value (for changes)
            new_value: New value (for changes)
            metadata: Additional context as dict (will be JSON serialized)

        DESIGN: This method is intentionally fire-and-forget. Audit logging
        should never block or fail the primary operation. Errors are logged
        but not raised.
        """
        try:
            import json
            metadata_json = json.dumps(metadata) if metadata else None

            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO audit_log
                       (action, actor_id, target_id, target_type, old_value, new_value, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (action, actor_id, target_id, target_type, old_value, new_value, metadata_json)
                )
                conn.commit()
        except Exception as e:
            # Never fail the primary operation due to audit logging
            logger.warning("Audit Log Failed", [
                ("Action", action),
                ("Error", str(e)),
            ])

    def get_audit_log(
        self,
        action: Optional[str] = None,
        actor_id: Optional[int] = None,
        target_id: Optional[int] = None,
        target_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Query the audit log with optional filters.

        Args:
            action: Filter by action type
            actor_id: Filter by who performed the action
            target_id: Filter by affected entity ID
            target_type: Filter by target type
            limit: Maximum records to return
            offset: Number of records to skip

        Returns:
            List of audit log entries as dicts
        """
        import json

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Build query with optional filters
            query = "SELECT id, action, actor_id, target_id, target_type, old_value, new_value, metadata, created_at FROM audit_log WHERE 1=1"
            params = []

            if action:
                query += " AND action = ?"
                params.append(action)
            if actor_id is not None:
                query += " AND actor_id = ?"
                params.append(actor_id)
            if target_id is not None:
                query += " AND target_id = ?"
                params.append(target_id)
            if target_type:
                query += " AND target_type = ?"
                params.append(target_type)

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)

            results = []
            for row in cursor.fetchall():
                metadata_parsed = None
                if row[7]:
                    try:
                        metadata_parsed = json.loads(row[7])
                    except json.JSONDecodeError:
                        metadata_parsed = row[7]

                results.append({
                    "id": row[0],
                    "action": row[1],
                    "actor_id": row[2],
                    "target_id": row[3],
                    "target_type": row[4],
                    "old_value": row[5],
                    "new_value": row[6],
                    "metadata": metadata_parsed,
                    "created_at": row[8],
                })

            return results

    def get_user_audit_history(self, user_id: int, limit: int = 20) -> list[dict]:
        """
        Get all audit entries involving a user (as actor or target).

        Args:
            user_id: Discord user ID
            limit: Maximum records to return

        Returns:
            List of audit log entries
        """
        import json

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """SELECT id, action, actor_id, target_id, target_type, old_value, new_value, metadata, created_at
                   FROM audit_log
                   WHERE actor_id = ? OR (target_id = ? AND target_type = 'user')
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, user_id, limit)
            )

            results = []
            for row in cursor.fetchall():
                metadata_parsed = None
                if row[7]:
                    try:
                        metadata_parsed = json.loads(row[7])
                    except json.JSONDecodeError:
                        metadata_parsed = row[7]

                results.append({
                    "id": row[0],
                    "action": row[1],
                    "actor_id": row[2],
                    "target_id": row[3],
                    "target_type": row[4],
                    "old_value": row[5],
                    "new_value": row[6],
                    "metadata": metadata_parsed,
                    "created_at": row[8],
                })

            return results

    def get_audit_stats(self, days: int = 7) -> dict:
        """
        Get audit log statistics for the specified time period.

        Args:
            days: Number of days to look back

        Returns:
            Dict with action counts and summary stats
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get counts by action type
            cursor.execute(
                """SELECT action, COUNT(*) as count
                   FROM audit_log
                   WHERE created_at >= datetime('now', ?)
                   GROUP BY action
                   ORDER BY count DESC""",
                (f'-{days} days',)
            )
            action_counts = {row[0]: row[1] for row in cursor.fetchall()}

            # Get total count
            cursor.execute(
                """SELECT COUNT(*) FROM audit_log
                   WHERE created_at >= datetime('now', ?)""",
                (f'-{days} days',)
            )
            total_count = cursor.fetchone()[0]

            # Get unique actors
            cursor.execute(
                """SELECT COUNT(DISTINCT actor_id) FROM audit_log
                   WHERE created_at >= datetime('now', ?) AND actor_id IS NOT NULL""",
                (f'-{days} days',)
            )
            unique_actors = cursor.fetchone()[0]

            return {
                "total_actions": total_count,
                "unique_actors": unique_actors,
                "action_counts": action_counts,
                "period_days": days,
            }

    def cleanup_old_audit_logs(self, days_to_keep: int = 90) -> int:
        """
        Remove audit log entries older than specified days.

        Args:
            days_to_keep: Number of days of logs to retain

        Returns:
            Number of records deleted
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """DELETE FROM audit_log
                   WHERE created_at < datetime('now', ?)""",
                (f'-{days_to_keep} days',)
            )
            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info("Audit Log Cleanup", [
                    ("Deleted", str(deleted)),
                    ("Retained Days", str(days_to_keep)),
                ])

            return deleted

    # -------------------------------------------------------------------------
    # Appeal Operations
    # -------------------------------------------------------------------------

    def create_appeal(
        self,
        user_id: int,
        action_type: str,
        action_id: int,
        reason: str,
        additional_context: Optional[str] = None,
    ) -> Optional[int]:
        """
        Create a new appeal for a disallow or thread close action.

        Args:
            user_id: Discord user ID of the appealing user
            action_type: Type of action being appealed ('disallow' or 'close')
            action_id: ID of the action (ban row ID for disallow, thread ID for close)
            reason: User's reason for the appeal
            additional_context: Optional additional context from user

        Returns:
            Appeal ID if created, None if already exists

        DESIGN: UNIQUE constraint prevents duplicate appeals for the same action.
        """
        appeal_id = None
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """INSERT INTO appeals (user_id, action_type, action_id, reason, additional_context)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, action_type, action_id, reason, additional_context)
                )
                conn.commit()
                appeal_id = cursor.lastrowid

                logger.info("DB: Appeal Created", [
                    ("Appeal ID", str(appeal_id)),
                    ("User ID", str(user_id)),
                    ("Action Type", action_type),
                    ("Action ID", str(action_id)),
                ])

            except sqlite3.IntegrityError:
                # User already appealed this action
                logger.info("DB: Duplicate Appeal Attempt", [
                    ("User ID", str(user_id)),
                    ("Action Type", action_type),
                    ("Action ID", str(action_id)),
                ])
                return None

        # Audit log OUTSIDE the lock to prevent deadlock
        if appeal_id:
            self.audit_log(
                action='appeal_create',
                actor_id=user_id,
                target_id=action_id,
                target_type=action_type,
                metadata={
                    'appeal_id': appeal_id,
                    'reason': reason[:100] if reason else None,
                }
            )

        return appeal_id

    def get_appeal(self, appeal_id: int) -> Optional[dict]:
        """
        Get an appeal by its ID.

        Args:
            appeal_id: The appeal ID

        Returns:
            Dict with appeal data or None if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, action_type, action_id, reason, additional_context,
                          status, reviewed_by, reviewed_at, created_at, denial_reason, case_message_id
                   FROM appeals WHERE id = ?""",
                (appeal_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "action_type": row[2],
                    "action_id": row[3],
                    "reason": row[4],
                    "additional_context": row[5],
                    "status": row[6],
                    "reviewed_by": row[7],
                    "reviewed_at": row[8],
                    "created_at": row[9],
                    "denial_reason": row[10],
                    "case_message_id": row[11],
                }
            return None

    def get_appeal_by_action(
        self,
        user_id: int,
        action_type: str,
        action_id: int,
    ) -> Optional[dict]:
        """
        Get an appeal by user and action details.

        Args:
            user_id: Discord user ID
            action_type: Type of action ('disallow' or 'close')
            action_id: ID of the action

        Returns:
            Dict with appeal data or None if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, action_type, action_id, reason, additional_context,
                          status, reviewed_by, reviewed_at, created_at
                   FROM appeals
                   WHERE user_id = ? AND action_type = ? AND action_id = ?""",
                (user_id, action_type, action_id)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "action_type": row[2],
                    "action_id": row[3],
                    "reason": row[4],
                    "additional_context": row[5],
                    "status": row[6],
                    "reviewed_by": row[7],
                    "reviewed_at": row[8],
                    "created_at": row[9],
                }
            return None

    def update_appeal_status(
        self,
        appeal_id: int,
        status: str,
        reviewed_by: int,
        denial_reason: Optional[str] = None,
    ) -> bool:
        """
        Update an appeal's status (approve or deny).

        Args:
            appeal_id: The appeal ID
            status: New status ('approved' or 'denied')
            reviewed_by: Moderator user ID who reviewed
            denial_reason: Optional reason for denial (only used when status='denied')

        Returns:
            True if updated, False if appeal not found
        """
        old_status = None
        success = False

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get old status for audit
            cursor.execute("SELECT status FROM appeals WHERE id = ?", (appeal_id,))
            row = cursor.fetchone()
            if not row:
                return False
            old_status = row[0]

            if denial_reason and status == "denied":
                cursor.execute(
                    """UPDATE appeals
                       SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, denial_reason = ?
                       WHERE id = ?""",
                    (status, reviewed_by, denial_reason, appeal_id)
                )
            else:
                cursor.execute(
                    """UPDATE appeals
                       SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (status, reviewed_by, appeal_id)
                )
            success = cursor.rowcount > 0
            conn.commit()

            if success:
                logger.info("DB: Appeal Status Updated", [
                    ("Appeal ID", str(appeal_id)),
                    ("Status", status),
                    ("Reviewed By", str(reviewed_by)),
                ])

        # Audit log OUTSIDE the lock to prevent deadlock
        if success:
            self.audit_log(
                action='appeal_review',
                actor_id=reviewed_by,
                target_id=appeal_id,
                target_type='appeal',
                old_value=old_status,
                new_value=status,
            )

        return success

    def has_appeal(
        self,
        user_id: int,
        action_type: str,
        action_id: int,
    ) -> bool:
        """
        Check if an appeal already exists for this action.

        Args:
            user_id: Discord user ID
            action_type: Type of action ('disallow' or 'close')
            action_id: ID of the action

        Returns:
            True if appeal exists, False otherwise
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT 1 FROM appeals
                   WHERE user_id = ? AND action_type = ? AND action_id = ?""",
                (user_id, action_type, action_id)
            )
            return cursor.fetchone() is not None

    def get_pending_appeals(self, limit: int = 50) -> list[dict]:
        """
        Get all pending appeals for moderation review.

        Args:
            limit: Maximum number of appeals to return

        Returns:
            List of pending appeal records
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, action_type, action_id, reason, additional_context,
                          status, reviewed_by, reviewed_at, created_at
                   FROM appeals
                   WHERE status = 'pending'
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (limit,)
            )
            return [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "action_type": row[2],
                    "action_id": row[3],
                    "reason": row[4],
                    "additional_context": row[5],
                    "status": row[6],
                    "reviewed_by": row[7],
                    "reviewed_at": row[8],
                    "created_at": row[9],
                }
                for row in cursor.fetchall()
            ]

    def get_user_appeals(self, user_id: int) -> list[dict]:
        """
        Get all appeals submitted by a user.

        Args:
            user_id: Discord user ID

        Returns:
            List of appeal records for the user
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, action_type, action_id, reason, additional_context,
                          status, reviewed_by, reviewed_at, created_at
                   FROM appeals
                   WHERE user_id = ?
                   ORDER BY created_at DESC""",
                (user_id,)
            )
            return [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "action_type": row[2],
                    "action_id": row[3],
                    "reason": row[4],
                    "additional_context": row[5],
                    "status": row[6],
                    "reviewed_by": row[7],
                    "reviewed_at": row[8],
                    "created_at": row[9],
                }
                for row in cursor.fetchall()
            ]

    def set_appeal_case_message_id(self, appeal_id: int, message_id: int) -> bool:
        """
        Store the case thread message ID for an appeal embed.

        This allows us to edit the appeal embed later when it's approved/denied.

        Args:
            appeal_id: The appeal ID
            message_id: The Discord message ID of the appeal embed in case thread

        Returns:
            True if updated, False if appeal not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE appeals SET case_message_id = ? WHERE id = ?",
                (message_id, appeal_id)
            )
            conn.commit()
            return cursor.rowcount > 0


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DebatesDatabase", "UserKarma"]
