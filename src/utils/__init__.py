"""
OthmanBot - Utilities Package
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
    get_ordinal,
    sanitize_input,
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
from .error_handler import (
    send_error_response,
    handle_command_errors,
    safe_api_call,
)
from .embed_factory import (
    create_embed,
    create_success_embed,
    create_error_embed,
    create_warning_embed,
    create_info_embed,
    create_ban_embed,
    create_unban_embed,
    add_timestamp_field,
    format_discord_timestamp,
)
from .duration import (
    parse_duration,
    format_duration,
    get_remaining_duration,
    DURATION_SUGGESTIONS,
)
from .api_cache import (
    ResponseCache,
    RateLimiter,
)
from .autocomplete import (
    thread_id_autocomplete,
    duration_autocomplete,
    banned_user_autocomplete,
    case_search_autocomplete,
)
from .similarity import (
    cosine_similarity,
    is_duplicate_content,
    SIMILARITY_THRESHOLD,
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
    # Number formatting helpers
    "get_ordinal",
    # Input sanitization
    "sanitize_input",
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
    # Error handling utilities
    "send_error_response",
    "handle_command_errors",
    "safe_api_call",
    # Embed factory utilities
    "create_embed",
    "create_success_embed",
    "create_error_embed",
    "create_warning_embed",
    "create_info_embed",
    "create_ban_embed",
    "create_unban_embed",
    "add_timestamp_field",
    "format_discord_timestamp",
    # Duration utilities
    "parse_duration",
    "format_duration",
    "get_remaining_duration",
    "DURATION_SUGGESTIONS",
    # API cache utilities
    "ResponseCache",
    "RateLimiter",
    # Autocomplete utilities
    "thread_id_autocomplete",
    "duration_autocomplete",
    "banned_user_autocomplete",
    "case_search_autocomplete",
    # Similarity utilities
    "cosine_similarity",
    "is_duplicate_content",
    "SIMILARITY_THRESHOLD",
]
