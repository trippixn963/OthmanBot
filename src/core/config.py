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

from src.core.logger import logger


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
    "DEBATES_FORUM_ID": "Debates forum channel ID",
    "MODERATOR_ROLE_ID": "Moderator role ID",
    "DEVELOPER_ID": "Developer user ID",
}

# Features that require OpenAI API key (for startup warnings)
OPENAI_DEPENDENT_FEATURES: list[str] = [
    "AI news summaries",
    "Bilingual content translation",
    "Debate tag detection",
    "Hostility analysis",
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


# =============================================================================
# Cache Constants
# =============================================================================

AI_CACHE_MAX_ENTRIES: int = 5000  # Max entries in AI response cache
CACHE_CLEANUP_RATIO: float = 0.8  # Remove 20% when cache is full


# =============================================================================
# Forum Thread Constants
# =============================================================================

FORUM_AUTO_ARCHIVE_MINUTES: int = 1440  # 24 hours in minutes


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


# =============================================================================
# Discord Role IDs (loaded from environment)
# =============================================================================

MODERATOR_ROLE_ID: int = _load_required_id("MODERATOR_ROLE_ID")
DEVELOPER_ID: int = _load_required_id("DEVELOPER_ID")


# =============================================================================
# Discord Channel/Forum IDs (loaded from environment)
# =============================================================================

DEBATES_FORUM_ID: int = _load_required_id("DEBATES_FORUM_ID")


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
# Module Export
# =============================================================================

__all__ = [
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
    # Cache Constants
    "AI_CACHE_MAX_ENTRIES",
    "CACHE_CLEANUP_RATIO",
    # Forum Constants
    "FORUM_AUTO_ARCHIVE_MINUTES",
    # IDs
    "SYRIA_GUILD_ID",
    "MODERATOR_ROLE_ID",
    "DEVELOPER_ID",
    "DEBATES_FORUM_ID",
    "NEWS_FORUM_TAGS",
    "SOCCER_TEAM_TAG_IDS",
    "DEBATE_TAGS",
    # Channel loaders
    "load_channel_id",
    "load_news_channel_id",
    "load_soccer_channel_id",
    "load_gaming_channel_id",
    "load_general_channel_id",
]
