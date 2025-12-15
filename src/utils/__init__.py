"""
Othman Discord Bot - Utilities Package
======================================

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .retry import (
    exponential_backoff,
    retry_async,
    CircuitBreaker,
    CircuitOpenError,
    get_circuit_breaker,
    send_webhook_alert_safe,
    RETRYABLE_EXCEPTIONS,
    OPENAI_RETRYABLE_EXCEPTIONS,
)
from .ai_cache import AICache
from .translate import translate_to_english
from .helpers import (
    get_developer_avatar,
    safe_fetch_message,
    truncate,
)
from .language import (
    is_primarily_arabic,
    get_min_message_length,
    is_english_only,
)
from .discord_rate_limit import (
    add_reactions_with_delay,
    send_message_with_retry,
    edit_message_with_retry,
    edit_thread_with_retry,
    delete_message_safe,
    remove_reaction_safe,
)

__all__ = [
    # Retry and circuit breaker utilities
    "exponential_backoff",
    "retry_async",
    "CircuitBreaker",
    "CircuitOpenError",
    "get_circuit_breaker",
    "send_webhook_alert_safe",
    "RETRYABLE_EXCEPTIONS",
    "OPENAI_RETRYABLE_EXCEPTIONS",
    # AI utilities
    "AICache",
    "translate_to_english",
    "get_developer_avatar",
    # Safe fetch helpers
    "safe_fetch_message",
    # String truncation helpers
    "truncate",
    # Language utilities
    "is_primarily_arabic",
    "get_min_message_length",
    "is_english_only",
    # Discord rate limit utilities
    "add_reactions_with_delay",
    "send_message_with_retry",
    "edit_message_with_retry",
    "edit_thread_with_retry",
    "delete_message_safe",
    "remove_reaction_safe",
]
