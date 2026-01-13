"""
OthmanBot - Constants
=====================

Centralized constants for Discord API limits and magic numbers.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""


# =============================================================================
# Discord API Limits
# =============================================================================

DISCORD_CHANNEL_NAME_LIMIT = 100
DISCORD_ROLE_NAME_LIMIT = 100
DISCORD_THREAD_NAME_LIMIT = 100
DISCORD_EMBED_TITLE_LIMIT = 256
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FIELD_NAME_LIMIT = 256
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_FOOTER_LIMIT = 2048
DISCORD_MESSAGE_LIMIT = 2000


# =============================================================================
# Display Truncation Lengths
# =============================================================================

THREAD_NAME_PREVIEW_LENGTH = 30
USER_NAME_TRUNCATION_LENGTH = 50
LOG_MESSAGE_TRUNCATION_LENGTH = 100
REASON_TRUNCATION_LENGTH = 200


# =============================================================================
# Timing Constants
# =============================================================================

TEMP_FILE_MAX_AGE_HOURS = 24
LOG_RETENTION_DAYS = 7
CACHE_CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes


# =============================================================================
# API Constants
# =============================================================================

DEFAULT_CACHE_TTL_SECONDS = 30
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
DEFAULT_BURST_LIMIT = 10


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Discord limits
    "DISCORD_CHANNEL_NAME_LIMIT",
    "DISCORD_ROLE_NAME_LIMIT",
    "DISCORD_THREAD_NAME_LIMIT",
    "DISCORD_EMBED_TITLE_LIMIT",
    "DISCORD_EMBED_DESCRIPTION_LIMIT",
    "DISCORD_EMBED_FIELD_NAME_LIMIT",
    "DISCORD_EMBED_FIELD_VALUE_LIMIT",
    "DISCORD_EMBED_FOOTER_LIMIT",
    "DISCORD_MESSAGE_LIMIT",
    # Truncation lengths
    "THREAD_NAME_PREVIEW_LENGTH",
    "USER_NAME_TRUNCATION_LENGTH",
    "LOG_MESSAGE_TRUNCATION_LENGTH",
    "REASON_TRUNCATION_LENGTH",
    # Timing
    "TEMP_FILE_MAX_AGE_HOURS",
    "LOG_RETENTION_DAYS",
    "CACHE_CLEANUP_INTERVAL_SECONDS",
    # API
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "DEFAULT_BURST_LIMIT",
]
