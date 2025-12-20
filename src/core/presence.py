"""
Othman Discord Bot - Presence Module
=====================================

Bot presence update logic with rotating status display.
Cycles through: news countdown, active debates, votes today.
Includes hourly promotional presence for trippixn.com/othman.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import PRESENCE_UPDATE_INTERVAL, NY_TZ

if TYPE_CHECKING:
    from src.bot import OthmanBot

# Promotional presence settings
PROMO_TEXT = "🌐 trippixn.com/othman"
PROMO_DURATION_MINUTES = 10

# Presence rotation state
_presence_index = 0
_promo_active = False
_promo_task: Optional[asyncio.Task] = None


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

    Skips updates during promotional presence window.
    """
    global _presence_index, _promo_active

    # Skip regular updates during promo window
    if _promo_active:
        return

    now = datetime.now(NY_TZ)

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
        emoji = "📰" if post_type == "news" else "⚽"

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
# Promotional Presence
# =============================================================================

async def start_promo_scheduler(bot: "OthmanBot") -> None:
    """
    Start the hourly promotional presence scheduler.

    DESIGN: Shows "trippixn.com/othman" for 10 minutes at the top of every hour
    then resumes normal rotating presence.
    """
    global _promo_task
    _promo_task = asyncio.create_task(_promo_loop(bot))
    logger.info("📢 Promo Presence Scheduler Started", [
        ("Schedule", "Every hour on the hour"),
        ("Duration", f"{PROMO_DURATION_MINUTES} minutes"),
        ("Text", PROMO_TEXT),
    ])


async def stop_promo_scheduler() -> None:
    """Stop the promotional presence scheduler."""
    global _promo_task
    if _promo_task:
        _promo_task.cancel()
        try:
            await _promo_task
        except asyncio.CancelledError:
            pass
        _promo_task = None


async def _promo_loop(bot: "OthmanBot") -> None:
    """Background loop that triggers promo presence on the hour."""
    global _promo_active

    while True:
        try:
            now = datetime.now(NY_TZ)
            # Calculate seconds until next hour
            minutes_until_hour = 60 - now.minute
            seconds_until_hour = minutes_until_hour * 60 - now.second

            # Wait until next hour
            await asyncio.sleep(seconds_until_hour)

            # Show promo presence
            _promo_active = True
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=PROMO_TEXT
            )
            await bot.change_presence(activity=activity)

            promo_time = datetime.now(NY_TZ)
            logger.info("📢 Promo Presence Activated", [
                ("Text", PROMO_TEXT),
                ("Duration", f"{PROMO_DURATION_MINUTES} minutes"),
                ("Time", promo_time.strftime("%I:%M %p EST")),
            ])

            # Wait for promo duration
            await asyncio.sleep(PROMO_DURATION_MINUTES * 60)

            # Restore normal presence
            _promo_active = False
            await update_presence(bot)

            logger.info("📢 Promo Presence Ended - Normal Presence Restored")

        except asyncio.CancelledError:
            break
        except Exception as e:
            _promo_active = False
            logger.warning("Promo Presence Loop Error", [
                ("Error", str(e)),
                ("Action", "Continuing loop"),
            ])
            await asyncio.sleep(60)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["presence_update_loop", "update_presence", "start_promo_scheduler", "stop_promo_scheduler"]
