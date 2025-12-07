"""
Othman Discord Bot - Helper Utilities
======================================

Common helper functions used across the bot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

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
            developer = await bot.fetch_user(int(developer_id_str))
            if developer is not None:
                developer_avatar_url = developer.display_avatar.url
        except (discord.NotFound, discord.HTTPException):
            pass  # Use bot avatar as fallback

    return developer_avatar_url


__all__ = [
    "get_developer_avatar",
    "safe_fetch_message",
    "safe_fetch_member",
    "safe_fetch_user",
]
