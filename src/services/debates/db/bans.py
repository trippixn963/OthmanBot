"""
OthmanBot - Bans Database Mixin
=========================================

Debate ban management operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
from typing import Optional

from src.core.logger import logger


class BansMixin:
    """Mixin for ban management operations."""

    def add_debate_ban(
        self,
        user_id: int,
        thread_id: Optional[int],
        banned_by: int,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None
    ) -> bool:
        """Ban a user from a specific thread or all debates."""
        success = False
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO debate_bans (user_id, thread_id, banned_by, reason, expires_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, thread_id, banned_by, reason, expires_at)
                )
                conn.commit()
                success = True
            except sqlite3.IntegrityError as e:
                conn.rollback()
                logger.debug("Ban Already Exists", [
                    ("User ID", str(user_id)),
                    ("Thread ID", str(thread_id) if thread_id else "Global"),
                    ("Error", str(e)),
                ])

        if success:
            self._add_to_ban_history(user_id, thread_id, banned_by, reason, expires_at)
        return success

    async def add_debate_ban_async(
        self,
        user_id: int,
        thread_id: Optional[int],
        banned_by: int,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None
    ) -> bool:
        """Async wrapper for add_debate_ban."""
        return await asyncio.to_thread(
            self.add_debate_ban, user_id, thread_id, banned_by, reason, expires_at
        )

    def remove_debate_ban(self, user_id: int, thread_id: Optional[int]) -> bool:
        """Remove a debate ban."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if thread_id is None:
                cursor.execute("DELETE FROM debate_bans WHERE user_id = ?", (user_id,))
            else:
                cursor.execute(
                    "DELETE FROM debate_bans WHERE user_id = ? AND thread_id = ?",
                    (user_id, thread_id)
                )
            removed = cursor.rowcount > 0
            conn.commit()
        return removed

    async def remove_debate_ban_async(self, user_id: int, thread_id: Optional[int]) -> bool:
        """Async wrapper for remove_debate_ban."""
        return await asyncio.to_thread(self.remove_debate_ban, user_id, thread_id)

    def is_user_banned(self, user_id: int, thread_id: int) -> bool:
        """Check if user is banned from a specific thread."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT 1 FROM debate_bans
                   WHERE user_id = ? AND (thread_id = ? OR thread_id IS NULL)
                   AND (expires_at IS NULL OR expires_at > datetime('now'))
                   LIMIT 1""",
                (user_id, thread_id)
            )
            return cursor.fetchone() is not None

    async def is_user_banned_async(self, user_id: int, thread_id: int) -> bool:
        """Async wrapper for is_user_banned."""
        return await asyncio.to_thread(self.is_user_banned, user_id, thread_id)

    def get_user_bans(self, user_id: int) -> list[dict]:
        """Get all active bans for a user."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT thread_id, banned_by, reason, expires_at, created_at
                   FROM debate_bans WHERE user_id = ?
                   AND (expires_at IS NULL OR expires_at > datetime('now'))""",
                (user_id,)
            )
            return [
                {"thread_id": r[0], "banned_by": r[1], "reason": r[2], "expires_at": r[3], "created_at": r[4]}
                for r in cursor.fetchall()
            ]

    def get_all_banned_users(self) -> list[int]:
        """Get all unique user IDs that have active bans."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT user_id FROM debate_bans WHERE expires_at IS NULL OR expires_at > datetime('now')"
            )
            return [row[0] for row in cursor.fetchall()]

    def get_banned_users_with_info(self) -> list[dict]:
        """Get all banned users with their ban details."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, expires_at, thread_id FROM debate_bans
                   WHERE expires_at IS NULL OR expires_at > datetime('now')
                   ORDER BY expires_at ASC NULLS LAST"""
            )
            return [{"user_id": r[0], "expires_at": r[1], "thread_id": r[2]} for r in cursor.fetchall()]

    def get_expired_bans(self) -> list[dict]:
        """Get all expired bans that need to be removed."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, thread_id, banned_by, reason, expires_at, created_at
                   FROM debate_bans WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"""
            )
            return [
                {"id": r[0], "user_id": r[1], "thread_id": r[2], "banned_by": r[3], "reason": r[4], "expires_at": r[5], "created_at": r[6]}
                for r in cursor.fetchall()
            ]

    def remove_expired_bans(self) -> int:
        """Remove all expired bans and return count removed."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM debate_bans WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"
            )
            removed = cursor.rowcount
            conn.commit()
        return removed

    def _add_to_ban_history(
        self,
        user_id: int,
        thread_id: Optional[int],
        banned_by: int,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None,
        duration: Optional[str] = None
    ) -> None:
        """Add a ban record to permanent history."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO ban_history (user_id, thread_id, banned_by, reason, duration_hours, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, thread_id, banned_by, reason, duration, expires_at)
                )
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.debug("Ban History Insert Failed", [
                    ("User ID", str(user_id)),
                    ("Thread ID", str(thread_id) if thread_id else "Global"),
                    ("Error", str(e)),
                ])

    def update_ban_history_removal(
        self,
        user_id: int,
        removed_by: int,
        removal_reason: str = "Appeal approved"
    ) -> bool:
        """Update ban_history to mark ban as removed."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE ban_history SET removed_at = CURRENT_TIMESTAMP, removed_by = ?, removal_reason = ?
                   WHERE user_id = ? AND removed_at IS NULL ORDER BY created_at DESC LIMIT 1""",
                (removed_by, removal_reason, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_user_ban_count(self, user_id: int) -> int:
        """Get total number of times a user has been banned."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ban_history WHERE user_id = ?", (user_id,))
            return cursor.fetchone()[0]

    def get_user_ban_history(self, user_id: int, limit: int = 10) -> list[dict]:
        """Get a user's ban history."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, thread_id, banned_by, reason, duration_hours, expires_at, created_at, removed_at, removed_by, removal_reason
                   FROM ban_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit)
            )
            return [
                {"id": r[0], "thread_id": r[1], "banned_by": r[2], "reason": r[3], "duration": r[4], "expires_at": r[5], "created_at": r[6], "removed_at": r[7], "removed_by": r[8], "removal_reason": r[9]}
                for r in cursor.fetchall()
            ]

    def get_ban_history_at_time(self, user_id: int, appeal_created_at: str) -> Optional[dict]:
        """Get the ban from ban_history that was active at the time of an appeal."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, thread_id, banned_by, reason, duration_hours, expires_at, created_at
                   FROM ban_history WHERE user_id = ? AND created_at <= ?
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id, appeal_created_at)
            )
            row = cursor.fetchone()
            if row:
                return {"id": row[0], "thread_id": row[1], "banned_by": row[2], "reason": row[3], "duration": row[4], "expires_at": row[5], "created_at": row[6]}
            return None

    def increment_ban_count(self, user_id: int) -> int:
        """Increment ban count in case_logs and return new count."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE case_logs SET ban_count = ban_count + 1 WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
            cursor.execute("SELECT ban_count FROM case_logs WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row[0] if row else 1

    def update_last_unban(self, user_id: int) -> None:
        """Update last_unban_at timestamp in case_logs."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE case_logs SET last_unban_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
