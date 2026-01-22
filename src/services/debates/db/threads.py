"""
OthmanBot - Threads Database Mixin
==================================

Thread data, analytics messages, and debate numbering.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import Optional


class ThreadsMixin:
    """Mixin for thread management operations."""

    def set_analytics_message(self, thread_id: int, message_id: int) -> None:
        """Store the analytics message ID for a thread."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO debate_threads (thread_id, analytics_message_id)
                   VALUES (?, ?)
                   ON CONFLICT(thread_id) DO UPDATE SET analytics_message_id = ?""",
                (thread_id, message_id, message_id)
            )
            conn.commit()

    async def set_analytics_message_async(self, thread_id: int, message_id: int) -> None:
        """Async wrapper for set_analytics_message."""
        await asyncio.to_thread(self.set_analytics_message, thread_id, message_id)

    def get_analytics_message(self, thread_id: int) -> Optional[int]:
        """Get the analytics message ID for a thread."""
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
        """Async wrapper for get_analytics_message."""
        return await asyncio.to_thread(self.get_analytics_message, thread_id)

    def clear_analytics_message(self, thread_id: int) -> None:
        """Clear the analytics message ID for a thread."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE debate_threads SET analytics_message_id = NULL WHERE thread_id = ?",
                (thread_id,)
            )
            conn.commit()

    async def clear_analytics_message_async(self, thread_id: int) -> None:
        """Async wrapper for clear_analytics_message."""
        await asyncio.to_thread(self.clear_analytics_message, thread_id)

    def get_all_debate_thread_ids(self) -> list[int]:
        """Get all tracked debate thread IDs."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT thread_id FROM debate_threads")
            return [row[0] for row in cursor.fetchall()]

    def delete_thread_data(self, thread_id: int) -> dict:
        """Delete all data associated with a thread."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            result = {"votes_deleted": 0, "participation_deleted": 0, "creator_deleted": 0}

            cursor.execute("DELETE FROM debate_threads WHERE thread_id = ?", (thread_id,))
            cursor.execute("DELETE FROM debate_participation WHERE thread_id = ?", (thread_id,))
            result["participation_deleted"] = cursor.rowcount
            cursor.execute("DELETE FROM debate_creators WHERE thread_id = ?", (thread_id,))
            result["creator_deleted"] = cursor.rowcount
            cursor.execute("DELETE FROM debate_bans WHERE thread_id = ?", (thread_id,))

            conn.commit()
            return result

    def get_next_debate_number(self) -> int:
        """
        Get and increment the debate counter atomically.

        Uses BEGIN IMMEDIATE to acquire exclusive lock at transaction start,
        preventing race conditions when multiple threads are created simultaneously.
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # BEGIN IMMEDIATE acquires exclusive lock immediately
            cursor.execute("BEGIN IMMEDIATE")
            try:
                cursor.execute("SELECT counter FROM debate_counter WHERE id = 1")
                row = cursor.fetchone()
                if row:
                    current = row[0]
                    next_num = current + 1
                    cursor.execute("UPDATE debate_counter SET counter = ? WHERE id = 1", (next_num,))
                else:
                    next_num = 1
                    cursor.execute("INSERT INTO debate_counter (id, counter) VALUES (1, 1)")

                conn.commit()
                return next_num
            except Exception:
                conn.rollback()
                raise

    def set_debate_counter(self, value: int) -> None:
        """Set the debate counter to a specific value."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO debate_counter (id, counter) VALUES (1, ?)
                   ON CONFLICT(id) DO UPDATE SET counter = ?""",
                (value, value)
            )
            conn.commit()

    def get_debate_counter(self) -> int:
        """Get the current debate counter value."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT counter FROM debate_counter WHERE id = 1")
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_most_active_debates(self, limit: int = 3) -> list[dict]:
        """Get debates with most participation."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT thread_id, COUNT(*) as participant_count, SUM(message_count) as total_messages
                   FROM debate_participation GROUP BY thread_id ORDER BY participant_count DESC LIMIT ?""",
                (limit,)
            )
            return [{"thread_id": r[0], "participant_count": r[1], "total_messages": r[2]} for r in cursor.fetchall()]

    def get_top_debate_starters(self, limit: int = 3) -> list[dict]:
        """Get users who have started the most debates."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, COUNT(*) as debate_count FROM debate_creators GROUP BY user_id ORDER BY debate_count DESC LIMIT ?",
                (limit,)
            )
            return [{"user_id": r[0], "debate_count": r[1]} for r in cursor.fetchall()]

    def get_threads_by_creator(self, user_id: int) -> list[int]:
        """Get all thread IDs created by a user."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT thread_id FROM debate_creators WHERE user_id = ?",
                (user_id,)
            )
            return [row[0] for row in cursor.fetchall()]

    def add_to_closure_history(
        self,
        thread_id: int,
        thread_name: str,
        closed_by: int,
        reason: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> None:
        """Add a thread closure to history.

        Args:
            thread_id: The thread ID that was closed
            thread_name: The name of the thread
            closed_by: The moderator who closed it
            reason: The reason for closing
            user_id: The debate owner's user ID (whose debate was closed)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO closure_history (thread_id, thread_name, closed_by, reason, user_id) VALUES (?, ?, ?, ?, ?)",
                (thread_id, thread_name, closed_by, reason, user_id)
            )
            conn.commit()

    def get_user_closure_count(self, user_id: int) -> int:
        """Get number of times a user's debates have been closed."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM closure_history WHERE user_id = ?", (user_id,))
            return cursor.fetchone()[0]

    def get_user_closure_history(self, user_id: int, limit: int = 10) -> list[dict]:
        """Get closure history for debates involving a user."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT thread_id, thread_name, closed_by, reason, created_at, reopened_at, reopened_by
                   FROM closure_history WHERE closed_by = ? ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit)
            )
            return [
                {"thread_id": r[0], "thread_name": r[1], "closed_by": r[2], "reason": r[3], "created_at": r[4], "reopened_at": r[5], "reopened_by": r[6]}
                for r in cursor.fetchall()
            ]

    def get_closure_by_thread_id(self, thread_id: int) -> Optional[dict]:
        """Get closure info for a specific thread."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT thread_name, closed_by, reason, created_at, reopened_at, reopened_by FROM closure_history WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1",
                (thread_id,)
            )
            row = cursor.fetchone()
            if row:
                return {"thread_name": row[0], "closed_by": row[1], "reason": row[2], "created_at": row[3], "reopened_at": row[4], "reopened_by": row[5]}
            return None

    def update_closure_history_reopened(self, thread_id: int, reopened_by: int) -> bool:
        """Mark a closure as reopened."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE closure_history SET reopened_at = CURRENT_TIMESTAMP, reopened_by = ? WHERE thread_id = ? AND reopened_at IS NULL ORDER BY created_at DESC LIMIT 1",
                (reopened_by, thread_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # Open Discussion Thread Management
    # =========================================================================

    def get_open_discussion_thread_id(self) -> Optional[int]:
        """Get the Open Discussion thread ID from the database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT thread_id FROM open_discussion WHERE id = 1")
            row = cursor.fetchone()
            return row[0] if row else None

    def set_open_discussion_thread_id(self, thread_id: int) -> None:
        """Set the Open Discussion thread ID in the database."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO open_discussion (id, thread_id)
                   VALUES (1, ?)
                   ON CONFLICT(id) DO UPDATE SET thread_id = ?""",
                (thread_id, thread_id)
            )
            conn.commit()
