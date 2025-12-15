"""
Othman Discord Bot - Configuration Module
==========================================

Channel ID loading and environment configuration helpers.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.logger import logger


# =============================================================================
# Timezone Configuration
# =============================================================================

# Use America/New_York which automatically handles EST/EDT daylight savings
# This is the single source of truth for timezone across the entire codebase
NY_TZ = ZoneInfo("America/New_York")


# =============================================================================
# Configuration Validation
# =============================================================================

class ConfigValidationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


@dataclass
class ConfigValidationResult:
    """Result of configuration validation."""
    valid: bool
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    invalid_format: list[tuple[str, str]] = field(default_factory=list)  # (var_name, reason)


# Required environment variables (bot won't start without these)
REQUIRED_ENV_VARS: list[str] = [
    "DISCORD_TOKEN",
]

# Optional environment variables with their descriptions
OPTIONAL_ENV_VARS: dict[str, str] = {
    "OPENAI_API_KEY": "AI-powered news summaries and content generation",
    "NEWS_CHANNEL_ID": "News posting channel",
    "SOCCER_CHANNEL_ID": "Soccer news channel",
    "GAMING_CHANNEL_ID": "Gaming news channel",
    "GENERAL_CHANNEL_ID": "General announcements channel",
    "SYRIA_GUILD_ID": "Main Discord server ID",
    "MODS_GUILD_ID": "Moderators Discord server ID (optional)",
    "DEBATES_FORUM_ID": "Debates forum channel ID",
    "MODERATOR_ROLE_ID": "Moderator role ID",
    "DEVELOPER_ID": "Developer user ID",
}

# Features that require OpenAI API key (for startup warnings)
OPENAI_DEPENDENT_FEATURES: list[str] = [
    "AI news summaries",
    "Bilingual content translation",
    "Debate tag detection",
]


def validate_config() -> ConfigValidationResult:
    """
    Validate all environment variables at startup.

    Returns:
        ConfigValidationResult with validation status and any issues found.

    DESIGN: Validates both required and optional env vars at startup
    - Required vars: Bot exits if missing
    - Optional vars: Logs warnings but continues
    - Format validation: Checks channel IDs are numeric
    """
    result = ConfigValidationResult(valid=True)

    # Check required variables
    for var in REQUIRED_ENV_VARS:
        value = os.getenv(var)
        if not value:
            result.missing_required.append(var)
            result.valid = False

    # Check optional variables
    for var, description in OPTIONAL_ENV_VARS.items():
        value = os.getenv(var)
        if not value:
            result.missing_optional.append(var)

    # Validate channel ID formats (should be numeric)
    channel_vars = ["NEWS_CHANNEL_ID", "SOCCER_CHANNEL_ID", "GAMING_CHANNEL_ID", "GENERAL_CHANNEL_ID"]
    for var in channel_vars:
        value = os.getenv(var)
        if value and not value.isdigit():
            result.invalid_format.append((var, "Must be a numeric Discord channel ID"))
            result.valid = False

    return result


def validate_and_log_config() -> None:
    """
    Validate configuration and log results.

    Raises:
        ConfigValidationError: If required configuration is missing.
    """
    result = validate_config()

    # Log missing required variables (critical)
    if result.missing_required:
        for var in result.missing_required:
            logger.error("Missing Required Configuration", [
                ("Variable", var),
                ("Action", f"Add {var}=<value> to your .env file"),
            ])

    # Log invalid format errors
    if result.invalid_format:
        for var, reason in result.invalid_format:
            logger.error("Invalid Configuration Format", [
                ("Variable", var),
                ("Reason", reason),
            ])

    # Log missing optional variables (warnings)
    if result.missing_optional:
        features_disabled = []
        for var in result.missing_optional:
            if var in OPTIONAL_ENV_VARS:
                features_disabled.append(f"{var} ({OPTIONAL_ENV_VARS[var]})")

        if features_disabled:
            logger.info("Optional Features Disabled", [
                ("Variables", ", ".join(result.missing_optional)),
                ("Features", ", ".join(features_disabled[:3]) + ("..." if len(features_disabled) > 3 else "")),
            ])

        # Special warning for OpenAI API key
        if "OPENAI_API_KEY" in result.missing_optional:
            logger.warning("OpenAI API Key Not Configured", [
                ("Impact", "AI features will be disabled"),
                ("Affected Features", ", ".join(OPENAI_DEPENDENT_FEATURES[:3])),
                ("Action", "Add OPENAI_API_KEY to .env for full functionality"),
            ])

    # Raise error if validation failed
    if not result.valid:
        raise ConfigValidationError(
            f"Missing required config: {', '.join(result.missing_required)}"
            + (f"; Invalid format: {', '.join(v for v, _ in result.invalid_format)}" if result.invalid_format else "")
        )

    # Log success
    logger.info("Configuration Validated Successfully", [
        ("Required", f"{len(REQUIRED_ENV_VARS)} OK"),
        ("Optional", f"{len(OPTIONAL_ENV_VARS) - len(result.missing_optional)}/{len(OPTIONAL_ENV_VARS)} configured"),
    ])


# =============================================================================
# Time Constants
# =============================================================================

SECONDS_PER_MINUTE: int = 60
SECONDS_PER_HOUR: int = 3600
SECONDS_PER_DAY: int = 86400


# =============================================================================
# Network & Retry Constants
# =============================================================================

NETWORK_TIMEOUT: int = 10  # Default timeout for HTTP requests (seconds)
OPENAI_TIMEOUT: int = 30  # Timeout for OpenAI API calls (seconds)
DATABASE_TIMEOUT: float = 30.0  # SQLite connection timeout (seconds)
RETRY_DELAY_SECONDS: int = 300  # Default retry delay on error (5 minutes)
SCHEDULER_ERROR_RETRY: int = 300  # Scheduler retry delay on error (5 minutes)


# =============================================================================
# Discord API Limits
# =============================================================================

DISCORD_AUTOCOMPLETE_LIMIT: int = 25  # Max choices in autocomplete
DISCORD_ARCHIVED_THREADS_LIMIT: int = 50  # Pagination limit for archived threads
DISCORD_FILE_SIZE_MB: int = 25  # Max file upload size
DISCORD_EMBED_DESCRIPTION_LIMIT: int = 4096  # Max embed description length
DISCORD_MESSAGE_LIMIT: int = 2000  # Max message content length


# =============================================================================
# Rate Limiting Constants
# =============================================================================

DISCORD_API_DELAY: float = 0.5  # Delay between Discord API calls (seconds)
REACTION_DELAY: float = 0.3  # Delay between adding reactions (seconds)
BATCH_PROCESSING_DELAY: float = 0.1  # Delay between batch operations (seconds)
PIN_SYSTEM_MESSAGE_DELAY: float = 1.0  # Delay after pinning for system message to appear (seconds)
BOT_STARTUP_DELAY: int = 10  # Initial delay before startup tasks (seconds)
PRESENCE_UPDATE_INTERVAL: int = 60  # Interval between presence updates (seconds)
BOT_DISABLED_CHECK_INTERVAL: int = 60  # Check interval when bot is disabled (seconds)
BACKUP_ERROR_RETRY_INTERVAL: int = 3600  # Wait time after backup error (1 hour)
STATUS_CHECK_INTERVAL: int = 60  # Interval for periodic status checks (seconds)


# =============================================================================
# Discord Error Codes
# =============================================================================

DISCORD_ERROR_THREAD_ARCHIVED: int = 50083  # Thread is archived and cannot be modified
DISCORD_ERROR_UNKNOWN_MESSAGE: int = 10008  # Unknown message
DISCORD_ERROR_MISSING_ACCESS: int = 50001  # Missing access

# =============================================================================
# String Truncation Limits
# =============================================================================

LOG_TITLE_PREVIEW_LENGTH: int = 30  # Title preview length in logs
LOG_ERROR_MESSAGE_LENGTH: int = 100  # Error message length in logs
THREAD_NAME_PREVIEW_LENGTH: int = 40  # Thread name preview in logs
CONTENT_PREVIEW_LENGTH: int = 200  # Content preview for errors/logs
DISCORD_THREAD_NAME_LIMIT: int = 100  # Discord thread name character limit
TEASER_LENGTH: int = 100  # Summary teaser length for embeds
LEADERBOARD_TOP_USERS: int = 10  # Top users to show in leaderboards
LEADERBOARD_TOP_ITEMS: int = 3  # Top items (streaks, debates, etc.)
DISCORD_AUTOCOMPLETE_LIMIT: int = 25  # Discord autocomplete max choices

# =============================================================================
# Cache Constants
# =============================================================================

AI_CACHE_MAX_ENTRIES: int = 5000  # Max entries in AI response cache
CACHE_CLEANUP_RATIO: float = 0.8  # Remove 20% when cache is full


# =============================================================================
# Debate Content Rules
# =============================================================================

MIN_MESSAGE_LENGTH: int = int(os.getenv("MIN_MESSAGE_LENGTH", "200"))  # Minimum chars for Latin/English
MIN_MESSAGE_LENGTH_ARABIC: int = int(os.getenv("MIN_MESSAGE_LENGTH_ARABIC", "400"))  # Min chars for Arabic


# =============================================================================
# Analytics Throttling
# =============================================================================

ANALYTICS_UPDATE_COOLDOWN: int = int(os.getenv("ANALYTICS_UPDATE_COOLDOWN", "60"))  # Seconds between updates
ANALYTICS_CACHE_MAX_SIZE: int = int(os.getenv("ANALYTICS_CACHE_MAX_SIZE", "100"))  # Max throttle cache entries
ANALYTICS_CACHE_CLEANUP_AGE: int = int(os.getenv("ANALYTICS_CACHE_CLEANUP_AGE", "3600"))  # Remove entries older than 1 hour


# =============================================================================
# Discord Server/Guild IDs (loaded from environment)
# =============================================================================

def _load_required_id(env_var: str) -> int:
    """Load a required Discord ID from environment variable.

    Raises:
        ConfigValidationError: If the environment variable is not set or invalid.
    """
    value = os.getenv(env_var)
    if not value:
        raise ConfigValidationError(f"Required environment variable {env_var} is not set")
    if not value.isdigit():
        raise ConfigValidationError(f"Environment variable {env_var} must be a numeric Discord ID")
    return int(value)


def _load_optional_id(env_var: str) -> Optional[int]:
    """Load an optional Discord ID from environment variable.

    Returns:
        The ID as int if set, None if not set.
    """
    value = os.getenv(env_var)
    if not value:
        return None
    if not value.isdigit():
        return None  # Skip invalid values silently for optional IDs
    return int(value)


def _load_tag_dict(env_var: str) -> dict[str, int]:
    """Load a tag dictionary from a JSON-formatted environment variable.

    Expected format: {"tag_name": 123456789, "other_tag": 987654321}

    Raises:
        ConfigValidationError: If the environment variable is not set or invalid JSON.
    """
    import json
    value = os.getenv(env_var)
    if not value:
        raise ConfigValidationError(f"Required environment variable {env_var} is not set")
    try:
        tags = json.loads(value)
        if not isinstance(tags, dict):
            raise ConfigValidationError(f"Environment variable {env_var} must be a JSON object")
        # Validate all values are integers
        return {k: int(v) for k, v in tags.items()}
    except json.JSONDecodeError as e:
        raise ConfigValidationError(f"Environment variable {env_var} contains invalid JSON: {e}")


SYRIA_GUILD_ID: int = _load_required_id("SYRIA_GUILD_ID")
MODS_GUILD_ID: Optional[int] = _load_optional_id("MODS_GUILD_ID")

# Build list of allowed guild IDs for auto-leave protection
ALLOWED_GUILD_IDS: set[int] = {SYRIA_GUILD_ID}
if MODS_GUILD_ID:
    ALLOWED_GUILD_IDS.add(MODS_GUILD_ID)


# =============================================================================
# Discord Role IDs (loaded from environment)
# =============================================================================

MODERATOR_ROLE_ID: int = _load_required_id("MODERATOR_ROLE_ID")
DEVELOPER_ID: int = _load_required_id("DEVELOPER_ID")
DEBATES_MANAGEMENT_ROLE_ID: Optional[int] = _load_optional_id("DEBATES_MANAGEMENT_ROLE_ID")


# =============================================================================
# Discord Channel/Forum IDs (loaded from environment)
# =============================================================================

DEBATES_FORUM_ID: int = _load_required_id("DEBATES_FORUM_ID")
CASE_LOG_FORUM_ID: Optional[int] = _load_optional_id("CASE_LOG_FORUM_ID")

# Channel IDs to hide/unhide when bot is toggled off/on
# These channels become invisible to @everyone when bot is disabled
# Format in .env: TOGGLE_CHANNEL_IDS=123,456,789
def _load_toggle_channel_ids() -> list[int]:
    """Load toggle channel IDs from comma-separated env var."""
    raw = os.getenv("TOGGLE_CHANNEL_IDS", "")
    if not raw:
        return []
    try:
        return [int(id.strip()) for id in raw.split(",") if id.strip()]
    except ValueError:
        logger.warning("Invalid TOGGLE_CHANNEL_IDS format - should be comma-separated integers")
        return []

TOGGLE_CHANNEL_IDS: list[int] = _load_toggle_channel_ids()


# =============================================================================
# News Forum Tag IDs (loaded from environment as JSON)
# =============================================================================

NEWS_FORUM_TAGS: dict[str, int] = _load_tag_dict("NEWS_FORUM_TAGS")


# =============================================================================
# Soccer Forum Tag IDs (loaded from environment as JSON)
# =============================================================================

SOCCER_TEAM_TAG_IDS: dict[str, int] = _load_tag_dict("SOCCER_TEAM_TAG_IDS")


# =============================================================================
# Debates Forum Tag IDs (loaded from environment as JSON)
# =============================================================================

DEBATE_TAGS: dict[str, int] = _load_tag_dict("DEBATE_TAGS")


# =============================================================================
# Channel ID Loading
# =============================================================================

def load_channel_id(env_var: str, name: str) -> Optional[int]:
    """
    Load a channel ID from environment variable.

    Args:
        env_var: Environment variable name
        name: Human-readable channel name for logging

    Returns:
        Channel ID as int or None if not configured

    DESIGN: Centralized channel ID loading with validation
    Validates that channel ID is numeric before converting
    Returns None if not configured (allows optional channels)
    """
    channel_id_str: Optional[str] = os.getenv(env_var)
    if channel_id_str and channel_id_str.isdigit():
        return int(channel_id_str)
    return None


def load_news_channel_id() -> Optional[int]:
    """Load news channel ID from NEWS_CHANNEL_ID."""
    return load_channel_id("NEWS_CHANNEL_ID", "news")


def load_soccer_channel_id() -> Optional[int]:
    """Load soccer channel ID from SOCCER_CHANNEL_ID."""
    return load_channel_id("SOCCER_CHANNEL_ID", "soccer")


def load_gaming_channel_id() -> Optional[int]:
    """Load gaming channel ID from GAMING_CHANNEL_ID."""
    return load_channel_id("GAMING_CHANNEL_ID", "gaming")


def load_general_channel_id() -> Optional[int]:
    """Load general channel ID from GENERAL_CHANNEL_ID."""
    return load_channel_id("GENERAL_CHANNEL_ID", "general")


# =============================================================================
# Role Check Helper
# =============================================================================

def has_debates_management_role(member) -> bool:
    """
    Check if a member has the Debates Management role or is the developer.

    Args:
        member: Discord Member or User object

    Returns:
        True if member is the developer, has the role, or if role is not configured

    DESIGN: Centralized role check for debates management commands.
    - Developer always has access (bypass)
    - If DEBATES_MANAGEMENT_ROLE_ID is configured, check for it
    - Falls back to manage_messages permission if role not configured
    """
    import discord

    # Developer bypass - always allow
    if member.id == DEVELOPER_ID:
        return True

    # For non-Member objects (e.g., User in DMs), only developer has access
    if not isinstance(member, discord.Member):
        return False

    # If role ID is configured, check for it
    if DEBATES_MANAGEMENT_ROLE_ID:
        return any(role.id == DEBATES_MANAGEMENT_ROLE_ID for role in member.roles)

    # Fallback to manage_messages permission
    return member.guild_permissions.manage_messages


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Timezone
    "NY_TZ",
    # Validation
    "ConfigValidationError",
    "ConfigValidationResult",
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
    "DISCORD_AUTOCOMPLETE_LIMIT",
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
    # IDs
    "SYRIA_GUILD_ID",
    "MODS_GUILD_ID",
    "ALLOWED_GUILD_IDS",
    "MODERATOR_ROLE_ID",
    "DEVELOPER_ID",
    "DEBATES_FORUM_ID",
    "CASE_LOG_FORUM_ID",
    "NEWS_FORUM_TAGS",
    "SOCCER_TEAM_TAG_IDS",
    "DEBATE_TAGS",
    # Channel loaders
    "load_channel_id",
    "load_news_channel_id",
    "load_soccer_channel_id",
    "load_gaming_channel_id",
    "load_general_channel_id",
    # Role IDs
    "DEBATES_MANAGEMENT_ROLE_ID",
    # Role check helpers
    "has_debates_management_role",
]
