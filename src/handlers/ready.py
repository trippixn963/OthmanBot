"""
Othman Discord Bot - Ready Handler
===================================

Service initialization and startup logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, List

import discord

from src.core.logger import logger
from src.core.config import SYRIA_GUILD_ID, ALLOWED_GUILD_IDS
from src.core.health import HealthCheckServer
from src.core.presence import update_presence, presence_update_loop
from src.core.backup import BackupScheduler
from src.posting.poster import cleanup_old_temp_files
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
from src.services.debates.numbering_scheduler import (
    NumberingReconciliationScheduler,
    reconcile_debate_numbering,
)
from src.services.debates.leaderboard import LeaderboardManager
from src.services.debates.backfill import (
    backfill_debate_stats,
    reconcile_debate_stats,
    StatsReconciliationScheduler,
)
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
    # Leave unauthorized guilds first
    await _leave_unauthorized_guilds(bot)

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

    # Initialize nightly numbering reconciliation scheduler
    await _init_numbering_reconciliation(bot)

    # Initialize leaderboard manager
    await _init_leaderboard(bot)

    # Initialize database backup scheduler
    await _init_backup_scheduler(bot)

    # Set initial presence
    await update_presence(bot)

    # Start presence update loop
    bot.presence_task = asyncio.create_task(presence_update_loop(bot))
    logger.info("🔄 Started Presence Update Loop", [
        ("Interval", "60 seconds"),
    ])

    # Clean up old temp files from previous sessions
    cleanup_old_temp_files()
    logger.info("🧹 Cleaned Up Old Temp Files")

    # Start health check HTTP server
    bot.health_server = HealthCheckServer(bot)
    await bot.health_server.start()

    # Initialize webhook alerts
    await _init_webhook_alerts(bot)

    # Update status channel to show online
    await bot.update_status_channel(online=True)


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
        bot=bot,
    )

    # Start the rotation scheduler
    await bot.content_rotation_scheduler.start(post_immediately=False)
    logger.tree("Content Rotation Scheduler Started", [
        ("Rotation", "news → soccer → gaming"),
        ("Interval", "hourly"),
    ], emoji="🔄")




async def _init_debates_scheduler(bot: "OthmanBot") -> None:
    """Initialize debates scheduler if configured.

    DESIGN: Posts hot debate every 3 hours (00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 EST)
    Calculates hotness score based on recent activity, karma, and reply count
    Posts to general channel with formatted announcement
    """
    if not bot.general_channel_id:
        logger.info("🔥 General Channel Not Configured - Skipping Debates Scheduler")
        return

    bot.debates_scheduler = DebatesScheduler(lambda: post_hot_debate(bot), bot=bot)
    await bot.debates_scheduler.start(post_immediately=False)
    logger.tree("Automated Hot Debates Started", [
        ("Interval", "every 3 hours"),
    ], emoji="🔥")


async def _init_hot_tag_manager(bot: "OthmanBot") -> None:
    """Initialize Hot tag manager for debate forum.

    DESIGN: Runs every 10 minutes to dynamically manage the "Hot" tag
    Adds tag to threads with high activity (10+ messages in 1 hour, 20+ in 6 hours, etc.)
    Removes tag from threads with no activity for 6+ hours
    """
    bot.hot_tag_manager = HotTagManager(bot)
    await bot.hot_tag_manager.start()
    logger.tree("Hot Tag Manager Started", [
        ("Check Interval", "every 10 minutes"),
    ], emoji="🏷️")


async def _init_karma_reconciliation(bot: "OthmanBot") -> None:
    """Initialize karma reconciliation - startup scan and nightly scheduler.

    DESIGN: Catches any missed votes while bot was offline
    - Runs immediately on startup to reconcile recent threads
    - Schedules nightly sync at 00:30 EST for ongoing accuracy
    """
    # Run startup reconciliation in background (don't block bot startup)
    # Track the task for proper cleanup on shutdown
    reconciliation_task = asyncio.create_task(_run_startup_reconciliation(bot))
    reconciliation_task.add_done_callback(_handle_task_exception)
    if not hasattr(bot, '_background_tasks'):
        bot._background_tasks: List[asyncio.Task] = []
    bot._background_tasks.append(reconciliation_task)

    # Start nightly scheduler
    bot.karma_reconciliation_scheduler = KarmaReconciliationScheduler(
        lambda: reconcile_karma(bot)
    )
    await bot.karma_reconciliation_scheduler.start()


def _handle_task_exception(task: asyncio.Task) -> None:
    """Handle exceptions from background tasks to prevent silent failures."""
    try:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background Task Failed", [
                ("Task", task.get_name()),
                ("Error", str(exc)),
            ])
    except asyncio.CancelledError:
        pass


async def _run_startup_reconciliation(bot: "OthmanBot") -> None:
    """Run startup karma reconciliation after a short delay."""
    # Wait a bit for bot to fully initialize
    await asyncio.sleep(10)

    logger.info("🔄 Running Startup Karma Reconciliation")
    try:
        stats = await reconcile_karma(bot, days_back=7)
        logger.tree("Startup Reconciliation Complete", [
            ("Threads Scanned", str(stats['threads_scanned'])),
            ("Votes Added", f"+{stats['votes_added']}"),
            ("Votes Removed", f"-{stats['votes_removed']}"),
        ], emoji="🔄")
    except Exception as e:
        logger.error("🔄 Startup Karma Reconciliation Failed", [
            ("Error", str(e)),
        ])


async def _init_numbering_reconciliation(bot: "OthmanBot") -> None:
    """Initialize nightly debate numbering reconciliation scheduler.

    DESIGN: Runs at 00:00 EST every night to fix any gaps in debate numbering
    - Scans all non-deprecated debates
    - Renumbers threads to fill any gaps
    - Updates the counter file
    """
    bot.numbering_reconciliation_scheduler = NumberingReconciliationScheduler(
        lambda: reconcile_debate_numbering(bot)
    )
    await bot.numbering_reconciliation_scheduler.start()


async def _init_backup_scheduler(bot: "OthmanBot") -> None:
    """Initialize database backup scheduler.

    DESIGN: Runs daily at 3:00 AM EST
    Creates backup on startup, then schedules daily backups
    Automatically cleans up backups older than 7 days
    """
    bot.backup_scheduler = BackupScheduler()
    await bot.backup_scheduler.start(run_immediately=True)


async def _init_webhook_alerts(bot: "OthmanBot") -> None:
    """Initialize webhook alert service.

    DESIGN: Sends status alerts to Discord webhook
    - Startup alert on bot ready
    - Hourly status alerts with system health
    - Shutdown alert on bot close
    - Error alerts (no pings)
    """
    # Set bot reference (alert_service is already created in bot.__init__)
    bot.alert_service.set_bot(bot)

    # Send startup alert
    await bot.alert_service.send_startup_alert()

    # Start hourly status alerts
    await bot.alert_service.start_hourly_alerts()

    logger.tree("Webhook Alerts Initialized", [
        ("Status", "Enabled" if bot.alert_service.enabled else "Disabled"),
    ], emoji="🔔")


async def _init_leaderboard(bot: "OthmanBot") -> None:
    """Initialize debates leaderboard manager.

    DESIGN: Creates or finds leaderboard post in debates forum
    Updates hourly with monthly and all-time top 3 debaters
    Handles user leave/rejoin by showing "(left)" suffix
    """
    if not hasattr(bot, 'debates_service') or not bot.debates_service:
        logger.info("📊 Debates Service Not Initialized - Skipping Leaderboard")
        return

    try:
        # Run one-time backfill for debate stats (if tables are empty)
        await backfill_debate_stats(bot)

        bot.leaderboard_manager = LeaderboardManager(bot, bot.debates_service.db)
        await bot.leaderboard_manager.start()

        # Start nightly stats reconciliation scheduler (00:30 EST)
        bot.stats_reconciliation_scheduler = StatsReconciliationScheduler(
            lambda: reconcile_debate_stats(bot)
        )
        await bot.stats_reconciliation_scheduler.start()
    except Exception as e:
        logger.error("📊 Failed To Initialize Leaderboard", [
            ("Error", str(e)),
        ])


async def _leave_unauthorized_guilds(bot: "OthmanBot") -> None:
    """Leave any guilds that aren't in the ALLOWED_GUILD_IDS set.

    DESIGN: Ensures bot only operates in configured guilds (Syria + Mods)
    Runs at startup to automatically remove bot from unauthorized servers
    """
    unauthorized_guilds = [g for g in bot.guilds if g.id not in ALLOWED_GUILD_IDS]

    if not unauthorized_guilds:
        return

    for guild in unauthorized_guilds:
        try:
            logger.warning("Leaving Unauthorized Guild", [
                ("Guild", guild.name),
                ("ID", str(guild.id)),
                ("Members", str(guild.member_count)),
            ])
            await guild.leave()
            logger.info("Left Unauthorized Guild", [
                ("Guild", guild.name),
            ])
        except Exception as e:
            logger.error("Failed To Leave Guild", [
                ("Guild", guild.name),
                ("Error", str(e)),
            ])


async def _sync_commands(bot: "OthmanBot") -> None:
    """Sync slash commands to the Syria guild only.

    DESIGN: Guild-specific sync is instant, global sync takes up to 1 hour
    """
    try:
        guild = discord.Object(id=SYRIA_GUILD_ID)

        # Copy global commands (from Cog) to the guild, then sync
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logger.tree("Synced Commands To Syria Guild", [
            ("Commands", str(len(synced))),
        ], emoji="⚡")
    except Exception as e:
        logger.error("⚡ Failed To Sync Commands", [
            ("Error", str(e)),
        ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["on_ready_handler"]
