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
from discord.ext import commands

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

if TYPE_CHECKING:
    from src.bot import OthmanBot


# Default timeout for service initialization (seconds)
SERVICE_INIT_TIMEOUT: float = 30.0


class ReadyHandler(commands.Cog):
    """Handles bot ready event and service initialization."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Initialize services and start automation when bot is ready."""
        # Guard against multiple ready events (Discord reconnects)
        if self.bot._ready_initialized:
            logger.info("Bot Reconnected", [
                ("Guilds", str(len(self.bot.guilds))),
                ("Latency", f"{round(self.bot.latency * 1000)}ms"),
            ])
            # Refresh presence on reconnect
            try:
                await update_presence(self.bot)
            except Exception as e:
                logger.debug("Failed to refresh presence on reconnect", [("Error", str(e))])
            # Update status channel to show online
            try:
                await self.bot.update_status_channel(online=True)
            except Exception as e:
                logger.debug("Failed to update status channel on reconnect", [("Error", str(e))])
            return

        self.bot._ready_initialized = True
        await self._initialize_services()

    @commands.Cog.listener()
    async def on_resumed(self) -> None:
        """Handle bot connection resume."""
        logger.info("Bot Connection Resumed")

    async def _initialize_services(self) -> None:
        """Initialize all services with error recovery."""
        bot = self.bot
        init_results: List[tuple[str, bool]] = []

        # Leave unauthorized guilds first
        try:
            async with asyncio.timeout(15.0):
                await self._leave_unauthorized_guilds()
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

        # Sync slash commands
        try:
            async with asyncio.timeout(30.0):
                await self._sync_commands()
        except asyncio.TimeoutError:
            logger.error("Timeout syncing commands - continuing startup")

        # Initialize footer and banner
        try:
            await init_footer(bot)
        except Exception as e:
            logger.warning("Failed to initialize footer", [("Error", str(e))])

        try:
            await init_banner(bot)
        except Exception as e:
            logger.warning("Failed to initialize banner", [("Error", str(e))])

        # Initialize all services
        init_results.append(("Content Rotation", await self._safe_init("Content Rotation", self._init_content_rotation)))
        init_results.append(("Debates Scheduler", await self._safe_init("Debates Scheduler", self._init_debates_scheduler)))
        init_results.append(("Hot Tag Manager", await self._safe_init("Hot Tag Manager", self._init_hot_tag_manager)))
        init_results.append(("Open Discussion", await self._safe_init("Open Discussion", self._init_open_discussion)))
        init_results.append(("Karma Reconciliation", await self._safe_init("Karma Reconciliation", self._init_karma_reconciliation)))
        init_results.append(("Numbering Reconciliation", await self._safe_init("Numbering Reconciliation", self._init_numbering_reconciliation)))
        init_results.append(("Ban Expiry Scheduler", await self._safe_init("Ban Expiry Scheduler", self._init_ban_expiry_scheduler)))
        init_results.append(("Case Archive Scheduler", await self._safe_init("Case Archive Scheduler", self._init_case_archive_scheduler)))
        init_results.append(("Backup Scheduler", await self._safe_init("Backup Scheduler", self._init_backup_scheduler)))

        # Set initial presence
        try:
            async with asyncio.timeout(10.0):
                await update_presence(bot)
        except asyncio.TimeoutError:
            logger.warning("Timeout setting initial presence")
        except Exception as e:
            logger.warning("Failed to set initial presence", [("Error", str(e))])

        # Start presence update loop
        bot.presence_task = asyncio.create_task(presence_update_loop(bot))
        logger.info("Started Presence Update Loop", [("Interval", "60 seconds")])

        # Start promotional presence scheduler
        await start_promo_scheduler(bot)

        # Clean up old temp files
        cleanup_old_temp_files()
        logger.info("Cleaned Up Old Temp Files")

        # Start health check HTTP server
        try:
            bot.health_server = HealthCheckServer(bot)
            await bot.health_server.start()
            init_results.append(("Health Server", True))
        except Exception as e:
            logger.error("Failed To Start Health Server", [("Error", str(e))])
            init_results.append(("Health Server", False))

        # Start stats API server
        try:
            bot.stats_api = OthmanAPI(bot)
            await bot.stats_api.start()
            init_results.append(("Stats API", True))
        except Exception as e:
            logger.error("Failed To Start Stats API", [("Error", str(e))])
            init_results.append(("Stats API", False))

        # Initialize webhook alerts
        init_results.append(("Webhook Alerts", await self._safe_init("Webhook Alerts", self._init_webhook_alerts)))

        # Update status channel
        try:
            async with asyncio.timeout(10.0):
                await bot.update_status_channel(online=True)
        except asyncio.TimeoutError:
            logger.warning("Timeout updating status channel")
        except Exception as e:
            logger.warning("Failed to update status channel", [("Error", str(e))])

        # Refresh analytics embeds in background
        asyncio.create_task(self._refresh_analytics_background())

        # Log summary
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

    async def _safe_init(
        self,
        name: str,
        init_func: Callable[[], Awaitable[None]],
        timeout: float = SERVICE_INIT_TIMEOUT
    ) -> bool:
        """Safely initialize a service with timeout."""
        try:
            async with asyncio.timeout(timeout):
                await init_func()
            return True
        except asyncio.TimeoutError:
            logger.error("Timeout Initializing Service", [
                ("Service", name),
                ("Timeout", f"{timeout}s"),
            ])
            return False
        except Exception as e:
            logger.error("Failed To Initialize Service", [
                ("Service", name),
                ("Error", str(e)),
            ])
            return False

    async def _refresh_analytics_background(self) -> None:
        """Background task to refresh all analytics embeds."""
        try:
            await asyncio.sleep(5.0)
            from src.handlers.debates import refresh_all_analytics_embeds
            await refresh_all_analytics_embeds(self.bot)
        except Exception as e:
            logger.warning("Background analytics refresh failed", [("Error", str(e))])

    async def _init_content_rotation(self) -> None:
        """Initialize unified content rotation scheduler."""
        bot = self.bot
        bot.news_scraper = NewsScraper()
        await bot.news_scraper.__aenter__()

        bot.soccer_scraper = SoccerScraper()
        await bot.soccer_scraper.__aenter__()

        bot.content_rotation_scheduler = ContentRotationScheduler(
            news_callback=lambda: post_news(bot),
            soccer_callback=lambda: post_soccer_news(bot),
            news_scraper=bot.news_scraper,
            soccer_scraper=bot.soccer_scraper,
            bot=bot,
        )

        await bot.content_rotation_scheduler.start(post_immediately=False)
        logger.tree("Content Rotation Scheduler Started", [
            ("Rotation", "news → soccer"),
            ("Interval", "hourly"),
        ], emoji="🔄")

    async def _init_debates_scheduler(self) -> None:
        """Initialize debates scheduler."""
        bot = self.bot
        if not bot.general_channel_id:
            logger.info("General Channel Not Configured - Skipping Debates Scheduler")
            return

        bot.debates_scheduler = DebatesScheduler(lambda: post_hot_debate(bot), bot=bot)
        await bot.debates_scheduler.start(post_immediately=False)
        logger.tree("Automated Hot Debates Started", [("Interval", "every 3 hours")], emoji="🔥")

    async def _init_hot_tag_manager(self) -> None:
        """Initialize Hot tag manager."""
        bot = self.bot
        bot.hot_tag_manager = HotTagManager(bot)
        await bot.hot_tag_manager.start()
        logger.tree("Hot Tag Manager Started", [("Check Interval", "every 10 minutes")], emoji="🏷️")

    async def _init_open_discussion(self) -> None:
        """Initialize Open Discussion thread."""
        bot = self.bot
        if not hasattr(bot, 'open_discussion') or not bot.open_discussion:
            logger.info("Open Discussion Service Not Initialized - Skipping")
            return

        thread = await bot.open_discussion.ensure_thread_exists()
        if thread:
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
            logger.warning("Failed To Create Open Discussion Thread")

    async def _init_karma_reconciliation(self) -> None:
        """Initialize karma reconciliation."""
        bot = self.bot

        # Run startup reconciliation in background
        reconciliation_task = asyncio.create_task(self._run_startup_reconciliation())
        reconciliation_task.add_done_callback(_handle_task_exception)
        if not hasattr(bot, '_background_tasks'):
            bot._background_tasks: List[asyncio.Task] = []
        if len(bot._background_tasks) > 50:
            bot._background_tasks = [t for t in bot._background_tasks if not t.done()]
        bot._background_tasks.append(reconciliation_task)

        # Start nightly scheduler
        bot.karma_reconciliation_scheduler = KarmaReconciliationScheduler(
            lambda: reconcile_karma(bot, days_back=None),
            bot=bot
        )
        await bot.karma_reconciliation_scheduler.start()

    async def _run_startup_reconciliation(self) -> None:
        """Run combined startup reconciliation."""
        bot = self.bot
        await asyncio.sleep(BOT_STARTUP_DELAY)

        karma_stats = None
        karma_success = True
        numbering_stats = None
        numbering_success = True

        # Karma reconciliation
        logger.info("Running Startup Karma Reconciliation (Full Scan)")
        try:
            karma_stats = await reconcile_karma(bot, days_back=None)
            logger.tree("Startup Karma Reconciliation Complete", [
                ("Threads Scanned", str(karma_stats['threads_scanned'])),
                ("Votes Added", f"+{karma_stats['votes_added']}"),
                ("Votes Removed", f"-{karma_stats['votes_removed']}"),
            ], emoji="🔄")
        except Exception as e:
            logger.error("Startup Karma Reconciliation Failed", [("Error", str(e))])
            karma_success = False
            karma_stats = {"error": str(e)}

        # Numbering reconciliation
        logger.info("Running Startup Numbering Reconciliation")
        try:
            numbering_stats = await reconcile_debate_numbering(bot)
            if numbering_stats['gaps_found'] > 0:
                logger.tree("Startup Numbering Reconciliation Complete", [
                    ("Threads Scanned", str(numbering_stats['threads_scanned'])),
                    ("Gaps Found", str(numbering_stats['gaps_found'])),
                    ("Threads Renumbered", str(numbering_stats['threads_renumbered'])),
                ], emoji="🔢")
            else:
                logger.info("Startup Numbering Check Complete - No Gaps Found", [
                    ("Threads Scanned", str(numbering_stats['threads_scanned'])),
                ])
        except Exception as e:
            logger.error("Startup Numbering Reconciliation Failed", [("Error", str(e))])
            numbering_success = False
            numbering_stats = {"error": str(e)}

    async def _init_numbering_reconciliation(self) -> None:
        """Initialize numbering reconciliation scheduler."""
        bot = self.bot
        bot.numbering_reconciliation_scheduler = NumberingReconciliationScheduler(
            lambda: reconcile_debate_numbering(bot),
            bot=bot
        )
        await bot.numbering_reconciliation_scheduler.start()

    async def _init_backup_scheduler(self) -> None:
        """Initialize database backup scheduler."""
        self.bot.backup_scheduler = BackupScheduler()
        await self.bot.backup_scheduler.start(run_immediately=True)

    async def _init_webhook_alerts(self) -> None:
        """Initialize webhook alert service."""
        bot = self.bot
        bot.alert_service.set_bot(bot)
        await bot.alert_service.send_startup_alert()
        await bot.alert_service.start_hourly_alerts()
        logger.tree("Webhook Alerts Initialized", [
            ("Status", "Enabled" if bot.alert_service.enabled else "Disabled"),
        ], emoji="🔔")

    async def _init_ban_expiry_scheduler(self) -> None:
        """Initialize ban expiry scheduler."""
        bot = self.bot
        if not hasattr(bot, 'debates_service') or not bot.debates_service:
            logger.info("Debates Service Not Initialized - Skipping Ban Expiry Scheduler")
            return

        bot.ban_expiry_scheduler = BanExpiryScheduler(bot)
        await bot.ban_expiry_scheduler.start()
        logger.tree("Ban Expiry Scheduler Started", [("Check Interval", "every 1 minute")], emoji="⏰")

    async def _init_case_archive_scheduler(self) -> None:
        """Initialize case archive scheduler."""
        bot = self.bot
        if not hasattr(bot, 'case_log_service') or not bot.case_log_service:
            logger.info("Case Log Service Not Initialized - Skipping Case Archive Scheduler")
            return

        if not bot.case_log_service.enabled:
            logger.info("Case Log Service Disabled - Skipping Case Archive Scheduler")
            return

        bot.case_archive_scheduler = CaseArchiveScheduler(bot)
        await bot.case_archive_scheduler.start()
        logger.tree("Case Archive Scheduler Started", [
            ("Check Interval", "every 24 hours"),
            ("Inactivity Threshold", "7 days"),
        ], emoji="📦")

    async def _leave_unauthorized_guilds(self) -> None:
        """Leave guilds not in ALLOWED_GUILD_IDS."""
        unauthorized = [g for g in self.bot.guilds if g.id not in ALLOWED_GUILD_IDS]

        for guild in unauthorized:
            try:
                logger.warning("Leaving Unauthorized Guild", [
                    ("Guild", guild.name),
                    ("ID", str(guild.id)),
                ])
                await guild.leave()
            except Exception as e:
                logger.error("Failed To Leave Guild", [("Guild", guild.name), ("Error", str(e))])

    async def _sync_commands(self) -> None:
        """Sync slash commands to Syria guild."""
        try:
            guild = discord.Object(id=SYRIA_GUILD_ID)
            self.bot.tree.copy_global_to(guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            logger.tree("Synced Commands To Syria Guild", [("Commands", str(len(synced)))], emoji="⚡")
        except Exception as e:
            logger.error("Failed To Sync Commands", [("Error", str(e))])


def _handle_task_exception(task: asyncio.Task) -> None:
    """Handle exceptions from background tasks."""
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


async def setup(bot: "OthmanBot") -> None:
    """Load the ReadyHandler cog."""
    await bot.add_cog(ReadyHandler(bot))
    logger.tree("Handler Loaded", [
        ("Name", "ReadyHandler"),
    ], emoji="✅")
