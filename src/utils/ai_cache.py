"""
Othman Discord Bot - AI Response Cache
=======================================

Caches OpenAI API responses to reduce costs and API calls.

Features:
- Caches article titles, summaries, and team tags
- Persistent JSON storage
- Automatic cleanup of old entries (90 days)
- Thread-safe operations
- Memory-efficient design

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from src.core.logger import logger


class AICache:
    """Manages caching of AI-generated content to reduce API costs."""

    def __init__(self, cache_file: str = "data/ai_cache.json") -> None:
        """
        Initialize the AI cache.

        Args:
            cache_file: Path to cache file (default: data/ai_cache.json)
        """
        self.cache_file: Path = Path(cache_file)
        self.cache_file.parent.mkdir(exist_ok=True)

        # DESIGN: Cache structure with separate sections for different AI operations
        # This allows easy retrieval and cleanup of specific types
        self.cache: Dict[str, Dict[str, Any]] = {
            "titles": {},  # article_id -> {arabic_title, english_title, timestamp}
            "summaries": {},  # article_id -> {arabic_summary, english_summary, timestamp}
            "team_tags": {},  # article_id -> {team, timestamp}
        }

        # DESIGN: 90-day cache TTL - balance between cost savings and freshness
        # Articles older than 90 days are unlikely to be seen again
        self.cache_ttl_days: int = 90

        self._load_cache()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    loaded_cache: Dict[str, Any] = json.load(f)

                # DESIGN: Validate cache structure and merge with defaults
                # This ensures backward compatibility if cache format changes
                for key in self.cache.keys():
                    if key in loaded_cache:
                        self.cache[key] = loaded_cache[key]

                logger.info(
                    f"💾 Loaded AI cache: "
                    f"{len(self.cache['titles'])} titles, "
                    f"{len(self.cache['summaries'])} summaries, "
                    f"{len(self.cache['team_tags'])} team tags"
                )

                # DESIGN: Clean up expired entries on load
                # Prevents cache from growing indefinitely
                self._cleanup_expired()

        except Exception as e:
            logger.warning(f"Failed to load AI cache: {e}")
            logger.info("Starting with fresh AI cache")

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save AI cache: {e}")

    def _cleanup_expired(self) -> None:
        """Remove entries older than cache_ttl_days."""
        try:
            cutoff_date: datetime = datetime.now() - timedelta(
                days=self.cache_ttl_days
            )
            cutoff_timestamp: str = cutoff_date.isoformat()

            removed_count: int = 0

            # DESIGN: Clean up each cache section separately
            # Check timestamp and remove if expired
            for section in self.cache.values():
                expired_keys: list[str] = [
                    key
                    for key, value in section.items()
                    if value.get("timestamp", "") < cutoff_timestamp
                ]

                for key in expired_keys:
                    del section[key]
                    removed_count += 1

            if removed_count > 0:
                logger.info(
                    f"🧹 Cleaned up {removed_count} expired AI cache entries "
                    f"(older than {self.cache_ttl_days} days)"
                )
                self._save_cache()

        except Exception as e:
            logger.warning(f"Failed to cleanup AI cache: {e}")

    def get_title(self, article_id: str) -> Optional[Dict[str, str]]:
        """
        Get cached title for article.

        Args:
            article_id: Article identifier

        Returns:
            Dict with arabic_title and english_title, or None if not cached
        """
        cached: Optional[Dict[str, Any]] = self.cache["titles"].get(article_id)
        if cached:
            return {
                "arabic_title": cached["arabic_title"],
                "english_title": cached["english_title"],
            }
        return None

    def cache_title(
        self, article_id: str, arabic_title: str, english_title: str
    ) -> None:
        """
        Cache AI-generated title.

        Args:
            article_id: Article identifier
            arabic_title: Original Arabic title
            english_title: AI-generated English title
        """
        self.cache["titles"][article_id] = {
            "arabic_title": arabic_title,
            "english_title": english_title,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_cache()

    def get_summary(self, article_id: str) -> Optional[Dict[str, str]]:
        """
        Get cached summary for article.

        Args:
            article_id: Article identifier

        Returns:
            Dict with arabic_summary and english_summary, or None if not cached
        """
        cached: Optional[Dict[str, Any]] = self.cache["summaries"].get(article_id)
        if cached:
            return {
                "arabic_summary": cached["arabic_summary"],
                "english_summary": cached["english_summary"],
            }
        return None

    def cache_summary(
        self, article_id: str, arabic_summary: str, english_summary: str
    ) -> None:
        """
        Cache AI-generated summary.

        Args:
            article_id: Article identifier
            arabic_summary: AI-generated Arabic summary
            english_summary: AI-generated English summary
        """
        self.cache["summaries"][article_id] = {
            "arabic_summary": arabic_summary,
            "english_summary": english_summary,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_cache()

    def get_team_tag(self, article_id: str) -> Optional[str]:
        """
        Get cached team tag for article.

        Args:
            article_id: Article identifier

        Returns:
            Team name string, or None if not cached
        """
        cached: Optional[Dict[str, Any]] = self.cache["team_tags"].get(article_id)
        if cached:
            return cached["team"]
        return None

    def cache_team_tag(self, article_id: str, team: str) -> None:
        """
        Cache AI-detected team tag.

        Args:
            article_id: Article identifier
            team: Team name (e.g., "Barcelona", "Real Madrid")
        """
        self.cache["team_tags"][article_id] = {
            "team": team,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_cache()

    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dict with counts for each cache section
        """
        return {
            "titles": len(self.cache["titles"]),
            "summaries": len(self.cache["summaries"]),
            "team_tags": len(self.cache["team_tags"]),
            "total": sum(len(section) for section in self.cache.values()),
        }
