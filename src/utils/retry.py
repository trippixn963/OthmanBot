"""
OthmanBot - Retry Utilities
====================================

Exponential backoff retry decorator and circuit breaker for handling transient failures.

Features:
- Configurable retry attempts (default: 3)
- Exponential backoff: 10s → 20s → 40s
- Circuit breaker pattern for failing services
- Safe webhook logging helper
- Comprehensive error logging
- Preserves function metadata
- Type-safe with proper annotations

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import aiohttp
import random
import time
from functools import wraps
from typing import Callable, Any, Optional, TYPE_CHECKING

import discord
from openai import RateLimitError, APIConnectionError, APIError

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import OthmanBot


# Specific exceptions that should be retried (transient errors)
RETRYABLE_EXCEPTIONS = (
    aiohttp.ClientError,
    discord.HTTPException,
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
)

# OpenAI exceptions that should be retried
OPENAI_RETRYABLE_EXCEPTIONS = (
    RateLimitError,
    APIConnectionError,
    APIError,
    asyncio.TimeoutError,
    ConnectionError,
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


# =============================================================================
# Async Retry Helper (for inline retries)
# =============================================================================

async def retry_async(
    coro_func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exceptions: tuple = RETRYABLE_EXCEPTIONS,
    **kwargs: Any
) -> Any:
    """
    Retry an async function with exponential backoff.

    Args:
        coro_func: Async function to retry
        *args: Positional arguments to pass to the function
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        exceptions: Tuple of exception types to retry on
        **kwargs: Keyword arguments to pass to the function

    Returns:
        Result of the async function

    Raises:
        The last exception if all retries fail

    Example:
        result = await retry_async(
            session.get, url,
            max_retries=3,
            base_delay=1.0
        )
    """
    last_exception: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt == max_retries - 1:
                raise

            delay = min(base_delay * (2 ** attempt), max_delay)
            delay += random.uniform(0, delay * 0.1)

            logger.debug("Retry Async", [
                ("Attempt", f"{attempt + 1}/{max_retries}"),
                ("Error", str(e)[:50]),
                ("Delay", f"{delay:.1f}s"),
            ])
            await asyncio.sleep(delay)

    if last_exception:
        raise last_exception
    raise RuntimeError("retry_async failed without exception")


# =============================================================================
# Circuit Breaker Pattern
# =============================================================================

class CircuitBreaker:
    """
    Circuit breaker pattern for failing services.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, requests are rejected immediately
    - HALF_OPEN: Testing if service has recovered

    DESIGN: Prevents cascading failures by failing fast when a service is down.
    After a timeout period, allows a single request through to test recovery.
    """

    # States
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            name: Name of the service (for logging)
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery
            half_open_max_calls: Number of test calls allowed in half-open state
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        """Get current circuit state, checking for recovery timeout."""
        if self._state == self.OPEN:
            # Check if recovery timeout has passed
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = self.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Circuit Half-Open", [
                        ("Service", self.name),
                        ("Testing Recovery", "Yes"),
                    ])
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self.state == self.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (allowing requests)."""
        return self.state == self.CLOSED

    def can_execute(self) -> bool:
        """Check if a request can be executed."""
        state = self.state
        if state == self.CLOSED:
            return True
        if state == self.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False  # OPEN

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == self.HALF_OPEN:
            # Service recovered
            self._state = self.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            logger.info("Circuit Closed (Recovered)", [
                ("Service", self.name),
            ])
        elif self._state == self.CLOSED:
            # Reset failure count on success
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == self.HALF_OPEN:
            # Recovery test failed, reopen circuit
            self._state = self.OPEN
            logger.warning("Circuit Re-Opened (Recovery Failed)", [
                ("Service", self.name),
                ("Timeout", f"{self.recovery_timeout}s"),
            ])
        elif self._state == self.CLOSED and self._failure_count >= self.failure_threshold:
            # Threshold exceeded, open circuit
            self._state = self.OPEN
            logger.warning("Circuit Opened", [
                ("Service", self.name),
                ("Failures", str(self._failure_count)),
                ("Threshold", str(self.failure_threshold)),
                ("Timeout", f"{self.recovery_timeout}s"),
            ])

    async def execute(
        self,
        coro_func: Callable[..., Any],
        *args: Any,
        fallback: Optional[Callable[..., Any]] = None,
        **kwargs: Any
    ) -> Any:
        """
        Execute a coroutine with circuit breaker protection.

        Args:
            coro_func: Async function to execute
            *args: Positional arguments
            fallback: Optional fallback function if circuit is open
            **kwargs: Keyword arguments

        Returns:
            Result of coro_func or fallback

        Raises:
            CircuitOpenError: If circuit is open and no fallback provided
        """
        if not self.can_execute():
            if fallback:
                logger.debug("Circuit Open - Using Fallback", [
                    ("Service", self.name),
                ])
                return await fallback(*args, **kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(*args, **kwargs)
            raise CircuitOpenError(f"Circuit breaker '{self.name}' is open")

        if self._state == self.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await coro_func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and no fallback is provided."""
    pass


# =============================================================================
# Global Circuit Breakers
# =============================================================================

# Circuit breakers for external services
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0
) -> CircuitBreaker:
    """
    Get or create a circuit breaker for a service.

    Args:
        name: Service name (e.g., "openai", "news_api", "media_download")
        failure_threshold: Number of failures before opening
        recovery_timeout: Seconds before testing recovery

    Returns:
        CircuitBreaker instance
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout
        )
    return _circuit_breakers[name]


# =============================================================================
# Safe Webhook Alert Helper
# =============================================================================

async def send_webhook_alert_safe(
    bot: "OthmanBot",
    error_type: str,
    error_message: str
) -> None:
    """
    Safely send a webhook alert without raising exceptions.

    This consolidates the duplicate pattern:
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(...)
        except Exception as e:
            logger.debug(...)

    Args:
        bot: The OthmanBot instance
        error_type: Type of error (e.g., "Database Error", "API Error")
        error_message: Detailed error message
    """
    try:
        if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
            await bot.webhook_alerts.send_error_alert(error_type, error_message)
    except Exception as e:
        logger.debug("Webhook alert failed", [("Error", str(e))])


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "exponential_backoff",
    "retry_async",
    "CircuitBreaker",
    "CircuitOpenError",
    "get_circuit_breaker",
    "send_webhook_alert_safe",
    "RETRYABLE_EXCEPTIONS",
    "OPENAI_RETRYABLE_EXCEPTIONS",
]
