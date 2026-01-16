"""
OthmanBot - Database Dead Letter Queue Mixin
============================================

Dead letter queue for failed article processing.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time

from src.core.logger import logger
from .core import DEAD_LETTER_MAX_FAILURES, DEAD_LETTER_QUARANTINE_HOURS


class DeadLetterMixin:
    """Mixin for dead letter queue database operations."""

    def add_to_dead_letter(
        self,
        content_type: str,
        article_id: str,
        article_url: str,
        error: str
    ) -> int:
        """Add or update an article in the dead letter queue."""
        now = time.time()
        quarantine_until = now + (DEAD_LETTER_QUARANTINE_HOURS * 3600)

        with self._get_conn() as conn:
            cur = conn.cursor()

            # Check if already exists
            cur.execute(
                """SELECT failure_count FROM dead_letter_queue
                   WHERE content_type = ? AND article_id = ?""",
                (content_type, article_id)
            )
            existing = cur.fetchone()

            if existing:
                new_count = existing["failure_count"] + 1
                cur.execute(
                    """UPDATE dead_letter_queue
                       SET failure_count = ?,
                           last_error = ?,
                           last_failure_at = ?,
                           quarantined_until = ?
                       WHERE content_type = ? AND article_id = ?""",
                    (new_count, error[:500], now, quarantine_until,
                     content_type, article_id)
                )

                is_permanent = new_count >= DEAD_LETTER_MAX_FAILURES
                logger.tree("Dead Letter Queue Updated", [
                    ("Article ID", article_id[:30]),
                    ("Content Type", content_type),
                    ("Failure Count", f"{new_count}/{DEAD_LETTER_MAX_FAILURES}"),
                    ("Status", "PERMANENT" if is_permanent else "TEMPORARY"),
                    ("Error", error[:50]),
                ], emoji="💀" if is_permanent else "⚠️")

                return new_count
            else:
                cur.execute(
                    """INSERT INTO dead_letter_queue
                       (content_type, article_id, article_url, failure_count,
                        last_error, first_failure_at, last_failure_at, quarantined_until)
                       VALUES (?, ?, ?, 1, ?, ?, ?, ?)""",
                    (content_type, article_id, article_url, error[:500],
                     now, now, quarantine_until)
                )

                logger.tree("Dead Letter Queue - First Failure", [
                    ("Article ID", article_id[:30]),
                    ("Content Type", content_type),
                    ("Quarantine Hours", str(DEAD_LETTER_QUARANTINE_HOURS)),
                    ("Error", error[:50]),
                ], emoji="⚠️")

                return 1

    def is_quarantined(self, content_type: str, article_id: str) -> bool:
        """Check if an article is currently quarantined."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT quarantined_until, failure_count FROM dead_letter_queue
                   WHERE content_type = ? AND article_id = ?""",
                (content_type, article_id)
            )
            row = cur.fetchone()

            if not row:
                return False

            # Permanently quarantined if exceeded max failures
            if row["failure_count"] >= DEAD_LETTER_MAX_FAILURES:
                return True

            # Temporarily quarantined if within time window
            if row["quarantined_until"] and row["quarantined_until"] > time.time():
                return True

            return False

    def get_dead_letter_stats(self, content_type: str) -> dict:
        """Get statistics about dead letter queue."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN failure_count >= ? THEN 1 ELSE 0 END) as permanent,
                    SUM(CASE WHEN quarantined_until > ? THEN 1 ELSE 0 END) as temp_quarantined
                   FROM dead_letter_queue
                   WHERE content_type = ?""",
                (DEAD_LETTER_MAX_FAILURES, time.time(), content_type)
            )
            row = cur.fetchone()

            return {
                "total": row["total"] or 0,
                "permanent": row["permanent"] or 0,
                "temp_quarantined": row["temp_quarantined"] or 0,
            }

    def clear_dead_letter(self, content_type: str, article_id: str) -> None:
        """Remove an article from dead letter queue."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM dead_letter_queue WHERE content_type = ? AND article_id = ?",
                (content_type, article_id)
            )
