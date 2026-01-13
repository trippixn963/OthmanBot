"""
OthmanBot - Karma Database Mixin
==========================================

Vote and karma tracking operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
from typing import Optional

from src.core.logger import logger
from src.services.debates.db.core import UserKarma


class KarmaMixin:
    """Mixin for vote and karma operations."""

    def add_vote(
        self,
        voter_id: int,
        message_id: int,
        author_id: int,
        vote_type: int
    ) -> bool:
        """Add or update a vote."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute(
                    "SELECT vote_type FROM votes WHERE voter_id = ? AND message_id = ?",
                    (voter_id, message_id)
                )
                existing = cursor.fetchone()

                if existing:
                    old_vote = existing[0]
                    if old_vote == vote_type:
                        conn.rollback()
                        return False

                    cursor.execute(
                        "UPDATE votes SET vote_type = ? WHERE voter_id = ? AND message_id = ?",
                        (vote_type, voter_id, message_id)
                    )
                    karma_change = vote_type - old_vote
                    self._update_user_karma(cursor, author_id, karma_change, vote_type)
                else:
                    cursor.execute(
                        "INSERT INTO votes (voter_id, message_id, author_id, vote_type) VALUES (?, ?, ?, ?)",
                        (voter_id, message_id, author_id, vote_type)
                    )
                    self._update_user_karma(cursor, author_id, vote_type, vote_type)

                conn.commit()
                return True
            except sqlite3.OperationalError:
                conn.rollback()
                raise
            except sqlite3.IntegrityError:
                conn.rollback()
                return False

    async def add_vote_async(
        self,
        voter_id: int,
        message_id: int,
        author_id: int,
        vote_type: int,
        max_retries: int = 3
    ) -> bool:
        """Async wrapper with retry logic."""
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(
                    self.add_vote, voter_id, message_id, author_id, vote_type
                )
            except sqlite3.OperationalError:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (2 ** attempt))
        return False

    def remove_vote(self, voter_id: int, message_id: int) -> Optional[int]:
        """Remove a vote. Returns author_id if removed."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute(
                    "SELECT author_id, vote_type FROM votes WHERE voter_id = ? AND message_id = ?",
                    (voter_id, message_id)
                )
                existing = cursor.fetchone()

                if not existing:
                    conn.rollback()
                    return None

                author_id, vote_type = existing
                cursor.execute(
                    "DELETE FROM votes WHERE voter_id = ? AND message_id = ?",
                    (voter_id, message_id)
                )
                self._update_user_karma(cursor, author_id, -vote_type, vote_type, is_removal=True)
                conn.commit()
                return author_id
            except sqlite3.OperationalError:
                conn.rollback()
                raise

    async def remove_vote_async(self, voter_id: int, message_id: int) -> Optional[int]:
        """Async wrapper for remove_vote."""
        return await asyncio.to_thread(self.remove_vote, voter_id, message_id)

    def get_message_votes(self, message_id: int) -> dict[int, int]:
        """Get all votes for a message."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT voter_id, vote_type FROM votes WHERE message_id = ?",
                (message_id,)
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    async def get_message_votes_async(self, message_id: int) -> dict[int, int]:
        """Async wrapper for get_message_votes."""
        return await asyncio.to_thread(self.get_message_votes, message_id)

    def _update_user_karma(
        self,
        cursor: sqlite3.Cursor,
        user_id: int,
        karma_change: int,
        vote_type: int,
        is_removal: bool = False
    ) -> None:
        """Update user karma totals."""
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        counter_change = -1 if is_removal else 1

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

    def get_user_karma(self, user_id: int) -> UserKarma:
        """Get karma data for a user."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, total_karma, upvotes_received, downvotes_received FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return UserKarma(*row) if row else UserKarma(user_id, 0, 0, 0)

    async def get_user_karma_async(self, user_id: int) -> UserKarma:
        """Async wrapper for get_user_karma."""
        return await asyncio.to_thread(self.get_user_karma, user_id)

    def reset_user_karma(self, user_id: int) -> dict:
        """Reset karma for a user without deleting participation history."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            result = {"karma_reset": False, "votes_cast_removed": 0, "votes_received_removed": 0}

            try:
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute("SELECT total_karma FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                result["old_karma"] = row[0] if row else 0

                cursor.execute(
                    "UPDATE users SET total_karma = 0, upvotes_received = 0, downvotes_received = 0 WHERE user_id = ?",
                    (user_id,)
                )
                result["karma_reset"] = cursor.rowcount > 0

                # Reverse karma from votes this user made
                cursor.execute("SELECT author_id, vote_type FROM votes WHERE voter_id = ?", (user_id,))
                for author_id, vote_type in cursor.fetchall():
                    if vote_type > 0:
                        cursor.execute(
                            "UPDATE users SET total_karma = total_karma - 1, upvotes_received = MAX(0, upvotes_received - 1) WHERE user_id = ?",
                            (author_id,)
                        )
                    else:
                        cursor.execute(
                            "UPDATE users SET total_karma = total_karma + 1, downvotes_received = MAX(0, downvotes_received - 1) WHERE user_id = ?",
                            (author_id,)
                        )
                    result["votes_cast_removed"] += 1

                cursor.execute("DELETE FROM votes WHERE voter_id = ?", (user_id,))
                cursor.execute("DELETE FROM votes WHERE author_id = ?", (user_id,))
                result["votes_received_removed"] = cursor.rowcount

                conn.commit()
                return result
            except sqlite3.Error:
                conn.rollback()
                raise

    async def reset_user_karma_async(self, user_id: int) -> dict:
        """Async wrapper for reset_user_karma."""
        return await asyncio.to_thread(self.reset_user_karma, user_id)

    def get_votes_by_user(self, user_id: int) -> list[dict]:
        """Get all votes cast by a user."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT message_id, author_id, vote_type, created_at FROM votes WHERE voter_id = ?",
                (user_id,)
            )
            return [
                {"message_id": r[0], "author_id": r[1], "vote_type": r[2], "created_at": r[3]}
                for r in cursor.fetchall()
            ]

    def get_votes_today(self) -> int:
        """Get total votes cast today."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM votes WHERE DATE(created_at) = DATE('now')"
            )
            return cursor.fetchone()[0]

    def get_total_votes(self) -> int:
        """Get total vote count."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM votes")
            return cursor.fetchone()[0]

    def remove_votes_by_user(self, user_id: int) -> dict:
        """Remove all votes cast by a user (reversing karma effects)."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            result = {"votes_removed": 0}

            try:
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute("SELECT author_id, vote_type FROM votes WHERE voter_id = ?", (user_id,))
                votes = cursor.fetchall()

                for author_id, vote_type in votes:
                    if vote_type > 0:
                        cursor.execute(
                            "UPDATE users SET total_karma = total_karma - 1, upvotes_received = MAX(0, upvotes_received - 1) WHERE user_id = ?",
                            (author_id,)
                        )
                    else:
                        cursor.execute(
                            "UPDATE users SET total_karma = total_karma + 1, downvotes_received = MAX(0, downvotes_received - 1) WHERE user_id = ?",
                            (author_id,)
                        )

                cursor.execute("DELETE FROM votes WHERE voter_id = ?", (user_id,))
                result["votes_removed"] = cursor.rowcount
                conn.commit()
                return result
            except sqlite3.Error:
                conn.rollback()
                raise
