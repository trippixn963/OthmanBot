"""
Othman Discord Bot - Ready Handler
===================================

Service initialization and startup logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import SYRIA_GUILD_ID
from src.core.presence import update_presence, presence_update_loop
from src.services import (
    NewsScraper,
    SoccerScraper,
    GamingScraper,
)
from src.services.schedulers.rotation import ContentRotationScheduler
from src.services.debates.scheduler import DebatesScheduler
from src.services.debates.hot_tag_manager import HotTagManager
from src.services.debates.reconciliation import reconcile_karma
from src.services.debates.karma_scheduler import KarmaReconciliationScheduler
from src.services.debates.leaderboard import LeaderboardManager
from src.posting.news import post_news
from src.posting.soccer import post_soccer_news
from src.posting.gaming import post_gaming_news
from src.posting.debates import post_hot_debate

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Ready Handler
# =============================================================================

async def on_ready_handler(bot: "OthmanBot") -> None:
    """
    Initialize services and start automation when bot is ready.

    Args:
        bot: The OthmanBot instance

    DESIGN: Initializes all services and starts automation immediately
    Bot automatically begins posting news on startup
    Sets up presence updates and live score tracking
    """
    logger.tree(
        f"Bot Ready: {bot.user.name}",
        [
            ("Bot ID", str(bot.user.id)),
            ("Guilds", str(len(bot.guilds))),
            ("Mode", "Fully Automated"),
            ("News Channel", str(bot.news_channel_id) if bot.news_channel_id else "Not Set"),
            ("Soccer Channel", str(bot.soccer_channel_id) if bot.soccer_channel_id else "Not Set"),
            ("Gaming Channel", str(bot.gaming_channel_id) if bot.gaming_channel_id else "Not Set"),
        ],
        emoji="✅",
    )

    # Sync slash commands to all guilds for instant availability
    await _sync_commands(bot)

    # Initialize content rotation service (news → soccer → gaming hourly)
    await _init_content_rotation(bot)

    # Initialize debates scheduler
    await _init_debates_scheduler(bot)

    # Initialize Hot tag manager for debates
    await _init_hot_tag_manager(bot)

    # Run startup karma reconciliation and start nightly scheduler
    await _init_karma_reconciliation(bot)

    # Initialize leaderboard manager
    await _init_leaderboard(bot)

    # Set initial presence
    await update_presence(bot)

    # Start presence update loop
    bot.presence_task = asyncio.create_task(presence_update_loop(bot))
    logger.info("🔄 Started presence update loop (updates every 60 seconds)")


# =============================================================================
# Service Initialization
# =============================================================================

async def _init_content_rotation(bot: "OthmanBot") -> None:
    """Initialize unified content rotation scheduler.

    DESIGN: Rotates through news → soccer → gaming content hourly
    Posts only ONE content type per hour to save OpenAI API tokens
    Skips content types with no new unposted articles
    State persists across bot restarts
    """
    # Initialize all scrapers
    bot.news_scraper = NewsScraper()
    await bot.news_scraper.__aenter__()

    bot.soccer_scraper = SoccerScraper()
    await bot.soccer_scraper.__aenter__()

    bot.gaming_scraper = GamingScraper()
    await bot.gaming_scraper.__aenter__()

    # Create unified content rotation scheduler
    bot.content_rotation_scheduler = ContentRotationScheduler(
        news_callback=lambda: post_news(bot),
        soccer_callback=lambda: post_soccer_news(bot),
        gaming_callback=lambda: post_gaming_news(bot),
        news_scraper=bot.news_scraper,
        soccer_scraper=bot.soccer_scraper,
        gaming_scraper=bot.gaming_scraper,
    )

    # Start the rotation scheduler
    await bot.content_rotation_scheduler.start(post_immediately=False)
    logger.success("🔄 Content rotation scheduler started - posting hourly (news → soccer → gaming)")




async def _init_debates_scheduler(bot: "OthmanBot") -> None:
    """Initialize debates scheduler if configured.

    DESIGN: Posts hot debate every 3 hours (00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 EST)
    Calculates hotness score based on recent activity, karma, and reply count
    Posts to general channel with formatted announcement
    """
    if not bot.general_channel_id:
        logger.info("🔥 General channel not configured - skipping debates scheduler")
        return

    bot.debates_scheduler = DebatesScheduler(lambda: post_hot_debate(bot))
    await bot.debates_scheduler.start(post_immediately=False)
    logger.success("🔥 Automated hot debates started - posting every 3 hours")


async def _init_hot_tag_manager(bot: "OthmanBot") -> None:
    """Initialize Hot tag manager for debate forum.

    DESIGN: Runs every 10 minutes to dynamically manage the "Hot" tag
    Adds tag to threads with high activity (10+ messages in 1 hour, 20+ in 6 hours, etc.)
    Removes tag from threads with no activity for 6+ hours
    """
    bot.hot_tag_manager = HotTagManager(bot)
    await bot.hot_tag_manager.start()
    logger.success("🔥 Hot tag manager started - checking threads every 10 minutes")


async def _init_karma_reconciliation(bot: "OthmanBot") -> None:
    """Initialize karma reconciliation - startup scan and nightly scheduler.

    DESIGN: Catches any missed votes while bot was offline
    - Runs immediately on startup to reconcile recent threads
    - Schedules nightly sync at 00:30 EST for ongoing accuracy
    """
    # Run startup reconciliation in background (don't block bot startup)
    asyncio.create_task(_run_startup_reconciliation(bot))

    # Start nightly scheduler
    bot.karma_reconciliation_scheduler = KarmaReconciliationScheduler(
        lambda: reconcile_karma(bot)
    )
    await bot.karma_reconciliation_scheduler.start()


async def _run_startup_reconciliation(bot: "OthmanBot") -> None:
    """Run startup karma reconciliation after a short delay."""
    # Wait a bit for bot to fully initialize
    await asyncio.sleep(10)

    logger.info("🔄 Running startup karma reconciliation...")
    try:
        stats = await reconcile_karma(bot, days_back=7)
        logger.success(
            f"✅ Startup reconciliation: {stats['threads_scanned']} threads, "
            f"+{stats['votes_added']} added, -{stats['votes_removed']} removed"
        )
    except Exception as e:
        logger.error(f"Startup karma reconciliation failed: {e}")


async def _init_leaderboard(bot: "OthmanBot") -> None:
    """Initialize debates leaderboard manager.

    DESIGN: Creates or finds leaderboard post in debates forum
    Updates hourly with monthly and all-time top 3 debaters
    Handles user leave/rejoin by showing "(left)" suffix
    """
    if not hasattr(bot, 'debates_service') or not bot.debates_service:
        logger.info("📊 Debates service not initialized - skipping leaderboard")
        return

    try:
        bot.leaderboard_manager = LeaderboardManager(bot, bot.debates_service.db)
        await bot.leaderboard_manager.start()
    except Exception as e:
        logger.error(f"Failed to initialize leaderboard: {e}")


async def _sync_commands(bot: "OthmanBot") -> None:
    """Sync slash commands to the Syria guild only.

    DESIGN: Guild-specific sync is instant, global sync takes up to 1 hour
    """
    try:
        guild = discord.Object(id=SYRIA_GUILD_ID)

        # Copy global commands (from Cog) to the guild, then sync
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logger.success(f"⚡ Synced {len(synced)} commands to Syria guild")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["on_ready_handler"]
