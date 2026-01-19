"""
OthmanBot - Ready Handler
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
from src.core.constants import TIMEOUT_LONG, TIMEOUT_MEDIUM, TIMEOUT_EXTENDED, SLEEP_STARTUP_DELAY
from src.core.health import HealthCheckServer
from src.core.presence import setup_presence
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
from src.services.schedulers.maintenance import MaintenanceScheduler
from src.services.debates.scheduler import DebatesScheduler
from src.services.debates.maintenance_scheduler import DebateMaintenanceScheduler
from src.services.debates.reconciliation import reconcile_karma
from src.services.debates.numbering_scheduler import reconcile_debate_numbering
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
        logger.info("Bot Connection Resumed", [
            ("Status", "Reconnected to Discord"),
        ])

    async def _initialize_services(self) -> None:
        """Initialize all services with error recovery."""
        bot = self.bot
        init_results: List[tuple[str, bool]] = []

        # Leave unauthorized guilds first
        try:
            async with asyncio.timeout(TIMEOUT_LONG):
                await self._leave_unauthorized_guilds()
        except asyncio.TimeoutError:
            logger.warning("Timeout Leaving Unauthorized Guilds", [
                ("Timeout", f"{TIMEOUT_LONG}s"),
                ("Action", "Continuing startup"),
            ])

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
            async with asyncio.timeout(TIMEOUT_EXTENDED):
                await self._sync_commands()
        except asyncio.TimeoutError:
            logger.error("Timeout Syncing Commands", [
                ("Timeout", f"{TIMEOUT_EXTENDED}s"),
                ("Action", "Continuing startup"),
            ])

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
        init_results.append(("Maintenance Scheduler", await self._safe_init("Maintenance Scheduler", self._init_maintenance_scheduler)))
        init_results.append(("Debates Scheduler", await self._safe_init("Debates Scheduler", self._init_debates_scheduler)))
        init_results.append(("Debate Maintenance", await self._safe_init("Debate Maintenance", self._init_debate_maintenance)))
        init_results.append(("Open Discussion", await self._safe_init("Open Discussion", self._init_open_discussion)))
        init_results.append(("Startup Reconciliation", await self._safe_init("Startup Reconciliation", self._init_startup_reconciliation)))
        init_results.append(("Ban Expiry Scheduler", await self._safe_init("Ban Expiry Scheduler", self._init_ban_expiry_scheduler)))
        init_results.append(("Case Archive Scheduler", await self._safe_init("Case Archive Scheduler", self._init_case_archive_scheduler)))
        init_results.append(("Backup Scheduler", await self._safe_init("Backup Scheduler", self._init_backup_scheduler)))

        # Start presence handler (rotation + promo)
        try:
            bot.presence_handler = await setup_presence(bot)
        except Exception as e:
            logger.warning("Failed To Start Presence Handler", [
                ("Error", str(e)[:50]),
            ])

        # Clean up old temp files
        cleanup_old_temp_files()
        logger.info("Cleaned Up Old Temp Files", [
            ("Action", "Removed expired temp files"),
        ])

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
            logger.warning("Timeout Updating Status Channel", [
                ("Timeout", "10s"),
            ])
        except Exception as e:
            logger.warning("Failed to update status channel", [("Error", str(e))])

        # Refresh analytics embeds in background
        analytics_task = asyncio.create_task(self._refresh_analytics_background())
        analytics_task.add_done_callback(_handle_task_exception)

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
            await asyncio.sleep(SLEEP_STARTUP_DELAY)
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

    async def _init_maintenance_scheduler(self) -> None:
        """Initialize maintenance scheduler for cleanup and engagement tracking."""
        bot = self.bot

        bot.maintenance_scheduler = MaintenanceScheduler(bot)

        # Warm the cache before starting
        await bot.maintenance_scheduler.warm_cache()

        # Start the scheduler
        bot.maintenance_scheduler.start()

        logger.tree("Maintenance Scheduler Initialized", [
            ("Engagement Check", "every 2 hours"),
            ("Cleanup", "every 6 hours"),
            ("Cache", "warmed"),
        ], emoji="🔧")

    async def _init_debates_scheduler(self) -> None:
        """Initialize debates scheduler."""
        bot = self.bot
        if not bot.general_channel_id:
            logger.info("Skipping Debates Scheduler", [
                ("Reason", "General channel not configured"),
            ])
            return

        bot.debates_scheduler = DebatesScheduler(lambda: post_hot_debate(bot), bot=bot)
        await bot.debates_scheduler.start(post_immediately=False)
        logger.tree("Automated Hot Debates Started", [("Interval", "every 3 hours")], emoji="🔥")

    async def _init_debate_maintenance(self) -> None:
        """Initialize centralized debate maintenance scheduler."""
        bot = self.bot
        bot.debate_maintenance_scheduler = DebateMaintenanceScheduler(bot)
        await bot.debate_maintenance_scheduler.start()

    async def _init_open_discussion(self) -> None:
        """Initialize Open Discussion thread."""
        bot = self.bot
        if not hasattr(bot, 'open_discussion') or not bot.open_discussion:
            logger.info("Skipping Open Discussion", [
                ("Reason", "Service not initialized"),
            ])
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
            logger.warning("Failed To Create Open Discussion Thread", [
                ("Action", "Thread creation returned None"),
            ])

    async def _init_startup_reconciliation(self) -> None:
        """Run startup reconciliation in background."""
        bot = self.bot

        # Run startup reconciliation in background
        reconciliation_task = asyncio.create_task(self._run_startup_reconciliation())
        reconciliation_task.add_done_callback(_handle_task_exception)
        if not hasattr(bot, '_background_tasks'):
            bot._background_tasks: List[asyncio.Task] = []
        if len(bot._background_tasks) > 50:
            bot._background_tasks = [t for t in bot._background_tasks if not t.done()]
        bot._background_tasks.append(reconciliation_task)

    async def _run_startup_reconciliation(self) -> None:
        """Run combined startup reconciliation."""
        bot = self.bot
        await asyncio.sleep(BOT_STARTUP_DELAY)

        # Karma reconciliation
        logger.info("Running Startup Karma Reconciliation", [
            ("Mode", "Full scan"),
            ("Days Back", "All"),
        ])
        try:
            karma_stats = await reconcile_karma(bot, days_back=None)
            logger.tree("Startup Karma Reconciliation Complete", [
                ("Threads Scanned", str(karma_stats['threads_scanned'])),
                ("Votes Added", f"+{karma_stats['votes_added']}"),
                ("Votes Removed", f"-{karma_stats['votes_removed']}"),
            ], emoji="🔄")
        except Exception as e:
            logger.error("Startup Karma Reconciliation Failed", [("Error", str(e))])

        # Numbering reconciliation
        logger.info("Running Startup Numbering Reconciliation", [
            ("Mode", "Full scan"),
        ])
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
            logger.info("Skipping Ban Expiry Scheduler", [
                ("Reason", "Debates service not initialized"),
            ])
            return

        bot.ban_expiry_scheduler = BanExpiryScheduler(bot)
        await bot.ban_expiry_scheduler.start()
        logger.tree("Ban Expiry Scheduler Started", [("Check Interval", "every 1 minute")], emoji="⏰")

    async def _init_case_archive_scheduler(self) -> None:
        """Initialize case archive scheduler."""
        bot = self.bot
        if not hasattr(bot, 'case_log_service') or not bot.case_log_service:
            logger.info("Skipping Case Archive Scheduler", [
                ("Reason", "Case log service not initialized"),
            ])
            return

        if not bot.case_log_service.enabled:
            logger.info("Skipping Case Archive Scheduler", [
                ("Reason", "Case log service disabled"),
            ])
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
        """Sync slash commands to Syria guild only (not globally)."""
        try:
            # First, clear any global commands so they don't appear in other servers
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync()  # Sync empty global commands
            logger.debug("Cleared Global Commands")

            # Now sync commands only to the main Syria guild
            guild = discord.Object(id=SYRIA_GUILD_ID)
            self.bot.tree.copy_global_to(guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            logger.tree("Synced Commands To Syria Guild Only", [
                ("Commands", str(len(synced))),
                ("Guild ID", str(SYRIA_GUILD_ID)),
                ("Global Commands", "Cleared"),
            ], emoji="⚡")
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
