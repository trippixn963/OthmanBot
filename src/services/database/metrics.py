"""
OthmanBot - Database Metrics Mixin
==================================

Scraper metrics recording and retrieval.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time

from src.core.logger import logger


class MetricsMixin:
    """Mixin for scraper metrics database operations."""

    def record_metric(
        self,
        content_type: str,
        metric_name: str,
        metric_value: float
    ) -> None:
        """Record a scraper metric."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO scraper_metrics
                   (content_type, metric_name, metric_value, recorded_at)
                   VALUES (?, ?, ?, ?)""",
                (content_type, metric_name, metric_value, time.time())
            )

    def get_metrics_summary(
        self,
        content_type: str,
        hours_back: int = 24
    ) -> dict:
        """Get metrics summary for a content type."""
        cutoff = time.time() - (hours_back * 3600)

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT metric_name,
                          COUNT(*) as count,
                          AVG(metric_value) as avg,
                          MIN(metric_value) as min,
                          MAX(metric_value) as max
                   FROM scraper_metrics
                   WHERE content_type = ? AND recorded_at > ?
                   GROUP BY metric_name""",
                (content_type, cutoff)
            )
            rows = cur.fetchall()

            result = {}
            for row in rows:
                result[row["metric_name"]] = {
                    "count": row["count"],
                    "avg": round(row["avg"], 2) if row["avg"] else 0,
                    "min": round(row["min"], 2) if row["min"] else 0,
                    "max": round(row["max"], 2) if row["max"] else 0,
                }
            return result

    def cleanup_metrics(self, days_to_keep: int = 7) -> int:
        """Remove old metrics entries."""
        cutoff = time.time() - (days_to_keep * 86400)

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM scraper_metrics WHERE recorded_at < ?",
                (cutoff,)
            )
            removed = cur.rowcount

            if removed > 0:
                logger.tree("Metrics Cleanup Complete", [
                    ("Removed", str(removed)),
                    ("Retention", f"{days_to_keep} days"),
                ], emoji="🧹")

            return removed
