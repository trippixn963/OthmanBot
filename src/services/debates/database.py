"""
Othman Discord Bot - Debates Database
======================================

SQLite database operations for karma tracking and debate statistics.

DATABASE SCHEMA:
================
┌─────────────────────────────────────────────────────────────────┐
│                         votes                                    │
├─────────────────────────────────────────────────────────────────┤
│ voter_id (INT)     - User who voted                             │
│ message_id (INT)   - Message that was voted on                  │
│ author_id (INT)    - Author of the message (receives karma)     │
│ vote_value (INT)   - +1 for upvote, -1 for downvote            │
│ created_at (TEXT)  - Timestamp of vote                          │
│ PRIMARY KEY: (voter_id, message_id) - One vote per user/message │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    debate_participation                          │
├─────────────────────────────────────────────────────────────────┤
│ thread_id (INT)    - Debate thread ID                           │
│ user_id (INT)      - User who participated                      │
│ message_count (INT)- Number of messages in thread               │
│ updated_at (TEXT)  - Last update timestamp                      │
│ PRIMARY KEY: (thread_id, user_id)                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     debate_creators                              │
├─────────────────────────────────────────────────────────────────┤
│ thread_id (INT)    - Debate thread ID (PRIMARY KEY)             │
│ user_id (INT)      - User who created the debate                │
│ created_at (TEXT)  - When the debate was created                │
└─────────────────────────────────────────────────────────────────┘

DESIGN DECISIONS:
=================
1. WAL MODE: Write-Ahead Logging for better read/write concurrency
   - Readers don't block writers
   - Writers don't block readers
   - Perfect for Discord bot with frequent reads

2. THREAD SAFETY: Uses threading.Lock() for all operations
   - check_same_thread=False allows multi-thread access
   - Lock prevents race conditions

3. PERSISTENT CONNECTION: Single connection reused for all operations
   - Avoids connection overhead
   - Auto-reconnects if connection drops

4. KARMA CALCULATION: SUM(vote_value) WHERE author_id = user_id
   - Upvotes (+1) and downvotes (-1) are summed
   - Net karma can be negative

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
import threading
import time
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

    def __init__(self, db_path: str = "data/debates.db") -> None:
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

    # Current schema version - increment when adding migrations
    SCHEMA_VERSION = 3

    # Valid table names for SQL injection prevention
    VALID_TABLES = frozenset({
        'votes', 'users', 'debate_threads', 'debate_bans',
        'debate_participation', 'debate_creators', 'case_logs',
        'analytics_messages', 'schema_version'
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
                return True
            except sqlite3.IntegrityError as e:
                # User already banned (unique constraint violation)
                logger.debug("Ban Already Exists (Integrity Constraint)", [
                    ("User ID", str(user_id)),
                    ("Thread ID", str(thread_id) if thread_id else "all"),
                    ("Error", str(e)),
                ])
                return False
            except sqlite3.OperationalError as e:
                logger.warning("Database Operational Error In add_debate_ban", [
                    ("User ID", str(user_id)),
                    ("Thread ID", str(thread_id) if thread_id else "all"),
                    ("Error", str(e)),
                ])
                return False

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
            conn.commit()
            return cursor.rowcount > 0

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

    def get_expired_bans(self) -> list[dict]:
        """
        Get all expired bans that need to be removed.

        Returns:
            List of expired ban records
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, thread_id, expires_at
                   FROM debate_bans
                   WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"""
            )
            return [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "thread_id": row[2],
                    "expires_at": row[3]
                }
                for row in cursor.fetchall()
            ]

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
            cursor.execute("DELETE FROM month_embeds")
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


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DebatesDatabase", "UserKarma"]
