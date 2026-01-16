"""
OthmanBot - Database Content Hashes Mixin
=========================================

Content similarity detection via stored hashes.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import List, Tuple

from src.core.logger import logger
from .core import CONTENT_HASH_RETENTION_DAYS, CONTENT_HASH_MAX_ENTRIES


class ContentHashesMixin:
    """Mixin for content hash database operations."""

    def store_content_hash(
        self,
        content_type: str,
        article_id: str,
        content_text: str
    ) -> None:
        """Store content text for similarity comparison."""
        # Store truncated content for similarity checking
        truncated = content_text[:2000] if len(content_text) > 2000 else content_text

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO content_hashes
                   (content_type, article_id, content_text, created_at)
                   VALUES (?, ?, ?, ?)""",
                (content_type, article_id, truncated, time.time())
            )

    def get_recent_content(
        self,
        content_type: str,
        limit: int = 50
    ) -> List[Tuple[str, str]]:
        """Get recent content for similarity comparison."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT article_id, content_text FROM content_hashes
                   WHERE content_type = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (content_type, limit)
            )
            rows = cur.fetchall()
            return [(row["article_id"], row["content_text"]) for row in rows]

    def cleanup_content_hashes(self) -> int:
        """Remove old content hashes."""
        cutoff = time.time() - (CONTENT_HASH_RETENTION_DAYS * 86400)

        with self._get_conn() as conn:
            cur = conn.cursor()

            # Remove expired entries
            cur.execute(
                "DELETE FROM content_hashes WHERE created_at < ?",
                (cutoff,)
            )
            expired = cur.rowcount

            # Check if over limit per type
            excess_removed = 0
            for content_type in ["news", "soccer"]:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM content_hashes WHERE content_type = ?",
                    (content_type,)
                )
                row = cur.fetchone()
                total = row["cnt"] if row else 0

                if total > CONTENT_HASH_MAX_ENTRIES:
                    to_remove = total - CONTENT_HASH_MAX_ENTRIES
                    cur.execute(
                        """DELETE FROM content_hashes
                           WHERE content_type = ? AND id IN (
                               SELECT id FROM content_hashes
                               WHERE content_type = ?
                               ORDER BY created_at ASC
                               LIMIT ?
                           )""",
                        (content_type, content_type, to_remove)
                    )
                    excess_removed += to_remove

            total_removed = expired + excess_removed
            if total_removed > 0:
                logger.tree("Content Hash Cleanup Complete", [
                    ("Expired Removed", str(expired)),
                    ("Excess Removed", str(excess_removed)),
                    ("Retention Days", str(CONTENT_HASH_RETENTION_DAYS)),
                ], emoji="🧹")

            return expired
