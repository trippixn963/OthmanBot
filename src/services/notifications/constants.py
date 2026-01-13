"""
OthmanBot - Notifications Constants
===================================

Constants for ban notification embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.core.config import EmbedColors

# Embed colors
COLOR_BAN = EmbedColors.BAN
COLOR_UNBAN = EmbedColors.UNBAN
COLOR_EXPIRED = EmbedColors.EXPIRED
COLOR_DM_SUCCESS = EmbedColors.SUCCESS
COLOR_DM_FAILED = EmbedColors.ERROR

__all__ = [
    "COLOR_BAN",
    "COLOR_UNBAN",
    "COLOR_EXPIRED",
    "COLOR_DM_SUCCESS",
    "COLOR_DM_FAILED",
]
