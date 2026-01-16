"""
OthmanBot - Appeals Database Mixin
==================================

Appeal management operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
from typing import Optional

from src.core.logger import logger


class AppealsMixin:
    """Mixin for appeal management operations."""

    def has_appeal(self, user_id: int, action_type: str, action_id: int) -> bool:
        """Check if a pending appeal already exists."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT 1 FROM appeals
                   WHERE user_id = ? AND action_type = ? AND action_id = ?
                   AND status = 'pending' LIMIT 1""",
                (user_id, action_type, action_id)
            )
            return cursor.fetchone() is not None

    async def has_appeal_async(self, user_id: int, action_type: str, action_id: int) -> bool:
        """Async wrapper for has_appeal."""
        return await asyncio.to_thread(self.has_appeal, user_id, action_type, action_id)

    def create_appeal(
        self,
        user_id: int,
        action_type: str,
        action_id: int,
        reason: str,
        additional_context: Optional[str] = None
    ) -> Optional[int]:
        """Create a new appeal and return its ID."""
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
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Appeal already exists
                conn.rollback()
                return None

    async def create_appeal_async(
        self,
        user_id: int,
        action_type: str,
        action_id: int,
        reason: str,
        additional_context: Optional[str] = None
    ) -> Optional[int]:
        """Async wrapper for create_appeal."""
        return await asyncio.to_thread(
            self.create_appeal, user_id, action_type, action_id, reason, additional_context
        )

    def get_appeal(self, appeal_id: int) -> Optional[dict]:
        """Get an appeal by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, action_type, action_id, reason, additional_context,
                          status, reviewed_by, reviewed_at, denial_reason, message_id, created_at
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
                    "denial_reason": row[9],
                    "message_id": row[10],
                    "created_at": row[11],
                }
            return None

    async def get_appeal_async(self, appeal_id: int) -> Optional[dict]:
        """Async wrapper for get_appeal."""
        return await asyncio.to_thread(self.get_appeal, appeal_id)

    def update_appeal_status(
        self,
        appeal_id: int,
        status: str,
        reviewed_by: int,
        denial_reason: Optional[str] = None
    ) -> bool:
        """Update appeal status (approved/denied)."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE appeals
                   SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, denial_reason = ?
                   WHERE id = ?""",
                (status, reviewed_by, denial_reason, appeal_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def update_appeal_status_async(
        self,
        appeal_id: int,
        status: str,
        reviewed_by: int,
        denial_reason: Optional[str] = None
    ) -> bool:
        """Async wrapper for update_appeal_status."""
        return await asyncio.to_thread(
            self.update_appeal_status, appeal_id, status, reviewed_by, denial_reason
        )

    def set_appeal_message_id(self, appeal_id: int, message_id: int) -> bool:
        """Store the message ID where the appeal was posted."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE appeals SET message_id = ? WHERE id = ?",
                (message_id, appeal_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def set_appeal_message_id_async(self, appeal_id: int, message_id: int) -> bool:
        """Async wrapper for set_appeal_message_id."""
        return await asyncio.to_thread(self.set_appeal_message_id, appeal_id, message_id)

    def get_appeal_by_message_id(self, message_id: int) -> Optional[dict]:
        """Get an appeal by its message ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, action_type, action_id, reason, additional_context,
                          status, reviewed_by, reviewed_at, denial_reason, message_id, created_at
                   FROM appeals WHERE message_id = ?""",
                (message_id,)
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
                    "denial_reason": row[9],
                    "message_id": row[10],
                    "created_at": row[11],
                }
            return None

    def get_pending_appeals(self, limit: int = 50) -> list[dict]:
        """Get all pending appeals."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, user_id, action_type, action_id, reason, additional_context, created_at
                   FROM appeals WHERE status = 'pending'
                   ORDER BY created_at ASC LIMIT ?""",
                (limit,)
            )
            return [
                {
                    "id": r[0],
                    "user_id": r[1],
                    "action_type": r[2],
                    "action_id": r[3],
                    "reason": r[4],
                    "additional_context": r[5],
                    "created_at": r[6],
                }
                for r in cursor.fetchall()
            ]

    def get_user_appeals(self, user_id: int, limit: int = 10) -> list[dict]:
        """Get appeals submitted by a user."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, action_type, action_id, reason, status, created_at, reviewed_at
                   FROM appeals WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit)
            )
            return [
                {
                    "id": r[0],
                    "action_type": r[1],
                    "action_id": r[2],
                    "reason": r[3],
                    "status": r[4],
                    "created_at": r[5],
                    "reviewed_at": r[6],
                }
                for r in cursor.fetchall()
            ]
