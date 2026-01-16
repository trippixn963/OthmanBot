"""
OthmanBot - Analytics Database Mixin
==============================================

User analytics, streaks, and participation tracking.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional


class AnalyticsMixin:
    """Mixin for analytics and participation operations."""

    def get_user_analytics(self, user_id: int) -> dict:
        """Get detailed analytics for a user's debate participation."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM debate_participation WHERE user_id = ?", (user_id,))
            debates_participated = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM debate_creators WHERE user_id = ?", (user_id,))
            debates_created = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(message_count), 0) FROM debate_participation WHERE user_id = ?", (user_id,))
            total_messages = cursor.fetchone()[0] or 0

            return {
                "debates_participated": debates_participated,
                "debates_created": debates_created,
                "total_messages": total_messages,
            }

    async def get_user_analytics_async(self, user_id: int) -> dict:
        """Async wrapper for get_user_analytics."""
        return await asyncio.to_thread(self.get_user_analytics, user_id)

    def has_debate_participation(self, user_id: int) -> bool:
        """Check if a user has ever participated in debates."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT 1 FROM debate_participation WHERE user_id = ? LIMIT 1", (user_id,))
            if cursor.fetchone():
                return True

            cursor.execute("SELECT 1 FROM debate_creators WHERE user_id = ? LIMIT 1", (user_id,))
            if cursor.fetchone():
                return True

            cursor.execute("SELECT 1 FROM users WHERE user_id = ? AND total_karma != 0 LIMIT 1", (user_id,))
            return cursor.fetchone() is not None

    def update_user_streak(self, user_id: int) -> dict:
        """Update a user's daily participation streak."""
        from src.core.config import NY_TZ
        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT current_streak, longest_streak, last_active_date FROM user_streaks WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()

            if row:
                current_streak, longest_streak, last_active_date = row

                if last_active_date == today:
                    return {"current_streak": current_streak, "longest_streak": longest_streak, "streak_extended": False}

                yesterday = (datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
                           - timedelta(days=1)).strftime("%Y-%m-%d")

                if last_active_date == yesterday:
                    current_streak += 1
                    if current_streak > longest_streak:
                        longest_streak = current_streak
                else:
                    current_streak = 1

                cursor.execute(
                    "UPDATE user_streaks SET current_streak = ?, longest_streak = ?, last_active_date = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (current_streak, longest_streak, today, user_id)
                )
            else:
                current_streak = 1
                longest_streak = 1
                cursor.execute(
                    "INSERT INTO user_streaks (user_id, current_streak, longest_streak, last_active_date) VALUES (?, 1, 1, ?)",
                    (user_id, today)
                )

            conn.commit()
            return {"current_streak": current_streak, "longest_streak": longest_streak, "streak_extended": True}

    async def update_user_streak_async(self, user_id: int) -> dict:
        """Async wrapper for update_user_streak."""
        return await asyncio.to_thread(self.update_user_streak, user_id)

    def get_user_streak(self, user_id: int) -> dict:
        """Get a user's current streak data."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT current_streak, longest_streak, last_active_date FROM user_streaks WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return {"current_streak": row[0], "longest_streak": row[1], "last_active_date": row[2]}
            return {"current_streak": 0, "longest_streak": 0, "last_active_date": None}

    async def get_user_streak_async(self, user_id: int) -> dict:
        """Async wrapper for get_user_streak."""
        return await asyncio.to_thread(self.get_user_streak, user_id)

    def get_top_streaks(self, limit: int = 3) -> list[dict]:
        """Get users with the highest current streaks."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, current_streak, longest_streak FROM user_streaks ORDER BY current_streak DESC LIMIT ?",
                (limit,)
            )
            return [{"user_id": r[0], "current_streak": r[1], "longest_streak": r[2]} for r in cursor.fetchall()]

    def increment_participation(self, thread_id: int, user_id: int) -> None:
        """Increment message count for a user in a thread."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO debate_participation (thread_id, user_id, message_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(thread_id, user_id) DO UPDATE SET message_count = message_count + 1""",
                (thread_id, user_id)
            )
            conn.commit()

    async def increment_participation_async(self, thread_id: int, user_id: int) -> None:
        """Async wrapper for increment_participation."""
        await asyncio.to_thread(self.increment_participation, thread_id, user_id)

    def set_debate_creator(self, thread_id: int, user_id: int) -> None:
        """Set the creator of a debate thread."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO debate_creators (thread_id, user_id) VALUES (?, ?)",
                (thread_id, user_id)
            )
            conn.commit()

    async def set_debate_creator_async(self, thread_id: int, user_id: int) -> None:
        """Async wrapper for set_debate_creator."""
        await asyncio.to_thread(self.set_debate_creator, thread_id, user_id)

    def bulk_set_participation(self, thread_id: int, user_id: int, count: int) -> None:
        """Set participation count directly (for reconciliation)."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO debate_participation (thread_id, user_id, message_count)
                   VALUES (?, ?, ?)
                   ON CONFLICT(thread_id, user_id) DO UPDATE SET message_count = ?""",
                (thread_id, user_id, count, count)
            )
            conn.commit()

    def get_user_recent_debates(self, user_id: int, limit: int = 5) -> list[dict]:
        """Get a user's recent debate participation."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT thread_id, message_count, created_at FROM debate_participation
                   WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit)
            )
            return [{"thread_id": r[0], "message_count": r[1], "created_at": r[2]} for r in cursor.fetchall()]

    def get_most_active_participants(self, limit: int = 3) -> list[dict]:
        """Get most active participants across all debates."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, COUNT(*) as debate_count, SUM(message_count) as total_messages
                   FROM debate_participation GROUP BY user_id ORDER BY debate_count DESC LIMIT ?""",
                (limit,)
            )
            return [{"user_id": r[0], "debate_count": r[1], "total_messages": r[2]} for r in cursor.fetchall()]

    def get_active_debate_count(self) -> int:
        """Get count of active debates."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM debate_threads")
            return cursor.fetchone()[0]

    def get_monthly_stats(self, year: int, month: int) -> dict:
        """Get statistics for a specific month."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) FROM votes WHERE strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?",
                (str(year), f"{month:02d}")
            )
            total_votes = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(DISTINCT author_id) FROM votes WHERE strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?",
                (str(year), f"{month:02d}")
            )
            unique_voters = cursor.fetchone()[0]

            return {"total_votes": total_votes, "unique_voters": unique_voters, "year": year, "month": month}

    def get_all_time_stats(self) -> dict:
        """
        Get all-time statistics for presence display.

        Returns:
            Dict with total_debates, total_votes, total_karma, total_participants, total_messages
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Total debates created
            cursor.execute("SELECT COUNT(*) FROM debate_threads")
            total_debates = cursor.fetchone()[0] or 0

            # Total votes cast
            cursor.execute("SELECT COUNT(*) FROM votes")
            total_votes = cursor.fetchone()[0] or 0

            # Total karma earned (sum of positive karma only)
            cursor.execute("SELECT COALESCE(SUM(CASE WHEN total_karma > 0 THEN total_karma ELSE 0 END), 0) FROM users")
            total_karma = cursor.fetchone()[0] or 0

            # Total unique participants
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM debate_participation")
            total_participants = cursor.fetchone()[0] or 0

            # Total messages in debates
            cursor.execute("SELECT COALESCE(SUM(message_count), 0) FROM debate_participation")
            total_messages = cursor.fetchone()[0] or 0

            return {
                "total_debates": total_debates,
                "total_votes": total_votes,
                "total_karma": total_karma,
                "total_participants": total_participants,
                "total_messages": total_messages,
            }
