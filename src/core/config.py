"""
OthmanBot - Configuration Module
================================

Central configuration from environment variables.
Uses a frozen dataclass pattern for type-safe config access.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, Optional
from zoneinfo import ZoneInfo


# =============================================================================
# Directory Setup
# =============================================================================

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
LOGS_DIR = ROOT_DIR / "logs"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


# =============================================================================
# Environment Helper Functions
# =============================================================================

def _env(key: str, default: str = "") -> str:
    """Get environment variable with default."""
    return os.getenv(key, default)


def _env_required(key: str) -> str:
    """Get required environment variable. Raises if not set."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} is not set")
    return value


def _env_int(key: str, default: int = 0) -> int:
    """Get environment variable as int with default."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_int_required(key: str) -> int:
    """Get required environment variable as int. Raises if not set."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} is not set")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Environment variable {key} must be an integer, got: {value}")


def _env_set(key: str) -> FrozenSet[int]:
    """Get environment variable as set of ints (comma-separated)."""
    value = os.getenv(key, "")
    if not value:
        return frozenset()
    try:
        return frozenset(int(x.strip()) for x in value.split(",") if x.strip())
    except ValueError:
        return frozenset()


def _env_list(key: str) -> tuple:
    """Get environment variable as tuple of ints (comma-separated)."""
    value = os.getenv(key, "")
    if not value:
        return ()
    try:
        return tuple(int(x.strip()) for x in value.split(",") if x.strip())
    except ValueError:
        return ()


