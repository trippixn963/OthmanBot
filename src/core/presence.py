"""
Othman Discord Bot - Presence Module
=====================================

Bot presence update logic with live match status and countdown display.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Presence Update Loop
# =============================================================================

async def presence_update_loop(bot: "OthmanBot") -> None:
    """
    Background task that updates bot presence every minute.

    Args:
        bot: The OthmanBot instance

    DESIGN: Shows live countdown to next post
    Updates every 60 seconds to keep time accurate
    Timezone-agnostic relative time for all users
    Runs continuously until bot shuts down
    """
    while True:
        try:
            await asyncio.sleep(60)
            await update_presence(bot)
        except asyncio.CancelledError:
            logger.info("Presence update loop cancelled")
            break
        except Exception as e:
            logger.warning("Failed To Update Presence", [
                ("Error", str(e)),
            ])


# =============================================================================
# Presence Update
# =============================================================================

async def update_presence(bot: "OthmanBot", status_text: Optional[str] = None) -> None:
    """
    Update bot's Discord presence.

    Args:
        bot: The OthmanBot instance
        status_text: Custom status text, or None for default

    DESIGN: Prioritizes live match status over post countdown
    Shows live match score during active matches
    Falls back to next post countdown when no live matches
    Finds soonest upcoming post across all content types
    """
    now = datetime.now()

    # If no custom status, show next post
    if status_text is None:
        # Get next post time from content rotation scheduler
        next_post_time = None
        post_type = "news"  # Default

        if bot.content_rotation_scheduler:
            next_post_time = bot.content_rotation_scheduler.get_next_post_time()
            post_type = bot.content_rotation_scheduler.next_content_type

        if next_post_time:
            minutes_until = int((next_post_time - now).total_seconds() / 60)
            emoji = "📰" if post_type == "news" else ("⚽" if post_type == "soccer" else "🎮")

            if minutes_until <= 0:
                status_text = f"{emoji} Posting now..."
            elif minutes_until == 1:
                status_text = f"{emoji} Post in 1 minute"
            elif minutes_until < 60:
                status_text = f"{emoji} Post in {minutes_until} minutes"
            else:
                status_text = f"{emoji} Posting hourly"
        else:
            status_text = "📰 Automated News"

    activity: discord.Activity = discord.Activity(
        type=discord.ActivityType.watching, name=status_text
    )
    await bot.change_presence(activity=activity)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["presence_update_loop", "update_presence"]
