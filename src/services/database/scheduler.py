"""
OthmanBot - Database Scheduler Mixin
====================================

Scheduler state persistence operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import time
from typing import Optional


class SchedulerMixin:
    """Mixin for scheduler state database operations."""

    def get_scheduler_state(self, scheduler_name: str) -> Optional[dict]:
        """Get scheduler state from database."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT is_running, extra_data FROM scheduler_state WHERE scheduler_name = ?",
                (scheduler_name,)
            )
            row = cur.fetchone()

            if not row:
                return None

            extra_data = None
            if row["extra_data"]:
                try:
                    extra_data = json.loads(row["extra_data"])
                except json.JSONDecodeError:
                    extra_data = None

            return {
                "is_running": bool(row["is_running"]),
                "extra_data": extra_data
            }

    def set_scheduler_state(
        self,
        scheduler_name: str,
        is_running: bool,
        extra_data: Optional[dict] = None
    ) -> None:
        """Save scheduler state to database."""
        extra_json = json.dumps(extra_data) if extra_data else None

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO scheduler_state
                   (scheduler_name, is_running, extra_data, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (scheduler_name, int(is_running), extra_json, time.time())
            )