def _env_tag_dict(key: str) -> Dict[str, int]:
    """Get environment variable as tag dictionary (JSON format)."""
    value = os.getenv(key, "")
    if not value:
        return {}
    try:
        tags = json.loads(value)
        if not isinstance(tags, dict):
            return {}
        return {k: int(v) for k, v in tags.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


# =============================================================================
# Timezone Configuration
# =============================================================================

# Use America/New_York which automatically handles EST/EDT daylight savings
# This is the single source of truth for timezone across the entire codebase
NY_TZ = ZoneInfo("America/New_York")


# =============================================================================
# Configuration Dataclass
# =============================================================================

@dataclass(frozen=True)
class Config:
    """Bot configuration from environment variables."""

    # =========================================================================
    # Core (bot-specific uses prefix)
    # =========================================================================
    TOKEN: str = _env("OTHMAN_TOKEN")
    GUILD_ID: int = _env_int("GUILD_ID")
    MODS_GUILD_ID: int = _env_int("MODS_GUILD_ID")
    OWNER_ID: int = _env_int("OWNER_ID")

    # =========================================================================
    # Roles
    # =========================================================================
    MOD_ROLE_ID: int = _env_int("MOD_ROLE_ID")
    DEBATES_MANAGEMENT_ROLE_ID: int = _env_int("DEBATES_MANAGEMENT_ROLE_ID")

    # =========================================================================
    # Channels
    # =========================================================================
    DEBATES_FORUM_ID: int = _env_int("DEBATES_FORUM_ID")
    CASE_LOG_FORUM_ID: int = _env_int("CASE_LOG_FORUM_ID")
    NEWS_CHANNEL_ID: int = _env_int("NEWS_CHANNEL_ID")
    SOCCER_CHANNEL_ID: int = _env_int("SOCCER_CHANNEL_ID")
    GENERAL_CHANNEL_ID: int = _env_int("GENERAL_CHANNEL_ID")

    # =========================================================================
    # Channel Lists
    # =========================================================================
    TOGGLE_CHANNEL_IDS: tuple = field(default_factory=lambda: _env_list("TOGGLE_CHANNEL_IDS"))

    # =========================================================================
    # User IDs
    # =========================================================================
    APPEAL_REVIEWER_IDS: FrozenSet[int] = field(
        default_factory=lambda: _env_set("APPEAL_REVIEWER_IDS")
    )

    # =========================================================================
    # Forum Tags (JSON format)
    # =========================================================================
    NEWS_FORUM_TAGS: Dict[str, int] = field(
        default_factory=lambda: _env_tag_dict("NEWS_FORUM_TAGS")
    )
    SOCCER_TEAM_TAG_IDS: Dict[str, int] = field(
        default_factory=lambda: _env_tag_dict("SOCCER_TEAM_TAG_IDS")
    )
    DEBATE_TAGS: Dict[str, int] = field(
        default_factory=lambda: _env_tag_dict("DEBATE_TAGS")
    )

    # =========================================================================
    # External APIs
    # =========================================================================
    OPENAI_API_KEY: str = _env("OPENAI_API_KEY")

    # =========================================================================
    # Paths (computed)
    # =========================================================================
    DATABASE_PATH: str = str(DATA_DIR / "othman.db")


# Create singleton config instance
config = Config()

# Build allowed guild IDs set from config
ALLOWED_GUILD_IDS: set[int] = {config.GUILD_ID} if config.GUILD_ID else set()
if config.MODS_GUILD_ID:
    ALLOWED_GUILD_IDS.add(config.MODS_GUILD_ID)


# =============================================================================
# Backwards Compatibility Exports
# =============================================================================
# These are exported for backwards compatibility with existing code
# New code should use config.FIELD_NAME instead

SYRIA_GUILD_ID = config.GUILD_ID
MODS_GUILD_ID = config.MODS_GUILD_ID
OWNER_ID = config.OWNER_ID
MOD_ROLE_ID = config.MOD_ROLE_ID
DEBATES_MANAGEMENT_ROLE_ID = config.DEBATES_MANAGEMENT_ROLE_ID
DEBATES_FORUM_ID = config.DEBATES_FORUM_ID
CASE_LOG_FORUM_ID = config.CASE_LOG_FORUM_ID
TOGGLE_CHANNEL_IDS = list(config.TOGGLE_CHANNEL_IDS)
APPEAL_REVIEWER_IDS = set(config.APPEAL_REVIEWER_IDS)
NEWS_FORUM_TAGS = config.NEWS_FORUM_TAGS
SOCCER_TEAM_TAG_IDS = config.SOCCER_TEAM_TAG_IDS
DEBATE_TAGS = config.DEBATE_TAGS


# =============================================================================
# Time Constants
# =============================================================================

SECONDS_PER_MINUTE: int = 60
SECONDS_PER_HOUR: int = 3600
SECONDS_PER_DAY: int = 86400


# =============================================================================
# Network & Retry Constants
# =============================================================================

NETWORK_TIMEOUT: int = 10
OPENAI_TIMEOUT: int = 30
DATABASE_TIMEOUT: float = 30.0
RETRY_DELAY_SECONDS: int = 300
SCHEDULER_ERROR_RETRY: int = 300


# =============================================================================
# Discord API Limits
# =============================================================================

DISCORD_AUTOCOMPLETE_LIMIT: int = 25
DISCORD_ARCHIVED_THREADS_LIMIT: int = 50
DISCORD_FILE_SIZE_MB: int = 25
DISCORD_EMBED_DESCRIPTION_LIMIT: int = 4096
DISCORD_MESSAGE_LIMIT: int = 2000


# =============================================================================
# Rate Limiting Constants
# =============================================================================

DISCORD_API_DELAY: float = 0.5
REACTION_DELAY: float = 0.3
BATCH_PROCESSING_DELAY: float = 0.1
PIN_SYSTEM_MESSAGE_DELAY: float = 1.0
BOT_STARTUP_DELAY: int = 10
PRESENCE_UPDATE_INTERVAL: int = 60
BOT_DISABLED_CHECK_INTERVAL: int = 60
BACKUP_ERROR_RETRY_INTERVAL: int = 3600
STATUS_CHECK_INTERVAL: int = 60


# =============================================================================
# Discord Error Codes
# =============================================================================

DISCORD_ERROR_THREAD_ARCHIVED: int = 50083
DISCORD_ERROR_UNKNOWN_MESSAGE: int = 10008
DISCORD_ERROR_MISSING_ACCESS: int = 50001


# =============================================================================
# String Truncation Limits
# =============================================================================

LOG_TITLE_PREVIEW_LENGTH: int = 30
LOG_ERROR_MESSAGE_LENGTH: int = 100
THREAD_NAME_PREVIEW_LENGTH: int = 40
CONTENT_PREVIEW_LENGTH: int = 200
DISCORD_THREAD_NAME_LIMIT: int = 100
TEASER_LENGTH: int = 100
LEADERBOARD_TOP_USERS: int = 10
LEADERBOARD_TOP_ITEMS: int = 3


# =============================================================================
# Stats API Constants
# =============================================================================

BASE_COMMAND_COUNT: int = 239


# =============================================================================
# Cache Constants
# =============================================================================

AI_CACHE_MAX_ENTRIES: int = 5000
CACHE_CLEANUP_RATIO: float = 0.8


# =============================================================================
# Debate Content Rules
# =============================================================================

MIN_MESSAGE_LENGTH: int = _env_int("MIN_MESSAGE_LENGTH", 200)
MIN_MESSAGE_LENGTH_ARABIC: int = _env_int("MIN_MESSAGE_LENGTH_ARABIC", 400)


# =============================================================================
# Open Discussion Configuration
# =============================================================================

# Import from centralized emojis module (delayed to avoid circular imports)
from src.core.emojis import VERIFY_EMOJI as OPEN_DISCUSSION_ACKNOWLEDGMENT_EMOJI


# =============================================================================
# Analytics Throttling
# =============================================================================

ANALYTICS_UPDATE_COOLDOWN: int = _env_int("ANALYTICS_UPDATE_COOLDOWN", 60)
ANALYTICS_CACHE_MAX_SIZE: int = _env_int("ANALYTICS_CACHE_MAX_SIZE", 100)
ANALYTICS_CACHE_CLEANUP_AGE: int = _env_int("ANALYTICS_CACHE_CLEANUP_AGE", 3600)


# =============================================================================
# Embed Styling (Imported from centralized colors module)
# =============================================================================

from src.core.colors import EmbedColors, EmbedIcons, EMBED_FOOTER_TEXT, EMBED_NO_VALUE


# =============================================================================
# Helper Functions
# =============================================================================

def load_channel_id(env_var: str, name: str) -> Optional[int]:
    """Load a channel ID from environment variable."""
    channel_id_str = os.getenv(env_var)
    if channel_id_str and channel_id_str.isdigit():
        return int(channel_id_str)
    return None


def load_news_channel_id() -> Optional[int]:
    """Load news channel ID from NEWS_CHANNEL_ID."""
    return config.NEWS_CHANNEL_ID or None


def load_soccer_channel_id() -> Optional[int]:
    """Load soccer channel ID from SOCCER_CHANNEL_ID."""
    return config.SOCCER_CHANNEL_ID or None


def load_general_channel_id() -> Optional[int]:
    """Load general channel ID from GENERAL_CHANNEL_ID."""
    return config.GENERAL_CHANNEL_ID or None


# =============================================================================
# Role Check Helpers
# =============================================================================

def has_debates_management_role(member) -> bool:
    """
    Check if a member has the Debates Management role or is the developer.

    Args:
        member: Discord Member or User object

    Returns:
        True if member is the developer, has the role, or if role is not configured
    """
    import discord

    # Owner bypass
    if member.id == config.OWNER_ID:
        return True

    # For non-Member objects (e.g., User in DMs), only developer has access
    if not isinstance(member, discord.Member):
        return False

    # If role ID is configured, check for it
    if config.DEBATES_MANAGEMENT_ROLE_ID:
        return any(role.id == config.DEBATES_MANAGEMENT_ROLE_ID for role in member.roles)

    # Fallback to manage_messages permission
    return member.guild_permissions.manage_messages


def can_review_appeals(user) -> bool:
    """
    Check if a user can review (approve/deny) appeals.

    Args:
        user: Discord User or Member object

    Returns:
        True if user is allowed to review appeals
    """
    # Owner always has access
    if user.id == config.OWNER_ID:
        return True

    # Check if user is in the allowed reviewers list
    if user.id in config.APPEAL_REVIEWER_IDS:
        return True

    # Fall back to debates management role check
    return has_debates_management_role(user)


# =============================================================================
# Configuration Validation
# =============================================================================

class ConfigValidationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


def validate_config() -> bool:
    """
    Validate configuration at startup.

    Returns:
        True if critical config is valid, False if bot cannot start
    """
    from src.core.logger import log

    is_valid = True
    warnings = []
    errors = []

    # Critical: Token must be set
    if not config.TOKEN:
        errors.append(("DISCORD_TOKEN", "Bot token is required"))
        is_valid = False

    # Critical: Guild ID should be set
    if not config.GUILD_ID:
        errors.append(("GUILD_ID", "Main guild ID is required"))
        is_valid = False

    # Important but not critical
    if not config.MOD_ROLE_ID:
        warnings.append(("MOD_ROLE_ID", "Moderation features limited"))
    if not config.DEBATES_FORUM_ID:
        warnings.append(("DEBATES_FORUM_ID", "Debates system disabled"))

    # Optional APIs
    optional_apis = []
    if not config.OPENAI_API_KEY:
        optional_apis.append("AI summaries")

    # Log results
    if errors:
        for key, reason in errors:
            log.tree("Config Error", [
                ("Variable", key),
                ("Reason", reason),
                ("Impact", "Bot cannot start"),
            ], emoji="🚨")

    if warnings:
        for key, reason in warnings:
            log.tree("Config Warning", [
                ("Variable", key),
                ("Reason", reason),
            ], emoji="⚠️")

    if optional_apis:
        log.tree("Optional APIs Not Configured", [
            ("APIs", ", ".join(optional_apis)),
            ("Impact", "Related features disabled"),
        ], emoji="ℹ️")

    if is_valid and not warnings:
        log.tree("Config Validation", [
            ("Status", "All checks passed"),
        ], emoji="✅")
    elif is_valid:
        log.tree("Config Validation", [
            ("Status", "Passed with warnings"),
            ("Warnings", str(len(warnings))),
        ], emoji="⚠️")

    return is_valid


def validate_and_log_config() -> None:
    """
    Validate configuration and raise error if critical config is missing.

    This is the main entry point for configuration validation at startup.

    Raises:
        ConfigValidationError: If required configuration is missing.
    """
    if not validate_config():
        raise ConfigValidationError("Critical configuration is missing")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Config instance
    "config",
    "Config",
    # Timezone
    "NY_TZ",
    # Directories
    "ROOT_DIR",
    "DATA_DIR",
    "LOGS_DIR",
    # Validation
    "ConfigValidationError",
    "validate_config",
    "validate_and_log_config",
    # Time Constants
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    # Network & Retry Constants
    "NETWORK_TIMEOUT",
    "OPENAI_TIMEOUT",
    "DATABASE_TIMEOUT",
    "RETRY_DELAY_SECONDS",
    "SCHEDULER_ERROR_RETRY",
    # Discord API Limits
    "DISCORD_AUTOCOMPLETE_LIMIT",
    "DISCORD_ARCHIVED_THREADS_LIMIT",
    "DISCORD_FILE_SIZE_MB",
    "DISCORD_EMBED_DESCRIPTION_LIMIT",
    "DISCORD_MESSAGE_LIMIT",
    # Rate Limiting Constants
    "DISCORD_API_DELAY",
    "REACTION_DELAY",
    "BATCH_PROCESSING_DELAY",
    "PIN_SYSTEM_MESSAGE_DELAY",
    "BOT_STARTUP_DELAY",
    "PRESENCE_UPDATE_INTERVAL",
    "BOT_DISABLED_CHECK_INTERVAL",
    "BACKUP_ERROR_RETRY_INTERVAL",
    "STATUS_CHECK_INTERVAL",
    # Discord Error Codes
    "DISCORD_ERROR_THREAD_ARCHIVED",
    "DISCORD_ERROR_UNKNOWN_MESSAGE",
    "DISCORD_ERROR_MISSING_ACCESS",
    # String Truncation Limits
    "LOG_TITLE_PREVIEW_LENGTH",
    "LOG_ERROR_MESSAGE_LENGTH",
    "THREAD_NAME_PREVIEW_LENGTH",
    "CONTENT_PREVIEW_LENGTH",
    "DISCORD_THREAD_NAME_LIMIT",
    "TEASER_LENGTH",
    "LEADERBOARD_TOP_USERS",
    "LEADERBOARD_TOP_ITEMS",
    # Stats
    "BASE_COMMAND_COUNT",
    # Cache Constants
    "AI_CACHE_MAX_ENTRIES",
    "CACHE_CLEANUP_RATIO",
    # Debate Content Rules
    "MIN_MESSAGE_LENGTH",
    "MIN_MESSAGE_LENGTH_ARABIC",
    # Analytics Throttling
    "ANALYTICS_UPDATE_COOLDOWN",
    "ANALYTICS_CACHE_MAX_SIZE",
    "ANALYTICS_CACHE_CLEANUP_AGE",
    # Backwards compatibility exports
    "SYRIA_GUILD_ID",
    "MODS_GUILD_ID",
    "ALLOWED_GUILD_IDS",
    "MOD_ROLE_ID",
    "OWNER_ID",
    "DEBATES_FORUM_ID",
    "CASE_LOG_FORUM_ID",
    "NEWS_FORUM_TAGS",
    "SOCCER_TEAM_TAG_IDS",
    "DEBATE_TAGS",
    "DEBATES_MANAGEMENT_ROLE_ID",
    "APPEAL_REVIEWER_IDS",
    "TOGGLE_CHANNEL_IDS",
    # Channel loaders
    "load_channel_id",
    "load_news_channel_id",
    "load_soccer_channel_id",
    "load_general_channel_id",
    # Role check helpers
    "has_debates_management_role",
    "can_review_appeals",
    # Embed styling
    "EmbedColors",
    "EmbedIcons",
    "EMBED_FOOTER_TEXT",
    "EMBED_NO_VALUE",
    # Open Discussion
    "OPEN_DISCUSSION_ACKNOWLEDGMENT_EMOJI",
]
