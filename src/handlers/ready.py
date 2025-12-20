"""
Othman Discord Bot - Ready Handler
===================================

Service initialization and startup logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable, List

import discord

from src.core.logger import logger
from src.core.config import SYRIA_GUILD_ID, ALLOWED_GUILD_IDS, BOT_STARTUP_DELAY
from src.core.health import HealthCheckServer
from src.core.presence import update_presence, presence_update_loop, start_promo_scheduler
from src.core.backup import BackupScheduler
from src.utils.footer import init_footer
from src.utils.banner import init_banner
from src.posting.poster import cleanup_old_temp_files
from src.services import (
    NewsScraper,
    SoccerScraper,
)
from src.services.stats_api import OthmanAPI
from src.services.schedulers.rotation import ContentRotationScheduler
from src.services.debates.scheduler import DebatesScheduler
from src.services.debates.hot_tag_manager import HotTagManager
from src.services.debates.reconciliation import reconcile_karma
from src.services.debates.karma_scheduler import KarmaReconciliationScheduler
from src.services.debates.numbering_scheduler import (
    NumberingReconciliationScheduler,
    reconcile_debate_numbering,
)
from src.services.debates.ban_expiry_scheduler import BanExpiryScheduler
from src.services.case_archive_scheduler import CaseArchiveScheduler
from src.posting.news import post_news
from src.posting.soccer import post_soccer_news
from src.posting.debates import post_hot_debate
from src.handlers.debates import refresh_all_analytics_embeds

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Ready Handler
# =============================================================================

# Default timeout for service initialization (seconds)
SERVICE_INIT_TIMEOUT: float = 30.0


async def _safe_init(
    name: str,
    init_func: Callable[["OthmanBot"], Awaitable[None]],
    bot: "OthmanBot",
    timeout: float = SERVICE_INIT_TIMEOUT
) -> bool:
    """
    Safely initialize a service with error recovery and timeout.

    Args:
        name: Human-readable service name for logging
        init_func: Async function to call
        bot: The OthmanBot instance
        timeout: Maximum seconds to wait for initialization

    Returns:
        True if initialization succeeded, False otherwise

    DESIGN: Prevents hanging services from blocking entire startup
    Each service gets a timeout (default 30s) to initialize
    Timeout errors are logged but don't crash the bot
    """
    try:
        async with asyncio.timeout(timeout):
            await init_func(bot)
        return True
    except asyncio.TimeoutError:
        logger.error("Timeout Initializing Service", [
            ("Service", name),
            ("Timeout", f"{timeout}s"),
            ("Status", "Skipped - continuing startup"),
        ])
        return False
    except Exception as e:
        logger.error("Failed To Initialize Service", [
            ("Service", name),
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
            ("Status", "Skipped - continuing startup"),
        ])
        return False


async def _refresh_analytics_background(bot: "OthmanBot") -> None:
    """
    Background task to refresh all analytics embeds on startup.

    This ensures all existing debate threads get updated embeds
    with any new fields (like created_at timestamp).
    """
    try:
        # Small delay to let other startup tasks complete first
        await asyncio.sleep(5.0)
        await refresh_all_analytics_embeds(bot)
    except Exception as e:
        logger.warning("Background analytics refresh failed", [
            ("Error", str(e)),
        ])


async def on_ready_handler(bot: "OthmanBot") -> None:
    """
    Initialize services and start automation when bot is ready.

    Args:
        bot: The OthmanBot instance

    DESIGN: Initializes all services with error recovery
    Each service failure is logged but doesn't block other services
    Bot continues running even if some services fail to start
    """
    # Track initialization results
    init_results: List[tuple[str, bool]] = []

    # Leave unauthorized guilds first (with timeout)
    try:
        async with asyncio.timeout(15.0):
            await _leave_unauthorized_guilds(bot)
    except asyncio.TimeoutError:
        logger.warning("Timeout leaving unauthorized guilds - continuing startup")

    logger.tree(
        f"Bot Ready: {bot.user.name}",
        [
            ("Bot ID", str(bot.user.id)),
            ("Guilds", str(len(bot.guilds))),
            ("Mode", "Fully Automated"),
            ("News Channel", str(bot.news_channel_id) if bot.news_channel_id else "Not Set"),
            ("Soccer Channel", str(bot.soccer_channel_id) if bot.soccer_channel_id else "Not Set"),
        ],
        emoji="✅",
    )

    # Sync slash commands (critical - but continue if fails, with timeout)
    try:
        async with asyncio.timeout(30.0):
            await _sync_commands(bot)
    except asyncio.TimeoutError:
        logger.error("Timeout syncing commands - continuing startup")

    # Initialize footer with cached avatar (for embed footers)
    try:
        await init_footer(bot)
    except Exception as e:
        logger.warning("Failed to initialize footer", [("Error", str(e))])

    # Initialize bot banner from server banner
    try:
        await init_banner(bot)
    except Exception as e:
        logger.warning("Failed to initialize banner", [("Error", str(e))])

    # Initialize all services with error recovery
    # Each service can fail independently without blocking others
    init_results.append(("Content Rotation", await _safe_init("Content Rotation", _init_content_rotation, bot)))
    init_results.append(("Debates Scheduler", await _safe_init("Debates Scheduler", _init_debates_scheduler, bot)))
    init_results.append(("Hot Tag Manager", await _safe_init("Hot Tag Manager", _init_hot_tag_manager, bot)))
    init_results.append(("Open Discussion", await _safe_init("Open Discussion", _init_open_discussion, bot)))
    init_results.append(("Karma Reconciliation", await _safe_init("Karma Reconciliation", _init_karma_reconciliation, bot)))
    init_results.append(("Numbering Reconciliation", await _safe_init("Numbering Reconciliation", _init_numbering_reconciliation, bot)))
    init_results.append(("Ban Expiry Scheduler", await _safe_init("Ban Expiry Scheduler", _init_ban_expiry_scheduler, bot)))
    init_results.append(("Case Archive Scheduler", await _safe_init("Case Archive Scheduler", _init_case_archive_scheduler, bot)))
    init_results.append(("Backup Scheduler", await _safe_init("Backup Scheduler", _init_backup_scheduler, bot)))

    # Set initial presence (non-critical, with timeout)
    try:
        async with asyncio.timeout(10.0):
            await update_presence(bot)
    except asyncio.TimeoutError:
        logger.warning("Timeout setting initial presence")
    except Exception as e:
        logger.warning("Failed to set initial presence", [("Error", str(e))])

    # Start presence update loop
    bot.presence_task = asyncio.create_task(presence_update_loop(bot))
    logger.info("🔄 Started Presence Update Loop", [
        ("Interval", "60 seconds"),
    ])

    # Start promotional presence scheduler (shows trippixn.com/othman on the hour)
    await start_promo_scheduler(bot)

    # Clean up old temp files from previous sessions
    cleanup_old_temp_files()
    logger.info("🧹 Cleaned Up Old Temp Files")

    # Start health check HTTP server (critical for monitoring)
    try:
        bot.health_server = HealthCheckServer(bot)
        await bot.health_server.start()
        init_results.append(("Health Server", True))
    except Exception as e:
        logger.error("Failed To Start Health Server", [("Error", str(e))])
        init_results.append(("Health Server", False))

    # Start stats API server (for dashboard)
    try:
        bot.stats_api = OthmanAPI(bot)
        await bot.stats_api.start()
        init_results.append(("Stats API", True))
    except Exception as e:
        logger.error("Failed To Start Stats API", [("Error", str(e))])
        init_results.append(("Stats API", False))

    # Initialize webhook alerts
    init_results.append(("Webhook Alerts", await _safe_init("Webhook Alerts", _init_webhook_alerts, bot)))

    # Update status channel to show online (with timeout)
    try:
        async with asyncio.timeout(10.0):
            await bot.update_status_channel(online=True)
    except asyncio.TimeoutError:
        logger.warning("Timeout updating status channel")
    except Exception as e:
        logger.warning("Failed to update status channel", [("Error", str(e))])

    # One-time migration: refresh all analytics embeds to include new fields
    # This runs in the background to avoid blocking startup
    asyncio.create_task(_refresh_analytics_background(bot))

    # Log initialization summary
    succeeded = sum(1 for _, ok in init_results if ok)
    failed = sum(1 for _, ok in init_results if not ok)

    if failed > 0:
        failed_services = [name for name, ok in init_results if not ok]
        logger.warning("Startup Completed With Errors", [
            ("Services OK", str(succeeded)),
            ("Services Failed", str(failed)),
            ("Failed", ", ".join(failed_services)),
        ])
    else:
        logger.tree("All Services Initialized", [
            ("Services", str(succeeded)),
            ("Status", "All OK"),
        ], emoji="✅")


# =============================================================================
# Service Initialization
# =============================================================================

async def _init_content_rotation(bot: "OthmanBot") -> None:
    """Initialize unified content rotation scheduler.

    DESIGN: Rotates through news → soccer content hourly
    Posts only ONE content type per hour to save OpenAI API tokens
    Skips content types with no new unposted articles
    State persists across bot restarts
    """
    # Initialize all scrapers
    bot.news_scraper = NewsScraper()
    await bot.news_scraper.__aenter__()

    bot.soccer_scraper = SoccerScraper()
    await bot.soccer_scraper.__aenter__()

    # Create unified content rotation scheduler
    bot.content_rotation_scheduler = ContentRotationScheduler(
        news_callback=lambda: post_news(bot),
        soccer_callback=lambda: post_soccer_news(bot),
        news_scraper=bot.news_scraper,
        soccer_scraper=bot.soccer_scraper,
        bot=bot,
    )

    # Start the rotation scheduler
    await bot.content_rotation_scheduler.start(post_immediately=False)
    logger.tree("Content Rotation Scheduler Started", [
        ("Rotation", "news → soccer"),
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


async def _init_open_discussion(bot: "OthmanBot") -> None:
    """Initialize Open Discussion thread in debates forum.

    DESIGN: Creates a pinned "Open Discussion" thread for casual conversation
    - No karma tracking (upvotes/downvotes don't affect score)
    - Sticky rules message that reposts every 25 messages
    - Users must acknowledge rules before posting
    """
    if not hasattr(bot, 'open_discussion') or not bot.open_discussion:
        logger.info("💬 Open Discussion Service Not Initialized - Skipping")
        return

    # Ensure the thread exists (creates if needed)
    thread = await bot.open_discussion.ensure_thread_exists()
    if thread:
        # Check pinned status using flags (for forum threads)
        is_pinned = False
        if hasattr(thread, 'flags') and hasattr(thread.flags, 'pinned'):
            is_pinned = thread.flags.pinned
        elif hasattr(thread, 'pinned'):
            is_pinned = thread.pinned

        logger.tree("Open Discussion Thread Ready", [
            ("Thread ID", str(thread.id)),
            ("Thread Name", thread.name),
            ("Pinned", "Yes" if is_pinned else "No"),
        ], emoji="💬")
    else:
        logger.warning("💬 Failed To Create Open Discussion Thread")


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
    # Cleanup completed tasks to prevent memory leak (cleanup more aggressively if list is large)
    if len(bot._background_tasks) > 50:
        _cleanup_completed_tasks(bot)
    bot._background_tasks.append(reconciliation_task)

    # Start nightly scheduler (pass bot for webhook alerts)
    # Uses days_back=None for full scan of ALL threads at midnight
    bot.karma_reconciliation_scheduler = KarmaReconciliationScheduler(
        lambda: reconcile_karma(bot, days_back=None),
        bot=bot
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


def _cleanup_completed_tasks(bot: "OthmanBot") -> None:
    """Remove completed tasks from the background tasks list to prevent memory leak."""
    if hasattr(bot, '_background_tasks'):
        bot._background_tasks = [t for t in bot._background_tasks if not t.done()]


async def _run_startup_reconciliation(bot: "OthmanBot") -> None:
    """Run combined startup reconciliation (karma + numbering) after a short delay."""
    # Wait a bit for bot to fully initialize
    await asyncio.sleep(BOT_STARTUP_DELAY)

    # Track results for combined webhook
    karma_stats = None
    karma_success = True
    numbering_stats = None
    numbering_success = True

    # Run karma reconciliation
    logger.info("🔄 Running Startup Karma Reconciliation (Full Scan)")
    try:
        # Scan ALL threads (days_back=None) for 100% accuracy at startup
        karma_stats = await reconcile_karma(bot, days_back=None)
        logger.tree("Startup Karma Reconciliation Complete", [
            ("Threads Scanned", str(karma_stats['threads_scanned'])),
            ("Votes Added", f"+{karma_stats['votes_added']}"),
            ("Votes Removed", f"-{karma_stats['votes_removed']}"),
        ], emoji="🔄")
    except Exception as e:
        logger.error("🔄 Startup Karma Reconciliation Failed", [
            ("Error", str(e)),
        ])
        karma_success = False
        karma_stats = {"error": str(e)}

    # Run numbering reconciliation
    logger.info("🔢 Running Startup Numbering Reconciliation")
    try:
        numbering_stats = await reconcile_debate_numbering(bot)
        if numbering_stats['gaps_found'] > 0:
            logger.tree("Startup Numbering Reconciliation Complete", [
                ("Threads Scanned", str(numbering_stats['threads_scanned'])),
                ("Gaps Found", str(numbering_stats['gaps_found'])),
                ("Threads Renumbered", str(numbering_stats['threads_renumbered'])),
            ], emoji="🔢")
        else:
            logger.info("🔢 Startup Numbering Check Complete - No Gaps Found", [
                ("Threads Scanned", str(numbering_stats['threads_scanned'])),
            ])
    except Exception as e:
        logger.error("🔢 Startup Numbering Reconciliation Failed", [
            ("Error", str(e)),
        ])
        numbering_success = False
        numbering_stats = {"error": str(e)}

    # Send combined webhook
    if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
        await bot.interaction_logger.log_startup_reconciliation(
            karma_stats=karma_stats,
            numbering_stats=numbering_stats,
            karma_success=karma_success,
            numbering_success=numbering_success
        )


async def _init_numbering_reconciliation(bot: "OthmanBot") -> None:
    """Initialize numbering reconciliation nightly scheduler.

    DESIGN: Ensures debate numbers are always sequential
    - Startup scan is handled by _run_startup_reconciliation (combined with karma)
    - Schedules nightly sync at 00:15 EST for ongoing accuracy
    """
    # Start nightly scheduler (startup scan is now combined in _run_startup_reconciliation)
    bot.numbering_reconciliation_scheduler = NumberingReconciliationScheduler(
        lambda: reconcile_debate_numbering(bot),
        bot=bot
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


async def _init_ban_expiry_scheduler(bot: "OthmanBot") -> None:
    """Initialize ban expiry scheduler for automatic unbans.

    DESIGN: Runs every 1 minute to check for expired bans
    - Automatically removes bans that have passed their expires_at timestamp
    - Logs all automatic unbans for audit trail
    """
    if not hasattr(bot, 'debates_service') or not bot.debates_service:
        logger.info("⏰ Debates Service Not Initialized - Skipping Ban Expiry Scheduler")
        return

    bot.ban_expiry_scheduler = BanExpiryScheduler(bot)
    await bot.ban_expiry_scheduler.start()
    logger.tree("Ban Expiry Scheduler Started", [
        ("Check Interval", "every 1 minute"),
    ], emoji="⏰")


async def _init_case_archive_scheduler(bot: "OthmanBot") -> None:
    """Initialize case archive scheduler for auto-archiving inactive case threads.

    DESIGN: Runs every 24 hours to archive inactive case threads
    - Archives threads that have been inactive for 7+ days
    - Keeps forum clean while preserving case history
    """
    if not hasattr(bot, 'case_log_service') or not bot.case_log_service:
        logger.info("📦 Case Log Service Not Initialized - Skipping Case Archive Scheduler")
        return

    if not bot.case_log_service.enabled:
        logger.info("📦 Case Log Service Disabled - Skipping Case Archive Scheduler")
        return

    bot.case_archive_scheduler = CaseArchiveScheduler(bot)
    await bot.case_archive_scheduler.start()
    logger.tree("Case Archive Scheduler Started", [
        ("Check Interval", "every 24 hours"),
        ("Inactivity Threshold", "7 days"),
    ], emoji="📦")


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
