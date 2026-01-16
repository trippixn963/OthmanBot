"""
OthmanBot - Database AI Cache Mixin
===================================

AI response caching operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional

from src.core.logger import logger
from .core import AI_CACHE_EXPIRATION_DAYS, AI_CACHE_MAX_ENTRIES


class AICacheMixin:
    """Mixin for AI cache database operations."""

    def get_ai_cache(self, cache_type: str, cache_key: str) -> Optional[str]:
        """Get cached AI response if not expired."""
        expiry_time = time.time() - (AI_CACHE_EXPIRATION_DAYS * 86400)
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT value FROM ai_cache
                   WHERE cache_type = ? AND cache_key = ? AND created_at > ?""",
                (cache_type, cache_key, expiry_time)
            )
            row = cur.fetchone()
            return row["value"] if row else None

    def set_ai_cache(self, cache_type: str, cache_key: str, value: str) -> None:
        """Set AI cache value with timestamp."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO ai_cache (cache_type, cache_key, value, created_at)
                   VALUES (?, ?, ?, ?)""",
                (cache_type, cache_key, value, time.time())
            )

    def cleanup_ai_cache(self) -> int:
        """Remove expired and excess cache entries."""
        expiry_time = time.time() - (AI_CACHE_EXPIRATION_DAYS * 86400)

        with self._get_conn() as conn:
            cur = conn.cursor()

            # Remove expired entries
            cur.execute(
                "DELETE FROM ai_cache WHERE created_at < ?",
                (expiry_time,)
            )
            expired_count = cur.rowcount

            # Check if over limit and remove oldest
            cur.execute("SELECT COUNT(*) as cnt FROM ai_cache")
            row = cur.fetchone()
            total = row["cnt"] if row else 0

            removed_oldest = 0
            if total > AI_CACHE_MAX_ENTRIES:
                to_remove = total - int(AI_CACHE_MAX_ENTRIES * 0.8)
                cur.execute(
                    """DELETE FROM ai_cache WHERE id IN (
                        SELECT id FROM ai_cache ORDER BY created_at ASC LIMIT ?
                    )""",
                    (to_remove,)
                )
                removed_oldest = to_remove

            total_removed = expired_count + removed_oldest
            if total_removed > 0:
                logger.tree("AI Cache Cleanup Complete", [
                    ("Expired Removed", str(expired_count)),
                    ("Oldest Removed", str(removed_oldest)),
                    ("Remaining", str(total - total_removed)),
                ], emoji="🧹")

            return total_removed
