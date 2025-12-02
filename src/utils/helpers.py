"""
Othman Discord Bot - Helper Utilities
======================================

Common helper functions used across the bot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.bot import OthmanBot


async def get_developer_avatar(bot: "OthmanBot") -> str:
    """
    Get developer avatar URL for embed footers.

    Args:
        bot: The bot instance

    Returns:
        Avatar URL string
    """
    developer_id_str = os.getenv("DEVELOPER_ID")
    developer_avatar_url = bot.user.display_avatar.url

    if developer_id_str and developer_id_str.isdigit():
        try:
            developer = await bot.fetch_user(int(developer_id_str))
            developer_avatar_url = developer.display_avatar.url
        except Exception:
            pass

    return developer_avatar_url


__all__ = ["get_developer_avatar"]
