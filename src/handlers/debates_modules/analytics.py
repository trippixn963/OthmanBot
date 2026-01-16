"""
OthmanBot - Debates Analytics Handler
=====================================

Analytics embed management for debate threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, DISCORD_API_DELAY
from src.caches import analytics_throttle_cache
from src.utils import (
    edit_message_with_retry,
    safe_fetch_message,
)
from src.utils.discord_rate_limit import log_http_error
from src.services.debates.analytics import (
    calculate_debate_analytics,
    generate_analytics_embed,
)

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Analytics Embed Management
# =============================================================================

async def update_analytics_embed(bot: "OthmanBot", thread: discord.Thread, force: bool = False) -> None:
    """
    Update the analytics embed for a debate thread.

    Args:
        bot: The OthmanBot instance
        thread: The debate thread
        force: If True, bypass throttle and update immediately

    DESIGN: Updates analytics embed in-place without reposting
    Throttled to 30 seconds per thread to avoid rate limits
    Uses AnalyticsThrottleCache for thread-safe throttling
    """
    # Check if debates service is available
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return

    # Throttle check - skip if updated recently (unless forced)
    if not force and not await analytics_throttle_cache.should_update(thread.id):
        return

    try:
        # Get analytics message ID from database
        analytics_message_id = await bot.debates_service.db.get_analytics_message_async(thread.id)
        if not analytics_message_id:
            logger.debug("📊 No Analytics Message Found", [
                ("Thread ID", str(thread.id)),
            ])
            return

        # Fetch the analytics message using safe helper
        analytics_message = await safe_fetch_message(thread, analytics_message_id)
        if analytics_message is None:
            # Clear stale reference to prevent repeated warnings
            await bot.debates_service.db.clear_analytics_message_async(thread.id)
            logger.info("📊 Cleared Stale Analytics Reference", [
                ("Message ID", str(analytics_message_id)),
                ("Thread ID", str(thread.id)),
            ])
            return

        # Calculate updated analytics
        analytics = await calculate_debate_analytics(thread, bot.debates_service.db)

        # Generate updated embed
        embed = await generate_analytics_embed(bot, analytics)

        # Edit the message with rate limit handling
        await edit_message_with_retry(analytics_message, embed=embed)

        # Record the update (handles cleanup internally)
        await analytics_throttle_cache.record_update(thread.id)

        logger.debug("📊 Updated Analytics Embed", [
            ("Thread", thread.name[:50]),
        ])

    except discord.HTTPException as e:
        log_http_error(e, "Update Analytics Embed", [
            ("Thread ID", str(thread.id)),
        ])
    except (ValueError, KeyError, TypeError) as e:
        logger.error("📊 Data Error Updating Analytics Embed", [
            ("Error", str(e)),
        ])


async def refresh_all_analytics_embeds(bot: "OthmanBot") -> int:
    """
    Refresh all analytics embeds for active debate threads.

    This is a one-time migration function to update existing embeds
    with new fields (e.g., created_at timestamp).

    Args:
        bot: The OthmanBot instance

    Returns:
        Number of embeds updated
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        logger.warning("Cannot Refresh Analytics", [
            ("Reason", "Debates service not available"),
        ])
        return 0

    if not DEBATES_FORUM_ID:
        logger.warning("Cannot Refresh Analytics", [
            ("Reason", "DEBATES_FORUM_ID not set"),
        ])
        return 0

    forum = bot.get_channel(DEBATES_FORUM_ID)
    if not forum or not isinstance(forum, discord.ForumChannel):
        logger.warning("Cannot Refresh Analytics", [
            ("Reason", "Forum channel not found"),
        ])
        return 0

    updated_count = 0
    error_count = 0

    logger.info("📊 Starting Analytics Embed Refresh", [
        ("Forum", forum.name),
    ])

    # Get all active (non-archived) threads
    for thread in forum.threads:
        if thread.archived:
            continue

        try:
            await update_analytics_embed(bot, thread, force=True)
            updated_count += 1

            # Small delay to avoid rate limits
            await asyncio.sleep(DISCORD_API_DELAY)

        except Exception as e:
            error_count += 1
            logger.warning("📊 Failed To Refresh Analytics For Thread", [
                ("Thread", thread.name[:50]),
                ("Error", str(e)),
            ])

    logger.success("📊 Analytics Embed Refresh Complete", [
        ("Updated", str(updated_count)),
        ("Errors", str(error_count)),
    ])

    return updated_count


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "update_analytics_embed",
    "refresh_all_analytics_embeds",
]
