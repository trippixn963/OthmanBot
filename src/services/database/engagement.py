"""
OthmanBot - Database Engagement Mixin
=====================================

Article engagement tracking operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import List

from src.core.logger import logger


class EngagementMixin:
    """Mixin for article engagement database operations."""

    def track_article_engagement(
        self,
        content_type: str,
        article_id: str,
        thread_id: int,
        thread_url: str,
        title: str,
    ) -> None:
        """Start tracking engagement for a posted article."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO article_engagement
                   (content_type, article_id, thread_id, thread_url, title, posted_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (content_type, article_id, thread_id, thread_url, title, time.time())
            )

        logger.tree("Article Engagement Tracking Started", [
            ("Content Type", content_type),
            ("Article ID", article_id[:20]),
            ("Thread ID", str(thread_id)),
        ], emoji="📊")

    def update_article_engagement(
        self,
        thread_id: int,
        upvotes: int,
        downvotes: int,
        replies: int,
    ) -> None:
        """Update engagement metrics for an article."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE article_engagement
                   SET upvotes = ?, downvotes = ?, replies = ?, last_checked_at = ?
                   WHERE thread_id = ?""",
                (upvotes, downvotes, replies, time.time(), thread_id)
            )

    def get_articles_to_check(
        self,
        content_type: str,
        hours_since_post: int = 72,
        limit: int = 20,
    ) -> List[dict]:
        """Get articles that need engagement checking."""
        cutoff = time.time() - (hours_since_post * 3600)

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT thread_id, article_id, title, upvotes, downvotes, replies
                   FROM article_engagement
                   WHERE content_type = ? AND posted_at > ?
                   ORDER BY posted_at DESC
                   LIMIT ?""",
                (content_type, cutoff, limit)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def get_top_articles(
        self,
        content_type: str,
        days_back: int = 7,
        limit: int = 10,
    ) -> List[dict]:
        """Get top performing articles by engagement."""
        cutoff = time.time() - (days_back * 86400)

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT article_id, title, thread_url, upvotes, downvotes, replies,
                          (upvotes + replies) as engagement_score
                   FROM article_engagement
                   WHERE content_type = ? AND posted_at > ?
                   ORDER BY engagement_score DESC
                   LIMIT ?""",
                (content_type, cutoff, limit)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def get_engagement_summary(self, content_type: str, days_back: int = 7) -> dict:
        """Get engagement summary statistics."""
        cutoff = time.time() - (days_back * 86400)

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT
                    COUNT(*) as total_articles,
                    SUM(upvotes) as total_upvotes,
                    SUM(downvotes) as total_downvotes,
                    SUM(replies) as total_replies,
                    AVG(upvotes) as avg_upvotes,
                    AVG(replies) as avg_replies
                   FROM article_engagement
                   WHERE content_type = ? AND posted_at > ?""",
                (content_type, cutoff)
            )
            row = cur.fetchone()

            return {
                "total_articles": row["total_articles"] or 0,
                "total_upvotes": row["total_upvotes"] or 0,
                "total_downvotes": row["total_downvotes"] or 0,
                "total_replies": row["total_replies"] or 0,
                "avg_upvotes": round(row["avg_upvotes"] or 0, 1),
                "avg_replies": round(row["avg_replies"] or 0, 1),
            }
