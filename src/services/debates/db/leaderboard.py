"""
OthmanBot - Leaderboard Database Mixin
================================================

Leaderboard and ranking operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import Optional

from src.services.debates.db.core import UserKarma


class LeaderboardMixin:
    """Mixin for leaderboard operations."""

    def get_leaderboard(self, limit: int = 10) -> list[UserKarma]:
        """Get top users by karma."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, total_karma, upvotes_received, downvotes_received FROM users ORDER BY total_karma DESC LIMIT ?",
                (limit,)
            )
            return [UserKarma(*row) for row in cursor.fetchall()]

    async def get_leaderboard_async(self, limit: int = 10) -> list[UserKarma]:
        """Async wrapper for get_leaderboard."""
        return await asyncio.to_thread(self.get_leaderboard, limit)

    def get_user_rank(self, user_id: int) -> int:
        """Get user's rank on leaderboard (1-indexed)."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*) + 1 FROM users
                   WHERE total_karma > (SELECT COALESCE(total_karma, 0) FROM users WHERE user_id = ?)""",
                (user_id,)
            )
            return cursor.fetchone()[0]

    async def get_user_rank_async(self, user_id: int) -> int:
        """Async wrapper for get_user_rank."""
        return await asyncio.to_thread(self.get_user_rank, user_id)

    def get_monthly_leaderboard(self, year: int, month: int, limit: int = 10) -> list[dict]:
        """Get leaderboard for a specific month based on votes in that month."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT author_id, SUM(vote_type) as monthly_karma
                   FROM votes
                   WHERE strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?
                   GROUP BY author_id
                   ORDER BY monthly_karma DESC
                   LIMIT ?""",
                (str(year), f"{month:02d}", limit)
            )
            return [{"user_id": r[0], "monthly_karma": r[1]} for r in cursor.fetchall()]

    def get_category_leaderboards(self, limit: int = 10) -> dict:
        """Get leaderboards for different categories."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            result = {}

            # Most debates participated
            cursor.execute(
                "SELECT user_id, COUNT(*) as count FROM debate_participation GROUP BY user_id ORDER BY count DESC LIMIT ?",
                (limit,)
            )
            result["most_active"] = [{"user_id": r[0], "count": r[1]} for r in cursor.fetchall()]

            # Most debates created
            cursor.execute(
                "SELECT user_id, COUNT(*) as count FROM debate_creators GROUP BY user_id ORDER BY count DESC LIMIT ?",
                (limit,)
            )
            result["most_debates_started"] = [{"user_id": r[0], "count": r[1]} for r in cursor.fetchall()]

            # Most upvotes received
            cursor.execute(
                "SELECT user_id, upvotes_received FROM users WHERE upvotes_received > 0 ORDER BY upvotes_received DESC LIMIT ?",
                (limit,)
            )
            result["most_upvoted"] = [{"user_id": r[0], "count": r[1]} for r in cursor.fetchall()]

            return result

    def get_rank_change(self, user_id: int) -> int:
        """Get user's rank change over the past week."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get current rank
            cursor.execute(
                "SELECT COUNT(*) + 1 FROM users WHERE total_karma > (SELECT COALESCE(total_karma, 0) FROM users WHERE user_id = ?)",
                (user_id,)
            )
            current_rank = cursor.fetchone()[0]

            # Get karma gained in past week
            cursor.execute(
                """SELECT COALESCE(SUM(vote_type), 0) FROM votes
                   WHERE author_id = ? AND created_at >= datetime('now', '-7 days')""",
                (user_id,)
            )
            recent_karma = cursor.fetchone()[0]

            # Estimate previous rank
            cursor.execute(
                """SELECT COUNT(*) + 1 FROM users
                   WHERE total_karma - ? > (SELECT COALESCE(total_karma, 0) - ? FROM users WHERE user_id = ?)""",
                (recent_karma, recent_karma, user_id)
            )
            estimated_old_rank = cursor.fetchone()[0]

            return estimated_old_rank - current_rank

    def get_karma_history(self, user_id: int, days: int = 7) -> list[int]:
        """Get daily karma changes for a user over the past N days."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT DATE(created_at), SUM(vote_type)
                   FROM votes WHERE author_id = ? AND created_at >= datetime('now', ?)
                   GROUP BY DATE(created_at) ORDER BY DATE(created_at)""",
                (user_id, f"-{days} days")
            )
            return [r[1] for r in cursor.fetchall()]
