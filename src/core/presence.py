"""
Othman Discord Bot - Presence Module
=====================================

Bot presence update logic with rotating status display.
Cycles through: news countdown, active debates, votes today.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import PRESENCE_UPDATE_INTERVAL

if TYPE_CHECKING:
    from src.bot import OthmanBot


# Presence rotation state
_presence_index = 0


# =============================================================================
# Presence Update Loop
# =============================================================================

async def presence_update_loop(bot: "OthmanBot") -> None:
    """
    Background task that updates bot presence every minute.

    Args:
        bot: The OthmanBot instance

    DESIGN: Rotates between news countdown, active debates, and votes today
    Updates every 60 seconds to keep time accurate
    Runs continuously until bot shuts down
    """
    while True:
        try:
            await asyncio.sleep(PRESENCE_UPDATE_INTERVAL)
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
        status_text: Custom status text, or None for rotating default

    DESIGN: Rotates between 3 statuses:
    1. News/content post countdown
    2. Active debates count
    3. Votes today count
    """
    global _presence_index
    now = datetime.now()

    # If no custom status, rotate through statuses
    if status_text is None:
        status_text = await _get_rotating_status(bot, now)
        _presence_index = (_presence_index + 1) % 3

    activity: discord.Activity = discord.Activity(
        type=discord.ActivityType.watching, name=status_text
    )
    try:
        await bot.change_presence(activity=activity)
    except discord.HTTPException as e:
        # Discord API errors (rate limits, server issues)
        logger.warning("Failed To Update Presence (HTTP)", [
            ("Error", str(e)),
        ])
    except ConnectionError as e:
        # Connection issues during shutdown/reconnection
        logger.debug("Presence Update Skipped (Connection Issue)", [
            ("Error", str(e)),
        ])
    except Exception as e:
        # Ignore other connection errors during shutdown/reconnection
        # Common errors: "Cannot write to closing transport", "Not connected"
        error_msg = str(e).lower()
        if "transport" in error_msg or "not connected" in error_msg or "closed" in error_msg:
            logger.debug("Presence Update Skipped (Connection Issue)", [
                ("Error", str(e)),
            ])
        else:
            logger.warning("Failed To Update Presence", [
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])


async def _get_rotating_status(bot: "OthmanBot", now: datetime) -> str:
    """
    Get the current rotating status text.

    Cycles through:
    0: News/content post countdown
    1: Active debates count
    2: Votes today count
    """
    if _presence_index == 0:
        # News countdown
        return _get_news_status(bot, now)
    elif _presence_index == 1:
        # Active debates count
        return await _get_debates_status(bot)
    else:
        # Votes today
        return await _get_votes_status(bot)


def _get_news_status(bot: "OthmanBot", now: datetime) -> str:
    """Get news/content post countdown status."""
    next_post_time = None
    post_type = "news"

    if bot.content_rotation_scheduler:
        next_post_time = bot.content_rotation_scheduler.get_next_post_time()
        post_type = bot.content_rotation_scheduler.next_content_type

    if next_post_time:
        minutes_until = int((next_post_time - now).total_seconds() / 60)
        emoji = "📰" if post_type == "news" else ("⚽" if post_type == "soccer" else "🎮")

        if minutes_until <= 0:
            return f"{emoji} Posting now..."
        elif minutes_until == 1:
            return f"{emoji} Post in 1 minute"
        elif minutes_until < 60:
            return f"{emoji} Post in {minutes_until} minutes"
        else:
            return f"{emoji} Posting hourly"

    return "📰 Automated News"


async def _get_debates_status(bot: "OthmanBot") -> str:
    """Get active debates count status."""
    try:
        if bot.debates_service and bot.debates_service.db:
            count = bot.debates_service.db.get_active_debate_count()
            return f"⚔️ {count} active debates"
    except Exception as e:
        logger.debug("Presence Debates Query Failed", [("Error", str(e))])
    return "⚔️ Debates Forum"


async def _get_votes_status(bot: "OthmanBot") -> str:
    """Get votes today count status."""
    try:
        if bot.debates_service and bot.debates_service.db:
            count = bot.debates_service.db.get_votes_today()
            return f"⬆️ {count} votes today"
    except Exception as e:
        logger.debug("Presence Votes Query Failed", [("Error", str(e))])
    return "⬆️ Karma Voting"


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["presence_update_loop", "update_presence"]
