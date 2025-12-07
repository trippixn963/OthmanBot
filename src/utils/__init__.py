"""
Othman Discord Bot - Utilities Package
======================================

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .retry import exponential_backoff
from .ai_cache import AICache
from .translate import translate_to_english
from .helpers import get_developer_avatar
from .discord_rate_limit import (
    RateLimitConfig,
    with_rate_limit_retry,
    add_reactions_with_delay,
    send_message_with_retry,
    edit_message_with_retry,
    edit_thread_with_retry,
    delete_message_safe,
    remove_reaction_safe,
)

__all__ = [
    "exponential_backoff",
    "AICache",
    "translate_to_english",
    "get_developer_avatar",
    # Discord rate limit utilities
    "RateLimitConfig",
    "with_rate_limit_retry",
    "add_reactions_with_delay",
    "send_message_with_retry",
    "edit_message_with_retry",
    "edit_thread_with_retry",
    "delete_message_safe",
    "remove_reaction_safe",
]
