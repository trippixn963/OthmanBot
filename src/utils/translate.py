"""
OthmanBot - Translation Utility
===============================

OpenAI-powered translation for non-English text.
Includes retry logic and circuit breaker for reliability.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import threading
import time
from openai import AsyncOpenAI, RateLimitError, APIConnectionError, APIError, AuthenticationError
from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

TRANSLATE_MAX_RETRIES: int = 3
"""Maximum number of retry attempts for translation."""

TRANSLATE_BASE_DELAY: float = 2.0
"""Base delay in seconds between retries."""

# Circuit breaker configuration
FAILURE_THRESHOLD: int = 5
RECOVERY_TIMEOUT: float = 60.0

# Circuit breaker state (thread-safe with lock)
_circuit_lock = threading.Lock()
_failure_count: int = 0
_last_failure_time: float = 0.0
_circuit_open: bool = False


# =============================================================================
# Circuit Breaker Helpers
# =============================================================================

def _check_circuit() -> bool:
    """Check if circuit is open. Returns True if requests should be blocked."""
    global _circuit_open, _failure_count, _last_failure_time

    with _circuit_lock:
        if not _circuit_open:
            return False

        # Check for recovery
        elapsed = time.time() - _last_failure_time
        if elapsed >= RECOVERY_TIMEOUT:
            logger.info("Translation Circuit Half-Open (Testing Recovery)", [
                ("Elapsed", f"{elapsed:.1f}s"),
                ("Recovery Timeout", f"{RECOVERY_TIMEOUT}s"),
            ])
            return False

        return True


def _record_success() -> None:
    """Record a successful translation."""
    global _failure_count, _circuit_open

    with _circuit_lock:
        _failure_count = 0
        if _circuit_open:
            _circuit_open = False
            logger.info("Translation Circuit Closed (Recovered)", [
                ("Status", "Circuit recovered"),
            ])


def _record_failure() -> None:
    """Record a failed translation."""
    global _failure_count, _last_failure_time, _circuit_open

    with _circuit_lock:
        _failure_count += 1
        _last_failure_time = time.time()

        if _failure_count >= FAILURE_THRESHOLD:
            _circuit_open = True
            logger.warning("Translation Circuit Opened", [
                ("Failures", str(_failure_count)),
                ("Timeout", f"{RECOVERY_TIMEOUT}s"),
            ])


# =============================================================================
# Translation Function
# =============================================================================

async def translate_to_english(text: str) -> str:
    """
    Translate non-English text to English using OpenAI.

    Args:
        text: The text to translate

    Returns:
        English translation of the text, or error message on failure

    DESIGN: Uses retry with exponential backoff for transient errors.
    Circuit breaker prevents hammering a failing service.
    Uses async/await to avoid blocking the event loop.
    """
    # Check circuit breaker
    if _check_circuit():
        logger.debug("Translation Skipped (Circuit Open)", [
            ("Reason", "Circuit breaker active"),
        ])
        return "Error: Translation service temporarily unavailable"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY Not Found", [
            ("Env Var", "OPENAI_API_KEY"),
            ("Action", "Translation unavailable"),
        ])
        return "Error: Translation service unavailable"

    client = AsyncOpenAI(api_key=api_key, timeout=30.0)
    last_error: Exception | None = None

    for attempt in range(TRANSLATE_MAX_RETRIES):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",  # Fast and cheap model for translations
                messages=[
                    {
                        "role": "system",
                        "content": "You are a translator. Translate the following text to English. Output ONLY the English translation, nothing else. Keep it concise and natural."
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                max_tokens=100,
                temperature=0.3  # Low temperature for consistent translations
            )

            translation = response.choices[0].message.content.strip()
            logger.info("Translation Complete", [
                ("Original", text[:50]),
                ("Result", translation[:50]),
            ])
            _record_success()
            return translation

        except AuthenticationError as e:
            # Don't retry auth errors
            logger.error("Translation Auth Error", [("Error", str(e))])
            return "Error: Translation service misconfigured"

        except (RateLimitError, APIConnectionError, APIError) as e:
            last_error = e
            if attempt < TRANSLATE_MAX_RETRIES - 1:
                delay = TRANSLATE_BASE_DELAY * (2 ** attempt)
                logger.warning("Translation Retry", [
                    ("Attempt", f"{attempt + 1}/{TRANSLATE_MAX_RETRIES}"),
                    ("Error", str(e)[:50]),
                    ("Delay", f"{delay:.1f}s"),
                ])
                await asyncio.sleep(delay)
            continue

        except Exception as e:
            last_error = e
            break

    # All retries failed
    _record_failure()
    logger.error("Failed To Translate Text", [
        ("Error", str(last_error) if last_error else "Unknown"),
        ("Attempts", str(TRANSLATE_MAX_RETRIES)),
    ])
    return "Error: Could not translate title"


__all__ = ["translate_to_english"]
