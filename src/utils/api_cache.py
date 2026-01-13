"""
OthmanBot - API Cache and Rate Limiting Utilities
=================================================

Reusable caching and rate limiting for HTTP APIs.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from collections import defaultdict
from typing import Optional

from src.core.constants import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    DEFAULT_BURST_LIMIT,
)


# =============================================================================
# Response Cache
# =============================================================================

class ResponseCache:
    """Simple in-memory cache for API responses with TTL."""

    def __init__(self, ttl: int = DEFAULT_CACHE_TTL_SECONDS):
        """
        Initialize cache with TTL.

        Args:
            ttl: Time-to-live in seconds for cached entries
        """
        self.ttl = ttl
        self._cache: dict[str, tuple[dict, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[dict]:
        """
        Get cached response if still valid.

        Args:
            key: Cache key

        Returns:
            Cached data if valid, None otherwise
        """
        async with self._lock:
            if key in self._cache:
                data, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    return data
                del self._cache[key]
            return None

    async def set(self, key: str, data: dict) -> None:
        """
        Cache a response.

        Args:
            key: Cache key
            data: Data to cache
        """
        async with self._lock:
            self._cache[key] = (data, time.time())

    async def invalidate(self, key: str) -> None:
        """
        Invalidate a cached response.

        Args:
            key: Cache key to invalidate
        """
        async with self._lock:
            if key in self._cache:
                del self._cache[key]

    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._lock:
            self._cache.clear()

    async def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        async with self._lock:
            now = time.time()
            expired_keys = [
                key for key, (_, timestamp) in self._cache.items()
                if now - timestamp >= self.ttl
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(
        self,
        requests_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        burst_limit: int = DEFAULT_BURST_LIMIT
    ):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute
            burst_limit: Maximum requests allowed in 1 second burst
        """
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str) -> tuple[bool, Optional[int]]:
        """
        Check if request is allowed for this client.

        Args:
            client_id: Client identifier (IP, user ID, etc.)

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        async with self._lock:
            now = time.time()
            window_start = now - 60

            # Clean old requests
            self._requests[client_id] = [
                ts for ts in self._requests[client_id]
                if ts > window_start
            ]

            requests = self._requests[client_id]

            # Check per-minute limit
            if len(requests) >= self.requests_per_minute:
                oldest = min(requests) if requests else now
                retry_after = int(oldest + 60 - now) + 1
                return False, retry_after

            # Check burst limit (last 1 second)
            recent = [ts for ts in requests if ts > now - 1]
            if len(recent) >= self.burst_limit:
                return False, 1

            # Allow request
            self._requests[client_id].append(now)
            return True, None

    async def cleanup(self) -> int:
        """
        Remove stale entries older than 2 minutes.

        Returns:
            Number of clients removed
        """
        async with self._lock:
            cutoff = time.time() - 120
            stale_clients = [
                client_id for client_id, timestamps in self._requests.items()
                if not timestamps or max(timestamps) < cutoff
            ]
            for client_id in stale_clients:
                del self._requests[client_id]
            return len(stale_clients)

    async def get_remaining(self, client_id: str) -> int:
        """
        Get remaining requests for this client.

        Args:
            client_id: Client identifier

        Returns:
            Number of remaining requests allowed
        """
        async with self._lock:
            now = time.time()
            window_start = now - 60
            requests = [
                ts for ts in self._requests.get(client_id, [])
                if ts > window_start
            ]
            return max(0, self.requests_per_minute - len(requests))


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "ResponseCache",
    "RateLimiter",
]
