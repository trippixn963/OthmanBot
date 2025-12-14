"""
Othman Discord Bot - Karma Reconciliation Scheduler
====================================================

Nightly scheduled karma reconciliation at 00:30 NY_TZ.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Callable, Awaitable

from src.core.logger import logger
from src.core.config import SECONDS_PER_HOUR, NY_TZ

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Karma Reconciliation Scheduler
# =============================================================================

class KarmaReconciliationScheduler:
    """
    Scheduler for nightly karma reconciliation.

    Runs at 00:30 NY_TZ every night to ensure karma is accurate.
    """

    def __init__(self, callback: Callable[[], Awaitable[dict]]) -> None:
        """
        Initialize scheduler.

        Args:
            callback: Async function to call for reconciliation (returns stats dict)
        """
        self.callback = callback
        self._task: asyncio.Task | None = None
        self._running = False

        # Schedule time: 00:30 NY_TZ
        self.schedule_hour = 0
        self.schedule_minute = 30

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Karma reconciliation scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("🔄 Karma Reconciliation Scheduler Started", [
            ("Schedule", "nightly at 00:30 NY_TZ"),
        ])

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("🛑 Karma reconciliation scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                # Calculate time until next 00:30 NY_TZ
                now = datetime.now(NY_TZ)
                target_time = now.replace(
                    hour=self.schedule_hour,
                    minute=self.schedule_minute,
                    second=0,
                    microsecond=0
                )

                # If we've already passed today's target time, schedule for tomorrow
                if now >= target_time:
                    target_time += timedelta(days=1)

                wait_seconds = (target_time - now).total_seconds()

                logger.info("🔄 Next Karma Reconciliation Scheduled", [
                    ("Time", target_time.strftime('%Y-%m-%d %H:%M %Z')),
                    ("Wait", f"{wait_seconds / 3600:.1f} hours"),
                ])

                # Wait until target time
                await asyncio.sleep(wait_seconds)

                # Run reconciliation
                if self._running:
                    logger.info("🔄 Starting nightly karma reconciliation...")
                    try:
                        stats = await self.callback()
                        logger.success("✅ Nightly Karma Reconciliation Complete", [
                            ("Added", f"+{stats.get('votes_added', 0)}"),
                            ("Removed", f"-{stats.get('votes_removed', 0)}"),
                        ])
                    except Exception as e:
                        logger.error("Nightly Karma Reconciliation Failed", [
                            ("Error Type", type(e).__name__),
                            ("Error", str(e)),
                        ])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error In Karma Reconciliation Scheduler", [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)),
                ])
                # Wait 1 hour before retrying on error
                await asyncio.sleep(SECONDS_PER_HOUR)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["KarmaReconciliationScheduler"]
