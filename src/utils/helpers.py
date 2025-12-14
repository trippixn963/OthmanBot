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


async def safe_fetch_member(
    guild: discord.Guild,
    user_id: int
) -> Optional[discord.Member]:
    """
    Safely fetch a guild member with proper error handling.

    Args:
        guild: The guild to fetch from
        user_id: The user ID to fetch

    Returns:
        The member if found, None otherwise
    """
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None
    except discord.Forbidden:
        logger.warning("No Permission To Fetch Member", [
            ("User ID", str(user_id)),
        ])
        return None
    except discord.HTTPException as e:
        logger.warning("HTTP Error Fetching Member", [
            ("User ID", str(user_id)),
            ("Error", str(e)),
        ])
        return None


async def safe_fetch_user(
    bot: "OthmanBot",
    user_id: int
) -> Optional[discord.User]:
    """
    Safely fetch a user with proper error handling.

    Args:
        bot: The bot instance
        user_id: The user ID to fetch

    Returns:
        The user if found, None otherwise
    """
    try:
        return await bot.fetch_user(user_id)
    except discord.NotFound:
        return None
    except discord.HTTPException as e:
        logger.warning("HTTP Error Fetching User", [
            ("User ID", str(user_id)),
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


def truncate_for_log(text: str, max_length: int = 30) -> str:
    """
    Truncate text for logging purposes (no ellipsis).

    Args:
        text: The text to truncate
        max_length: Maximum length (default: 30)

    Returns:
        Truncated text without ellipsis
    """
    if not text:
        return ""
    return text[:max_length]


__all__ = [
    "get_developer_avatar",
    "safe_fetch_message",
    "safe_fetch_member",
    "safe_fetch_user",
    "truncate",
    "truncate_for_log",
]
