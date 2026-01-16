"""
OthmanBot - Database Posted URLs Mixin
======================================

Posted article URL tracking operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time

from .core import POSTED_URLS_MAX_PER_TYPE


class PostedURLsMixin:
    """Mixin for posted URLs database operations."""

    def is_url_posted(self, content_type: str, article_id: str) -> bool:
        """Check if URL has been posted."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT 1 FROM posted_urls
                   WHERE content_type = ? AND article_id = ?""",
                (content_type, article_id)
            )
            row = cur.fetchone()
            return row is not None

    def mark_url_posted(self, content_type: str, article_id: str) -> None:
        """Mark URL as posted."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR IGNORE INTO posted_urls (content_type, article_id, posted_at)
                   VALUES (?, ?, ?)""",
                (content_type, article_id, time.time())
            )

    def cleanup_posted_urls(self, content_type: str) -> int:
        """Keep only the most recent URLs per content type."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) as cnt FROM posted_urls WHERE content_type = ?",
                (content_type,)
            )
            row = cur.fetchone()
            total = row["cnt"] if row else 0

            if total <= POSTED_URLS_MAX_PER_TYPE:
                return 0

            to_remove = total - POSTED_URLS_MAX_PER_TYPE
            cur.execute(
                """DELETE FROM posted_urls WHERE content_type = ? AND id IN (
                    SELECT id FROM posted_urls WHERE content_type = ?
                    ORDER BY posted_at ASC LIMIT ?
                )""",
                (content_type, content_type, to_remove)
            )
            return cur.rowcount

    def get_posted_urls_set(self, content_type: str) -> set:
        """Get all posted article IDs as a set for O(1) lookup."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT article_id FROM posted_urls WHERE content_type = ?",
                (content_type,)
            )
            rows = cur.fetchall()
            return {row["article_id"] for row in rows}
