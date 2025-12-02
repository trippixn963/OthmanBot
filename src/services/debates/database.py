"""
Othman Discord Bot - Debates Database
======================================

SQLite database operations for karma tracking.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
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
    """SQLite database for debate karma tracking."""

    def __init__(self, db_path: str = "data/debates.db") -> None:
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def _init_database(self) -> None:
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

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

            # Indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_votes_message
                ON votes(message_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_votes_author
                ON votes(author_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_karma
                ON users(total_karma DESC)
            """)

            # Thread hostility tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thread_hostility (
                    thread_id INTEGER PRIMARY KEY,
                    cumulative_score REAL DEFAULT 0,
                    message_count INTEGER DEFAULT 0,
                    warning_sent INTEGER DEFAULT 0,
                    last_warning_at TIMESTAMP,
                    locked_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Message hostility scores (for audit)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS message_hostility (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id INTEGER NOT NULL,
                    message_id INTEGER UNIQUE,
                    user_id INTEGER NOT NULL,
                    score REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Index for hostility lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_hostility_thread
                ON message_hostility(thread_id)
            """)

            # Debate bans table - users banned from specific threads or all debates
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS debate_bans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    banned_by INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, thread_id)
                )
            """)

            # Index for ban lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_bans_user
                ON debate_bans(user_id)
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

            conn.commit()
            logger.info("🗳️ Debates database initialized")

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
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check existing vote
            cursor.execute(
                "SELECT vote_type FROM votes WHERE voter_id = ? AND message_id = ?",
                (voter_id, message_id)
            )
            existing = cursor.fetchone()

            if existing:
                old_vote = existing[0]
                if old_vote == vote_type:
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
            return True

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
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get existing vote
            cursor.execute(
                """SELECT author_id, vote_type FROM votes
                   WHERE voter_id = ? AND message_id = ?""",
                (voter_id, message_id)
            )
            existing = cursor.fetchone()

            if not existing:
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
            return author_id

    def get_message_votes(self, message_id: int) -> dict[int, int]:
        """
        Get all votes for a specific message.

        Args:
            message_id: Discord message ID

        Returns:
            Dict of voter_id -> vote_type (+1 or -1)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT voter_id, vote_type FROM votes WHERE message_id = ?",
                (message_id,)
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, total_karma, upvotes_received, downvotes_received
                   FROM users WHERE user_id = ?""",
                (user_id,)
            )
            row = cursor.fetchone()

            if row:
                return UserKarma(*row)
            return UserKarma(user_id, 0, 0, 0)

    def get_leaderboard(self, limit: int = 10) -> list[UserKarma]:
        """
        Get top users by karma.

        Args:
            limit: Number of users to return

        Returns:
            List of UserKarma sorted by total_karma desc
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, total_karma, upvotes_received, downvotes_received
                   FROM users
                   ORDER BY total_karma DESC
                   LIMIT ?""",
                (limit,)
            )
            return [UserKarma(*row) for row in cursor.fetchall()]

    def get_user_rank(self, user_id: int) -> int:
        """
        Get user's rank on leaderboard.

        Args:
            user_id: User ID

        Returns:
            Rank (1-indexed), or 0 if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*) + 1 FROM users
                   WHERE total_karma > (
                       SELECT COALESCE(total_karma, 0) FROM users WHERE user_id = ?
                   )""",
                (user_id,)
            )
            return cursor.fetchone()[0]

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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO debate_threads (thread_id, analytics_message_id)
                   VALUES (?, ?)""",
                (thread_id, message_id)
            )
            conn.commit()

    def get_analytics_message(self, thread_id: int) -> Optional[int]:
        """
        Get the analytics message ID for a debate thread.

        Args:
            thread_id: Discord thread ID

        Returns:
            Message ID if found, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT analytics_message_id FROM debate_threads WHERE thread_id = ?",
                (thread_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None


    # -------------------------------------------------------------------------
    # Hostility Operations
    # -------------------------------------------------------------------------

    def get_thread_hostility(self, thread_id: int) -> Optional[dict]:
        """
        Get hostility data for a thread.

        Args:
            thread_id: Discord thread ID

        Returns:
            Dict with hostility data or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT cumulative_score, message_count, warning_sent,
                          last_warning_at, locked_at, updated_at
                   FROM thread_hostility WHERE thread_id = ?""",
                (thread_id,)
            )
            row = cursor.fetchone()

            if row:
                return {
                    "cumulative_score": row[0],
                    "message_count": row[1],
                    "warning_sent": bool(row[2]),
                    "last_warning_at": row[3],
                    "locked_at": row[4],
                    "updated_at": row[5]
                }
            return None

    def update_thread_hostility(
        self,
        thread_id: int,
        cumulative_score: float,
        message_count: int
    ) -> None:
        """
        Update hostility data for a thread.

        Args:
            thread_id: Discord thread ID
            cumulative_score: Current cumulative score
            message_count: Total messages analyzed
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO thread_hostility (thread_id, cumulative_score, message_count, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(thread_id) DO UPDATE SET
                       cumulative_score = excluded.cumulative_score,
                       message_count = excluded.message_count,
                       updated_at = CURRENT_TIMESTAMP""",
                (thread_id, cumulative_score, message_count)
            )
            conn.commit()

    def mark_warning_sent(self, thread_id: int) -> None:
        """
        Mark that a warning was sent for a thread.

        Args:
            thread_id: Discord thread ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE thread_hostility
                   SET warning_sent = 1, last_warning_at = CURRENT_TIMESTAMP
                   WHERE thread_id = ?""",
                (thread_id,)
            )
            conn.commit()

    def mark_thread_locked(self, thread_id: int) -> None:
        """
        Mark that a thread was locked due to hostility.

        Args:
            thread_id: Discord thread ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE thread_hostility
                   SET locked_at = CURRENT_TIMESTAMP
                   WHERE thread_id = ?""",
                (thread_id,)
            )
            conn.commit()

    def add_message_hostility(
        self,
        thread_id: int,
        message_id: int,
        user_id: int,
        score: float
    ) -> None:
        """
        Log hostility score for a message.

        Args:
            thread_id: Discord thread ID
            message_id: Discord message ID
            user_id: Author ID
            score: Hostility score
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO message_hostility
                   (thread_id, message_id, user_id, score)
                   VALUES (?, ?, ?, ?)""",
                (thread_id, message_id, user_id, score)
            )
            conn.commit()

    def get_top_hostile_user(self, thread_id: int) -> Optional[int]:
        """
        Get the user with highest cumulative hostility score in a thread.

        Args:
            thread_id: Discord thread ID

        Returns:
            User ID of most hostile user, or None if no data
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, SUM(score) as total_score
                   FROM message_hostility
                   WHERE thread_id = ?
                   GROUP BY user_id
                   ORDER BY total_score DESC
                   LIMIT 1""",
                (thread_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    # -------------------------------------------------------------------------
    # Debate Ban Operations
    # -------------------------------------------------------------------------

    def add_debate_ban(
        self,
        user_id: int,
        thread_id: Optional[int],
        banned_by: int,
        reason: Optional[str] = None
    ) -> bool:
        """
        Ban a user from a specific thread or all debates.

        Args:
            user_id: User to ban
            thread_id: Thread ID to ban from (None = all debates)
            banned_by: User ID who issued the ban
            reason: Optional reason for the ban

        Returns:
            True if ban was added, False if already exists
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO debate_bans (user_id, thread_id, banned_by, reason)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, thread_id, banned_by, reason)
                )
                conn.commit()
                return True
            except Exception:
                return False

    def remove_debate_ban(self, user_id: int, thread_id: Optional[int]) -> bool:
        """
        Remove a debate ban.

        Args:
            user_id: User to unban
            thread_id: Thread ID (None = all debates ban)

        Returns:
            True if ban was removed, False if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if thread_id is None:
                cursor.execute(
                    "DELETE FROM debate_bans WHERE user_id = ? AND thread_id IS NULL",
                    (user_id,)
                )
            else:
                cursor.execute(
                    "DELETE FROM debate_bans WHERE user_id = ? AND thread_id = ?",
                    (user_id, thread_id)
                )
            conn.commit()
            return cursor.rowcount > 0

    def is_user_banned(self, user_id: int, thread_id: int) -> bool:
        """
        Check if user is banned from a specific thread.

        Args:
            user_id: User to check
            thread_id: Thread ID to check

        Returns:
            True if user is banned from this thread or all debates
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check for specific thread ban OR global debates ban (thread_id IS NULL)
            cursor.execute(
                """SELECT 1 FROM debate_bans
                   WHERE user_id = ? AND (thread_id = ? OR thread_id IS NULL)
                   LIMIT 1""",
                (user_id, thread_id)
            )
            return cursor.fetchone() is not None

    def get_user_bans(self, user_id: int) -> list[dict]:
        """
        Get all bans for a user.

        Args:
            user_id: User ID

        Returns:
            List of ban records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT thread_id, banned_by, reason, created_at
                   FROM debate_bans WHERE user_id = ?""",
                (user_id,)
            )
            return [
                {
                    "thread_id": row[0],
                    "banned_by": row[1],
                    "reason": row[2],
                    "created_at": row[3]
                }
                for row in cursor.fetchall()
            ]

    def get_all_banned_users(self) -> list[int]:
        """
        Get all unique user IDs that have active bans.

        Returns:
            List of user IDs with active bans
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT user_id FROM debate_bans")
            return [row[0] for row in cursor.fetchall()]

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
        - Hostility records

        Args:
            user_id: User ID to purge

        Returns:
            Dict with counts of deleted records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            deleted = {}

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

            # Delete hostility records
            cursor.execute("DELETE FROM message_hostility WHERE user_id = ?", (user_id,))
            deleted["hostility"] = cursor.rowcount

            conn.commit()
            return deleted

    # -------------------------------------------------------------------------
    # Leaderboard Thread Operations
    # -------------------------------------------------------------------------

    def get_leaderboard_thread(self) -> Optional[int]:
        """
        Get saved leaderboard thread ID.

        Returns:
            Thread ID if found, None otherwise
        """
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO leaderboard_thread (id, thread_id)
                   VALUES (1, ?)""",
                (thread_id,)
            )
            conn.commit()

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
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT year, month, message_id FROM leaderboard_embeds
                   ORDER BY year DESC, month DESC"""
            )
            return [
                {"year": row[0], "month": row[1], "message_id": row[2]}
                for row in cursor.fetchall()
            ]

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
        with self._get_connection() as conn:
            cursor = conn.cursor()
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

    def get_cached_user(self, user_id: int) -> Optional[dict]:
        """
        Get cached user info.

        Args:
            user_id: Discord user ID

        Returns:
            Dict with user info or None
        """
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE user_cache
                   SET is_member = 0, updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (user_id,)
            )
            conn.commit()

    def mark_user_rejoined(self, user_id: int) -> None:
        """
        Mark user as rejoined (update is_member = 1).

        Args:
            user_id: Discord user ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE user_cache
                   SET is_member = 1, updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (user_id,)
            )
            conn.commit()

    def get_leaderboard_users_in_cache(self) -> list[int]:
        """
        Get all user IDs from leaderboard that are in the user cache.

        Returns:
            List of user IDs
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT DISTINCT u.user_id FROM users u
                   JOIN user_cache c ON u.user_id = c.user_id"""
            )
            return [row[0] for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Active Debates Operations
    # -------------------------------------------------------------------------

    def get_most_active_debates(self, limit: int = 3) -> list[dict]:
        """
        Get the most active debate threads by message count.

        Args:
            limit: Number of threads to return

        Returns:
            List of dicts with thread_id, message_count
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT thread_id, message_count
                   FROM thread_hostility
                   WHERE message_count > 0
                   ORDER BY message_count DESC
                   LIMIT ?""",
                (limit,)
            )
            return [
                {"thread_id": row[0], "message_count": row[1]}
                for row in cursor.fetchall()
            ]

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
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, COUNT(*) as msg_count
                   FROM message_hostility
                   GROUP BY user_id
                   ORDER BY msg_count DESC
                   LIMIT ?""",
                (limit,)
            )
            return [
                {"user_id": row[0], "message_count": row[1]}
                for row in cursor.fetchall()
            ]

    def get_top_debate_starters(self, limit: int = 3) -> list[dict]:
        """
        Get users who started the most debates (all-time).
        Uses the first message in each thread to determine the starter.

        Args:
            limit: Number of users to return

        Returns:
            List of dicts with user_id, debate_count
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Get the first message (lowest message_id) per thread as the starter
            cursor.execute(
                """SELECT user_id, COUNT(DISTINCT thread_id) as debate_count
                   FROM (
                       SELECT thread_id, user_id
                       FROM message_hostility
                       WHERE message_id = (
                           SELECT MIN(message_id) FROM message_hostility m2
                           WHERE m2.thread_id = message_hostility.thread_id
                       )
                   )
                   GROUP BY user_id
                   ORDER BY debate_count DESC
                   LIMIT ?""",
                (limit,)
            )
            return [
                {"user_id": row[0], "debate_count": row[1]}
                for row in cursor.fetchall()
            ]


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DebatesDatabase", "UserKarma"]
