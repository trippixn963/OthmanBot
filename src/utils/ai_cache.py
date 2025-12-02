"""
Othman Discord Bot - AI Cache Utility
======================================

JSON-based cache for AI-generated responses to reduce API costs.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
from pathlib import Path
from typing import Optional

from src.core.logger import logger


class AICache:
    """
    Simple JSON-based cache for AI responses.

    Stores AI-generated content (titles, summaries) to avoid
    redundant OpenAI API calls for the same content.
    """

    def __init__(self, filename: str) -> None:
        """
        Initialize the AI cache.

        Args:
            filename: Path to JSON cache file (e.g., "data/news_ai_cache.json")
        """
        self.cache_file: Path = Path(filename)
        self.cache_file.parent.mkdir(exist_ok=True)
        self.cache: dict[str, str] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
                logger.debug(f"Loaded {len(self.cache)} cached AI responses")
        except Exception as e:
            logger.warning(f"Failed to load AI cache: {e}")
            self.cache = {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save AI cache: {e}")

    def get(self, key: str) -> Optional[str]:
        """
        Get a cached value.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        return self.cache.get(key)

    def set(self, key: str, value: str) -> None:
        """
        Set a cache value.

        Args:
            key: Cache key
            value: Value to cache
        """
        self.cache[key] = value
        self._save_cache()

    def clear(self) -> None:
        """Clear all cached values."""
        self.cache = {}
        self._save_cache()
        logger.info("AI cache cleared")

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
        cached = self.cache.get(key)
        if cached:
            parts = cached.split("|||", 1)
            if len(parts) == 2:
                return {"original_title": parts[0], "english_title": parts[1]}
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
        self.cache[key] = f"{original_title}|||{ai_title}"
        self._save_cache()

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
        cached = self.cache.get(key)
        if cached:
            parts = cached.split("|||", 1)
            if len(parts) == 2:
                return {"arabic_summary": parts[0], "english_summary": parts[1]}
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
        self.cache[key] = f"{arabic_summary}|||{english_summary}"
        self._save_cache()

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
        return self.cache.get(key)

    def cache_team_tag(self, article_id: str, team_tag: str) -> None:
        """
        Cache team tag for an article.

        Args:
            article_id: Unique article identifier
            team_tag: Team tag (e.g., "Real Madrid", "Barcelona")
        """
        key = f"team:{article_id}"
        self.cache[key] = team_tag
        self._save_cache()


__all__ = ["AICache"]
