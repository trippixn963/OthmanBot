"""
Othman Discord Bot - Retry Utilities
====================================

Exponential backoff retry decorator for handling transient failures.

Features:
- Configurable retry attempts (default: 3)
- Exponential backoff: 10s → 20s → 40s
- Comprehensive error logging
- Preserves function metadata
- Type-safe with proper annotations

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import aiohttp
import random
from functools import wraps
from typing import Callable, Any, Optional

import discord

from src.core.logger import logger


# Specific exceptions that should be retried (transient errors)
RETRYABLE_EXCEPTIONS = (
    aiohttp.ClientError,
    discord.HTTPException,
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
)


def exponential_backoff(
    max_retries: int = 3,
    base_delay: float = 10.0,
    max_delay: float = 60.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that retries async functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 10)
        max_delay: Maximum delay cap in seconds (default: 60)

    Returns:
        Decorated function with retry logic

    Example:
        @exponential_backoff(max_retries=3, base_delay=10)
        async def post_news():
            # ... posting logic ...
            pass

    DESIGN: Exponential backoff formula: delay = min(base_delay * (2 ** attempt), max_delay)
    Example with base_delay=10: 10s → 20s → 40s (capped at max_delay)
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap async function with exponential backoff retry logic."""
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute wrapped function with automatic retry on failure."""
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    # DESIGN: Try executing the function
                    # First attempt (attempt=0) happens immediately
                    # Subsequent attempts happen after backoff delay
                    return await func(*args, **kwargs)

                except RETRYABLE_EXCEPTIONS as e:
                    # Only retry transient/network errors
                    last_exception = e

                    # DESIGN: If this was the last attempt, re-raise exception
                    # No point delaying if we're out of retries
                    if attempt == max_retries - 1:
                        logger.error(
                            f"❌ {func.__name__} failed after {max_retries} attempts: {e}"
                        )
                        raise

                    # DESIGN: Calculate exponential backoff delay with jitter
                    # attempt=0: delay = 10s
                    # attempt=1: delay = 20s
                    # attempt=2: delay = 40s
                    # Capped at max_delay to prevent excessive waits
                    delay: float = min(base_delay * (2**attempt), max_delay)
                    # Add jitter (0-10% of delay) to prevent thundering herd
                    delay += random.uniform(0, delay * 0.1)

                    logger.warning("⚠️ Retry Attempt Failed", [
                        ("Function", func.__name__),
                        ("Attempt", f"{attempt + 1}/{max_retries}"),
                        ("Error", str(e)),
                    ])
                    logger.info("🔄 Retrying", [
                        ("Delay", f"{delay:.1f}s"),
                    ])

                    # DESIGN: Wait before retrying
                    # asyncio.sleep is non-blocking, allows other tasks to run
                    await asyncio.sleep(delay)

            # DESIGN: This should never be reached due to raise in loop
            # But type checker requires it for proper return type
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        return wrapper

    return decorator
