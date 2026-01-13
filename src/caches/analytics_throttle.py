"""
OthmanBot - Analytics Throttle Cache
====================================

Thread-safe cache for throttling analytics embed updates.
Prevents excessive updates by enforcing a cooldown period.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict

from src.core.logger import logger
from src.core.config import (
    NY_TZ,
    ANALYTICS_UPDATE_COOLDOWN,
    ANALYTICS_CACHE_MAX_SIZE,
    ANALYTICS_CACHE_CLEANUP_AGE,
)


# =============================================================================
# Analytics Throttle Cache
# =============================================================================

class AnalyticsThrottleCache:
    """
    Thread-safe cache for throttling analytics updates.

    Prevents excessive updates to analytics embeds by tracking the last update
    time for each thread and enforcing a cooldown period.

    DESIGN: Encapsulates global state (_analytics_last_update, _analytics_lock)
    into a proper class with methods for checking/recording updates and cleanup.
    """

    def __init__(
        self,
        cooldown_seconds: int = ANALYTICS_UPDATE_COOLDOWN,
        max_size: int = ANALYTICS_CACHE_MAX_SIZE,
        cleanup_age_seconds: int = ANALYTICS_CACHE_CLEANUP_AGE,
    ) -> None:
        """
        Initialize the throttle cache.

        Args:
            cooldown_seconds: Minimum seconds between updates for same thread
            max_size: Maximum number of entries before cleanup
            cleanup_age_seconds: Remove entries older than this
        """
        self._last_update: Dict[int, datetime] = {}
        self._lock = asyncio.Lock()
        self._cooldown = cooldown_seconds
        self._max_size = max_size
        self._cleanup_age = cleanup_age_seconds

    async def should_update(self, thread_id: int) -> bool:
        """
        Check if enough time has passed since last update for this thread.

        Args:
            thread_id: The thread ID to check

        Returns:
            True if update is allowed, False if still in cooldown
        """
        async with self._lock:
            last_update = self._last_update.get(thread_id)
            if last_update is None:
                return True

            elapsed = (datetime.now(NY_TZ) - last_update).total_seconds()
            if elapsed < self._cooldown:
                logger.debug("Throttled Analytics Update", [
                    ("Thread ID", str(thread_id)),
                    ("Elapsed", f"{elapsed:.0f}s"),
                    ("Cooldown", f"{self._cooldown}s"),
                ])
                return False
            return True

    async def record_update(self, thread_id: int) -> None:
        """
        Record that an analytics update was performed for this thread.

        Args:
            thread_id: The thread ID that was updated
        """
        async with self._lock:
            self._last_update[thread_id] = datetime.now(NY_TZ)
            await self._cleanup_unlocked()

    async def _cleanup_unlocked(self) -> None:
        """
        Remove stale entries from cache. Must be called with lock held.
        Uses atomic dict replacement to avoid modification during iteration.
        """
        now = datetime.now(NY_TZ)
        stale_threshold = now - timedelta(seconds=self._cleanup_age)

        # Build new dict with only fresh entries (atomic replacement)
        fresh_entries = {
            thread_id: last_update
            for thread_id, last_update in self._last_update.items()
            if last_update >= stale_threshold
        }

        removed_count = len(self._last_update) - len(fresh_entries)

        # If still over max, keep only the newest entries
        if len(fresh_entries) > self._max_size:
            sorted_entries = sorted(fresh_entries.items(), key=lambda x: x[1], reverse=True)
            extra_removed = len(fresh_entries) - self._max_size
            fresh_entries = dict(sorted_entries[:self._max_size])
            removed_count += extra_removed

        # Atomic replacement
        self._last_update = fresh_entries

        if removed_count > 0:
            logger.debug("Cleaned Analytics Cache", [
                ("Removed", str(removed_count)),
                ("Remaining", str(len(self._last_update))),
            ])

    @property
    def size(self) -> int:
        """Return current cache size (for monitoring)."""
        return len(self._last_update)


# =============================================================================
# Module-level Instance
# =============================================================================

# Singleton instance (initialized once, used throughout)
analytics_throttle_cache = AnalyticsThrottleCache()


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "AnalyticsThrottleCache",
    "analytics_throttle_cache",
]
