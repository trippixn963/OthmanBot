"""
OthmanBot - Centralized Maintenance Scheduler
==============================================

Single scheduler managing all nightly and hourly maintenance tasks.
All schedule times defined in one place for easy visibility and modification.

Author: Claude Code
Server: discord.gg/syria
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Awaitable, Optional, Any

from src.core.logger import logger
from src.core.config import NY_TZ, SECONDS_PER_HOUR

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Schedule Configuration - ALL maintenance times in one place
# =============================================================================

@dataclass
class ScheduledTask:
    """Configuration for a scheduled maintenance task."""
    name: str
    hour: int
    minute: int
    callback_name: str  # Method name on DebateMaintenanceScheduler to call
    description: str


@dataclass
class HourlyTask:
    """Configuration for an hourly maintenance task."""
    name: str
    callback_name: str
    description: str


# Daily tasks - run once per day at specified EST time
DAILY_SCHEDULE: list[ScheduledTask] = [
    ScheduledTask(
        name="hot_tag_evaluation",
        hour=0, minute=0,
        callback_name="_run_hot_tag_evaluation",
        description="Evaluate and update Hot tags on debates",
    ),
    ScheduledTask(
        name="karma_reconciliation",
        hour=0, minute=10,
        callback_name="_run_karma_reconciliation",
        description="Reconcile karma from votes + cleanup orphans",
    ),
    ScheduledTask(
        name="stale_archive",
        hour=0, minute=20,
        callback_name="_run_stale_archive",
        description="Archive debates inactive for 14+ days",
    ),
    ScheduledTask(
        name="numbering_reconciliation",
        hour=0, minute=35,
        callback_name="_run_numbering_reconciliation",
        description="Fix gaps in debate numbering",
    ),
    ScheduledTask(
        name="stats_reconciliation",
        hour=0, minute=50,
        callback_name="_run_stats_reconciliation",
        description="Reconcile debate participation stats",
    ),
]

# Hourly tasks - run at the top of every hour
HOURLY_SCHEDULE: list[HourlyTask] = [
    HourlyTask(
        name="unnumbered_check",
        callback_name="_run_unnumbered_check",
        description="Number threads missed during downtime",
    ),
]


# =============================================================================
# Maintenance Scheduler
# =============================================================================

class DebateMaintenanceScheduler:
    """
    Centralized scheduler for all maintenance tasks.

    Benefits:
    - All schedule times visible in one place
    - Consistent error handling and logging
    - Single point of control for start/stop
    - No code duplication across schedulers
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the maintenance scheduler.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot
        self._running = False
        self._daily_tasks: list[asyncio.Task] = []
        self._hourly_tasks: list[asyncio.Task] = []

    # -------------------------------------------------------------------------
    # Start / Stop
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start all maintenance schedulers."""
        if self._running:
            logger.warning("Maintenance Scheduler Already Running", [
                ("Action", "Skipping start"),
            ])
            return

        self._running = True

        # Start daily task schedulers
        for task_config in DAILY_SCHEDULE:
            task = asyncio.create_task(
                self._daily_task_loop(task_config),
                name=f"maintenance_{task_config.name}"
            )
            task.add_done_callback(self._handle_task_exception)
            self._daily_tasks.append(task)

        # Start hourly task schedulers
        for task_config in HOURLY_SCHEDULE:
            task = asyncio.create_task(
                self._hourly_task_loop(task_config),
                name=f"maintenance_{task_config.name}"
            )
            task.add_done_callback(self._handle_task_exception)
            self._hourly_tasks.append(task)

        # Log the full schedule
        self._log_schedule()

    async def stop(self) -> None:
        """Stop all maintenance schedulers."""
        self._running = False

        # Cancel all daily tasks
        for task in self._daily_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Cancel all hourly tasks
        for task in self._hourly_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._daily_tasks.clear()
        self._hourly_tasks.clear()

        logger.tree("Maintenance Scheduler Stopped", [
            ("Daily Tasks", str(len(DAILY_SCHEDULE))),
            ("Hourly Tasks", str(len(HOURLY_SCHEDULE))),
        ], emoji="🛑")

    def _log_schedule(self) -> None:
        """Log the complete maintenance schedule."""
        schedule_lines = []
        for task in DAILY_SCHEDULE:
            schedule_lines.append(f"{task.hour:02d}:{task.minute:02d} - {task.name}")
        for task in HOURLY_SCHEDULE:
            schedule_lines.append(f"Hourly - {task.name}")

        logger.tree("Maintenance Scheduler Started", [
            ("Daily Tasks", str(len(DAILY_SCHEDULE))),
            ("Hourly Tasks", str(len(HOURLY_SCHEDULE))),
            ("Schedule", " | ".join(schedule_lines)),
        ], emoji="🔧")

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle uncaught exceptions from scheduler tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.tree("Maintenance Task Exception", [
                ("Task", task.get_name()),
                ("Error Type", type(exc).__name__),
                ("Error", str(exc)[:100]),
            ], emoji="❌")

    # -------------------------------------------------------------------------
    # Task Loops
    # -------------------------------------------------------------------------

    async def _daily_task_loop(self, config: ScheduledTask) -> None:
        """
        Loop that runs a task once daily at the specified time.

        Args:
            config: The task configuration
        """
        while self._running:
            try:
                # Calculate time until next run
                now = datetime.now(NY_TZ)
                target = now.replace(
                    hour=config.hour,
                    minute=config.minute,
                    second=0,
                    microsecond=0
                )

                # If past today's time, schedule for tomorrow
                if now >= target:
                    target += timedelta(days=1)

                wait_seconds = (target - now).total_seconds()

                logger.debug(f"Scheduled: {config.name}", [
                    ("Next Run", target.strftime("%Y-%m-%d %H:%M EST")),
                    ("Wait", f"{wait_seconds / 3600:.1f}h"),
                ])

                # Wait until target time
                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                # Run the task
                await self._execute_task(config.name, config.callback_name, config.description)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.tree(f"Error In {config.name} Scheduler", [
                    ("Error", str(e)[:100]),
                ], emoji="❌")
                await self._send_error_webhook(f"{config.name} Scheduler Error", str(e))
                # Wait 1 hour before retrying
                await asyncio.sleep(SECONDS_PER_HOUR)

    async def _hourly_task_loop(self, config: HourlyTask) -> None:
        """
        Loop that runs a task at the top of every hour.

        Args:
            config: The task configuration
        """
        while self._running:
            try:
                # Calculate time until next hour
                now = datetime.now(NY_TZ)
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                wait_seconds = (next_hour - now).total_seconds()

                logger.debug(f"Scheduled: {config.name}", [
                    ("Next Run", next_hour.strftime("%H:%M EST")),
                    ("Wait", f"{wait_seconds / 60:.1f}m"),
                ])

                # Wait until top of hour
                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                # Run the task
                await self._execute_task(config.name, config.callback_name, config.description)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.tree(f"Error In {config.name} Scheduler", [
                    ("Error", str(e)[:100]),
                ], emoji="❌")
                # Wait 5 min before retrying hourly task
                await asyncio.sleep(300)

    async def _execute_task(self, name: str, callback_name: str, description: str) -> None:
        """
        Execute a maintenance task with consistent logging.

        Args:
            name: Task name for logging
            callback_name: Method name to call on self
            description: Task description
        """
        start_time = datetime.now(NY_TZ)

        logger.tree(f"Starting: {name}", [
            ("Time", start_time.strftime("%H:%M:%S EST")),
            ("Description", description),
        ], emoji="▶️")

        try:
            # Get and call the callback method
            callback = getattr(self, callback_name, None)
            if callback is None:
                logger.warning("Callback Not Found", [
                    ("Callback", callback_name),
                    ("Task", name),
                ])
                return

            stats = await callback()

            # Calculate duration
            duration = (datetime.now(NY_TZ) - start_time).total_seconds()

            # Log completion with stats
            log_items = [("Duration", f"{duration:.1f}s")]
            if isinstance(stats, dict):
                for key, value in stats.items():
                    if key != "error":
                        log_items.append((key.replace("_", " ").title(), str(value)))

            logger.tree(f"Completed: {name}", log_items, emoji="✅")

        except Exception as e:
            duration = (datetime.now(NY_TZ) - start_time).total_seconds()
            logger.tree(f"Failed: {name}", [
                ("Duration", f"{duration:.1f}s"),
                ("Error", str(e)[:100]),
            ], emoji="❌")
            await self._send_error_webhook(f"{name} Failed", str(e))

    # -------------------------------------------------------------------------
    # Task Implementations
    # -------------------------------------------------------------------------

    async def _run_hot_tag_evaluation(self) -> dict:
        """Run hot tag evaluation on all debate threads."""
        from src.services.debates.hot_tag_manager import evaluate_hot_tags
        return await evaluate_hot_tags(self.bot)

    async def _run_karma_reconciliation(self) -> dict:
        """Run karma reconciliation and orphan vote cleanup."""
        from src.services.debates.reconciliation import reconcile_karma
        from src.services.debates.reconciliation import cleanup_orphan_votes

        # Run karma reconciliation
        stats = await reconcile_karma(self.bot, days_back=None)

        # Cleanup orphan votes
        try:
            orphan_stats = await cleanup_orphan_votes(self.bot)
            stats["orphan_votes_cleaned"] = orphan_stats.get("total_cleaned", 0)
        except Exception as e:
            logger.warning("Orphan Vote Cleanup Failed", [
                ("Error", str(e)[:50]),
            ])

        # Refresh avatar/banner at midnight
        try:
            if hasattr(self.bot, 'debates_service') and self.bot.debates_service:
                self.bot.debates_service.refresh_avatar()
                self.bot.debates_service.refresh_banner()
        except Exception:
            pass

        return stats

    async def _run_stale_archive(self) -> dict:
        """Run stale debate archival."""
        from src.services.debates.stale_archive_manager import archive_stale_debates
        return await archive_stale_debates(self.bot)

    async def _run_numbering_reconciliation(self) -> dict:
        """Run debate numbering reconciliation."""
        from src.services.debates.numbering_scheduler import reconcile_debate_numbering
        return await reconcile_debate_numbering(self.bot)

    async def _run_stats_reconciliation(self) -> dict:
        """Run debate stats reconciliation."""
        from src.services.debates.backfill import reconcile_debate_stats
        return await reconcile_debate_stats(self.bot)

    async def _run_unnumbered_check(self) -> dict:
        """Check for and number any unnumbered threads."""
        from src.services.debates.numbering_scheduler import check_unnumbered_threads
        stats = await check_unnumbered_threads(self.bot)
        # Only return stats if we actually numbered something (skip logging for no-op)
        if stats.get("threads_numbered", 0) == 0:
            return {}
        return stats

    # -------------------------------------------------------------------------
    # Webhook Alerts
    # -------------------------------------------------------------------------

    async def _send_error_webhook(self, error_type: str, error_msg: str) -> None:
        """Send error alert to webhook if available."""
        try:
            if hasattr(self.bot, 'webhook_alerts') and self.bot.webhook_alerts:
                await self.bot.webhook_alerts.send_error_alert(error_type, error_msg)
        except Exception:
            pass


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DebateMaintenanceScheduler",
    "DAILY_SCHEDULE",
    "HOURLY_SCHEDULE",
]
