"""
OthmanBot - Ban Evasion Alert Cache
===================================

Time-based cache for tracking ban evasion alerts.
Prevents alert spam by remembering which users have been flagged.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import threading
from datetime import datetime, timedelta
from typing import Dict

from src.core.config import NY_TZ


# =============================================================================
# Constants
# =============================================================================

# Ban evasion detection - accounts younger than this are flagged
BAN_EVASION_ACCOUNT_AGE_DAYS = 7

# How long to remember ban evasion alerts (24 hours)
BAN_EVASION_ALERT_EXPIRY_HOURS = 24


# =============================================================================
# Ban Evasion Alert Cache
# =============================================================================

class BanEvasionAlertCache:
    """
    Time-based cache for tracking ban evasion alerts.

    Prevents alert spam by remembering which users have been flagged,
    but automatically expires entries after a configurable time period
    to prevent unbounded memory growth.

    DESIGN: Uses a dict mapping user_id -> alert_timestamp instead of a simple set.
    Cleanup happens periodically (every N checks) to balance memory vs performance.
    Thread-safe using a threading lock for concurrent access from async handlers.
    """

    # Cleanup every N checks instead of every check (O(n) optimization)
    CLEANUP_INTERVAL: int = 100
    MAX_SIZE_BEFORE_CLEANUP: int = 500

    def __init__(self, expiry_hours: int = BAN_EVASION_ALERT_EXPIRY_HOURS) -> None:
        """
        Initialize the alert cache.

        Args:
            expiry_hours: Hours before an alert entry expires and user can be re-alerted
        """
        self._lock = threading.Lock()
        self._alerts: Dict[int, datetime] = {}
        self._expiry = timedelta(hours=expiry_hours)
        self._check_count: int = 0

    def should_alert(self, user_id: int) -> bool:
        """
        Check if we should alert for this user.

        Performs cleanup periodically or when cache grows too large.
        Thread-safe.

        Args:
            user_id: Discord user ID to check

        Returns:
            True if we should send an alert, False if already alerted recently
        """
        with self._lock:
            self._check_count += 1

            # Cleanup periodically or when cache is large
            if (self._check_count >= self.CLEANUP_INTERVAL or
                    len(self._alerts) >= self.MAX_SIZE_BEFORE_CLEANUP):
                self._cleanup_unlocked()
                self._check_count = 0

            if user_id in self._alerts:
                # Check if this specific entry is expired
                alert_time = self._alerts[user_id]
                if datetime.now(NY_TZ) - alert_time > self._expiry:
                    del self._alerts[user_id]
                    return True
                return False  # Already alerted and not expired
            return True

    def record_alert(self, user_id: int) -> None:
        """
        Record that we've alerted about this user.
        Thread-safe.

        Args:
            user_id: Discord user ID that was flagged
        """
        with self._lock:
            self._alerts[user_id] = datetime.now(NY_TZ)

    def _cleanup_unlocked(self) -> None:
        """Remove expired entries from cache. Must be called with lock held."""
        now = datetime.now(NY_TZ)
        expired = [
            user_id for user_id, alert_time in self._alerts.items()
            if now - alert_time > self._expiry
        ]
        for user_id in expired:
            del self._alerts[user_id]

    @property
    def size(self) -> int:
        """Return current cache size (for monitoring)."""
        with self._lock:
            return len(self._alerts)


# =============================================================================
# Module-level Instance
# =============================================================================

# Singleton instance for ban evasion tracking
ban_evasion_cache = BanEvasionAlertCache()


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "BanEvasionAlertCache",
    "ban_evasion_cache",
    "BAN_EVASION_ACCOUNT_AGE_DAYS",
    "BAN_EVASION_ALERT_EXPIRY_HOURS",
]
