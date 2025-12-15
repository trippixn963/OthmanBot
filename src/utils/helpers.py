"""
Othman Discord Bot - Helper Utilities
======================================

Common helper functions used across the bot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Safe Discord API Fetch Helpers
# =============================================================================

async def safe_fetch_message(
    channel: discord.abc.Messageable,
    message_id: int
) -> Optional[discord.Message]:
    """
    Safely fetch a message with proper error handling.

    Args:
        channel: The channel/thread to fetch from
        message_id: The message ID to fetch

    Returns:
        The message if found, None otherwise
    """
    try:
        return await channel.fetch_message(message_id)
    except discord.NotFound:
        logger.debug("Message Not Found", [
            ("Message ID", str(message_id)),
        ])
        return None
    except discord.Forbidden:
        logger.warning("No Permission To Fetch Message", [
            ("Message ID", str(message_id)),
        ])
        return None
    except discord.HTTPException as e:
        logger.warning("HTTP Error Fetching Message", [
            ("Message ID", str(message_id)),
            ("Error", str(e)),
        ])
        return None


# =============================================================================
# Bot Helpers
# =============================================================================

async def get_developer_avatar(bot: "OthmanBot") -> str:
    """
    Get developer avatar URL for embed footers.

    Args:
        bot: The bot instance

    Returns:
        Avatar URL string
    """
    # Fallback URL if bot.user is not available
    default_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"

    # Null check for bot.user
    if bot.user is None:
        return default_avatar

    developer_avatar_url = bot.user.display_avatar.url

    developer_id_str = os.getenv("DEVELOPER_ID")
    if developer_id_str and developer_id_str.isdigit():
        try:
            async with asyncio.timeout(5.0):  # 5 second timeout for API call
                developer = await bot.fetch_user(int(developer_id_str))
                if developer is not None:
                    developer_avatar_url = developer.display_avatar.url
        except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError):
            pass  # Use bot avatar as fallback

    return developer_avatar_url


# =============================================================================
# String Truncation Helpers
# =============================================================================

def truncate(text: str, max_length: int, ellipsis: str = "...") -> str:
    """
    Truncate text to a maximum length with optional ellipsis.

    Args:
        text: The text to truncate
        max_length: Maximum length (including ellipsis if added)
        ellipsis: String to append if truncated (default: "...")

    Returns:
        Truncated text with ellipsis if it exceeded max_length
    """
    if not text or len(text) <= max_length:
        return text
    return text[:max_length - len(ellipsis)] + ellipsis


# =============================================================================
# Number Formatting Helpers
# =============================================================================

def get_ordinal(n: int) -> str:
    """
    Convert a number to its ordinal string (1st, 2nd, 3rd, etc.).

    Args:
        n: The number to convert

    Returns:
        Ordinal string (e.g., "1st", "2nd", "3rd", "4th")
    """
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# =============================================================================
# Input Sanitization
# =============================================================================

def sanitize_input(text: Optional[str], max_length: int = 500) -> Optional[str]:
    """
    Sanitize user input by stripping whitespace and enforcing length limits.

    Args:
        text: The input text to sanitize
        max_length: Maximum allowed length (default: 500)

    Returns:
        Sanitized text, or None if input is None or empty after stripping
    """
    if text is None:
        return None
    # Strip leading/trailing whitespace
    cleaned = text.strip()
    # Return None if empty after stripping
    if not cleaned:
        return None
    # Enforce max length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


__all__ = [
    "get_developer_avatar",
    "safe_fetch_message",
    "truncate",
    "get_ordinal",
    "sanitize_input",
]
