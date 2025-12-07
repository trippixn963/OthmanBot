"""
Othman Discord Bot - AI Cache Utility
======================================

JSON-based cache for AI-generated responses to reduce API costs.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import time
from pathlib import Path
from typing import Optional

from src.core.logger import logger


# Cache expiration (30 days in seconds)
CACHE_EXPIRATION_SECONDS: int = 30 * 24 * 60 * 60


class AICache:
    """
    Simple JSON-based cache for AI responses.

    Stores AI-generated content (titles, summaries) to avoid
    redundant OpenAI API calls for the same content.

    Automatically cleans up old entries when max size is exceeded
    or when entries are older than CACHE_EXPIRATION_SECONDS.
    """

    MAX_ENTRIES = 5000  # Maximum cache entries before cleanup

    def __init__(self, filename: str) -> None:
        """
        Initialize the AI cache.

        Args:
            filename: Path to JSON cache file (e.g., "data/news_ai_cache.json")
        """
        self.cache_file: Path = Path(filename)
        self.cache_file.parent.mkdir(exist_ok=True)
        # Cache stores {key: {"value": str, "timestamp": float}}
        self.cache: dict[str, dict] = {}
        self._load_cache()
        self._cleanup_if_needed()

    def _load_cache(self) -> None:
        """Load cache from disk and migrate old format if needed."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    raw_cache = json.load(f)

                # Migrate old format (string values) to new format (dict with timestamp)
                migrated = False
                for key, value in raw_cache.items():
                    if isinstance(value, str):
                        # Old format: migrate to new format with current timestamp
                        raw_cache[key] = {"value": value, "timestamp": time.time()}
                        migrated = True

                self.cache = raw_cache

                if migrated:
                    self._save_cache()
                    logger.info("Migrated AI Cache To New Format", [
                        ("Entries", str(len(self.cache))),
                    ])
                else:
                    logger.debug("Loaded AI Cache", [
                        ("Entries", str(len(self.cache))),
                    ])
        except Exception as e:
            logger.warning("Failed To Load AI Cache", [
                ("Error", str(e)),
            ])
            self.cache = {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed To Save AI Cache", [
                ("Error", str(e)),
            ])

    def _cleanup_if_needed(self) -> None:
        """Remove expired and oldest entries to prevent memory leaks."""
        current_time = time.time()
        initial_count = len(self.cache)

        # First, remove expired entries (use list() to create snapshot and avoid dict size change during iteration)
        expired_keys = [
            key for key, entry in list(self.cache.items())
            if isinstance(entry, dict) and current_time - entry.get("timestamp", 0) > CACHE_EXPIRATION_SECONDS
        ]
        for key in expired_keys:
            del self.cache[key]

        # Then, if still over limit, remove oldest entries by timestamp
        if len(self.cache) > self.MAX_ENTRIES:
            # Sort by timestamp and remove oldest 20% (use list() to avoid dict modification during iteration)
            sorted_entries = sorted(
                list(self.cache.items()),
                key=lambda x: x[1].get("timestamp", 0) if isinstance(x[1], dict) else 0
            )
            entries_to_remove = len(self.cache) - int(self.MAX_ENTRIES * 0.8)
            keys_to_remove = [key for key, _ in sorted_entries[:entries_to_remove]]

            for key in keys_to_remove:
                del self.cache[key]

        removed_count = initial_count - len(self.cache)
        if removed_count > 0:
            self._save_cache()
            logger.info("🧹 Cleaned AI Cache", [
                ("File", str(self.cache_file)),
                ("Expired", str(len(expired_keys))),
                ("Total Removed", str(removed_count)),
                ("Remaining", str(len(self.cache))),
            ])

    def get(self, key: str) -> Optional[str]:
        """
        Get a cached value if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired
        """
        entry = self.cache.get(key)
        if entry is None:
            return None

        # Handle new format with timestamp
        if isinstance(entry, dict):
            timestamp = entry.get("timestamp", 0)
            if time.time() - timestamp > CACHE_EXPIRATION_SECONDS:
                # Entry expired, remove it
                del self.cache[key]
                return None
            return entry.get("value")

        # Handle old format (string) for backward compatibility
        return entry

    def set(self, key: str, value: str) -> None:
        """
        Set a cache value with timestamp.

        Args:
            key: Cache key
            value: Value to cache
        """
        self.cache[key] = {"value": value, "timestamp": time.time()}
        self._save_cache()
        self._cleanup_if_needed()

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
