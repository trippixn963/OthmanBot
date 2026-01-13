"""
Othman Discord Bot - Cases Database Mixin
==========================================

Case log management for moderation tracking.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Optional


class CasesMixin:
    """Mixin for case log operations."""

    def get_case_log(self, user_id: int) -> Optional[dict]:
        """Get case log for a user."""
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
                    "case_id": row[0],
                    "thread_id": row[1],
                    "ban_count": row[2],
                    "last_unban_at": row[3],
                    "created_at": row[4]
                }
            return None

    def create_case_log(self, user_id: int, case_id: int, thread_id: int) -> None:
        """Create a new case log for a user."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO case_logs (user_id, case_id, thread_id) VALUES (?, ?, ?)",
                (user_id, case_id, thread_id)
            )
            conn.commit()

    def get_next_case_id(self) -> int:
        """Get the next available case ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(case_id) FROM case_logs")
            row = cursor.fetchone()
            return (row[0] or 0) + 1

    def get_all_case_logs(self) -> list[dict]:
        """Get all case logs."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, case_id, thread_id, ban_count, last_unban_at, created_at FROM case_logs ORDER BY case_id"
            )
            return [
                {"user_id": r[0], "case_id": r[1], "thread_id": r[2], "ban_count": r[3], "last_unban_at": r[4], "created_at": r[5]}
                for r in cursor.fetchall()
            ]


class CacheMixin:
    """Mixin for user cache operations."""

    def cache_user(self, user_id: int, username: str, display_name: Optional[str] = None) -> None:
        """Cache user info for leaderboard display."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO user_cache (user_id, username, display_name, is_member, updated_at)
                   VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                   username = ?, display_name = ?, is_member = 1, updated_at = CURRENT_TIMESTAMP""",
                (user_id, username, display_name, username, display_name)
            )
            conn.commit()

    def get_cached_user(self, user_id: int) -> Optional[dict]:
        """Get cached user info."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, display_name, is_member FROM user_cache WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return {"username": row[0], "display_name": row[1], "is_member": bool(row[2])}
            return None

    def mark_user_left(self, user_id: int) -> None:
        """Mark a user as having left the server."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_cache SET is_member = 0, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()

    def mark_user_rejoined(self, user_id: int) -> None:
        """Mark a user as having rejoined the server."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_cache SET is_member = 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()

    def get_leaderboard_users_in_cache(self) -> list[int]:
        """Get user IDs that are in the cache."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM user_cache")
            return [row[0] for row in cursor.fetchall()]

    def delete_user_data(self, user_id: int) -> dict:
        """Delete all data for a user (GDPR-style)."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            result = {}

            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            result["users_deleted"] = cursor.rowcount

            cursor.execute("DELETE FROM votes WHERE voter_id = ? OR author_id = ?", (user_id, user_id))
            result["votes_deleted"] = cursor.rowcount

            cursor.execute("DELETE FROM debate_participation WHERE user_id = ?", (user_id,))
            result["participation_deleted"] = cursor.rowcount

            cursor.execute("DELETE FROM debate_creators WHERE user_id = ?", (user_id,))
            result["creators_deleted"] = cursor.rowcount

            cursor.execute("DELETE FROM user_cache WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM user_streaks WHERE user_id = ?", (user_id,))

            conn.commit()
            return result

    async def delete_user_data_async(self, user_id: int) -> dict:
        """Async wrapper for delete_user_data."""
        import asyncio
        return await asyncio.to_thread(self.delete_user_data, user_id)
