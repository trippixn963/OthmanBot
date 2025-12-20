"""
Othman Discord Bot - AI Cache Utility
======================================

SQLite-based cache for AI-generated responses to reduce API costs.

Uses the unified othman.db database for storage.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Optional

from src.core.database import get_db
from src.core.logger import logger


class AICache:
    """
    SQLite-based cache for AI responses.

    Stores AI-generated content (titles, summaries) to avoid
    redundant OpenAI API calls for the same content.

    Uses the unified database for persistence.
    """

    def __init__(self, cache_type: str) -> None:
        """
        Initialize the AI cache.

        Args:
            cache_type: Type of cache (e.g., "news", "soccer")
        """
        self.cache_type: str = cache_type
        self._db = get_db()

        # Cleanup old entries on startup
        self._db.cleanup_ai_cache()

        logger.debug("AI Cache Initialized", [
            ("Type", cache_type),
            ("Backend", "SQLite"),
        ])

    def get(self, key: str) -> Optional[str]:
        """
        Get a cached value if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired
        """
        return self._db.get_ai_cache(self.cache_type, key)

    def set(self, key: str, value: str) -> None:
        """
        Set a cache value with timestamp.

        Args:
            key: Cache key
            value: Value to cache
        """
        self._db.set_ai_cache(self.cache_type, key, value)

    def clear(self) -> None:
        """Clear all cached values for this type."""
        self._db.execute(
            "DELETE FROM ai_cache WHERE cache_type = ?",
            (self.cache_type,)
        )
        logger.info("AI Cache Cleared", [("Type", self.cache_type)])

    # -------------------------------------------------------------------------
    # Title Cache Methods
    # -------------------------------------------------------------------------

    def get_title(self, article_id: str) -> Optional[dict[str, str]]:
        """
        Get cached title for an article.

        Args:
            article_id: Unique article identifier

        Returns:
            Dict with 'original_title' and 'english_title' keys, or None if not cached
        """
        key = f"title:{article_id}"
        cached = self.get(key)
        if cached:
            parts = cached.split("|||", 1)
            if len(parts) == 2:
                logger.debug("AI Cache HIT: Title", [
                    ("Article", article_id[:30]),
                ])
                return {"original_title": parts[0], "english_title": parts[1]}
        logger.debug("AI Cache MISS: Title", [
            ("Article", article_id[:30]),
        ])
        return None

    def cache_title(self, article_id: str, original_title: str, ai_title: str) -> None:
        """
        Cache title for an article.

        Args:
            article_id: Unique article identifier
            original_title: Original article title
            ai_title: AI-cleaned/translated title
        """
        key = f"title:{article_id}"
        self.set(key, f"{original_title}|||{ai_title}")

    # -------------------------------------------------------------------------
    # Summary Cache Methods
    # -------------------------------------------------------------------------

    def get_summary(self, article_id: str) -> Optional[dict[str, str]]:
        """
        Get cached summary for an article.

        Args:
            article_id: Unique article identifier

        Returns:
            Dict with 'arabic_summary' and 'english_summary' keys, or None if not cached
        """
        key = f"summary:{article_id}"
        cached = self.get(key)
        if cached:
            parts = cached.split("|||", 1)
            if len(parts) == 2:
                logger.debug("AI Cache HIT: Summary", [
                    ("Article", article_id[:30]),
                ])
                return {"arabic_summary": parts[0], "english_summary": parts[1]}
        logger.debug("AI Cache MISS: Summary", [
            ("Article", article_id[:30]),
        ])
        return None

    def cache_summary(self, article_id: str, arabic_summary: str, english_summary: str) -> None:
        """
        Cache summary for an article.

        Args:
            article_id: Unique article identifier
            arabic_summary: Arabic summary text
            english_summary: English summary text
        """
        key = f"summary:{article_id}"
        self.set(key, f"{arabic_summary}|||{english_summary}")

    # -------------------------------------------------------------------------
    # Team Tag Cache Methods (for soccer articles)
    # -------------------------------------------------------------------------

    def get_team_tag(self, article_id: str) -> Optional[str]:
        """
        Get cached team tag for an article.

        Args:
            article_id: Unique article identifier

        Returns:
            Team tag string or None if not cached
        """
        key = f"team:{article_id}"
        result = self.get(key)
        if result:
            logger.debug("AI Cache HIT: Team Tag", [
                ("Article", article_id[:30]),
                ("Team", result),
            ])
        else:
            logger.debug("AI Cache MISS: Team Tag", [
                ("Article", article_id[:30]),
            ])
        return result

    def cache_team_tag(self, article_id: str, team_tag: str) -> None:
        """
        Cache team tag for an article.

        Args:
            article_id: Unique article identifier
            team_tag: Team tag (e.g., "Real Madrid", "Barcelona")
        """
        key = f"team:{article_id}"
        self.set(key, team_tag)


__all__ = ["AICache"]
