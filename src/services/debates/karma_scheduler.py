"""
OthmanBot - Karma Reconciliation Scheduler
====================================================

Nightly scheduled karma reconciliation at 00:00 EST (midnight).
Performs a full scan of ALL threads for 100% karma accuracy.
Also runs orphan vote cleanup to remove votes from deleted messages.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Callable, Awaitable, Optional, Any

from src.core.logger import logger
from src.core.config import SECONDS_PER_HOUR, NY_TZ
from src.services.debates.reconciliation import cleanup_orphan_votes
from src.utils.footer import refresh_avatar
from src.utils.banner import refresh_banner

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Karma Reconciliation Scheduler
# =============================================================================

class KarmaReconciliationScheduler:
    """
    Scheduler for nightly karma reconciliation.

    Runs at 00:00 EST (midnight) every night to ensure karma is accurate.
    Performs a full scan of ALL threads (not limited by days).
    """

    def __init__(
        self,
        callback: Callable[[], Awaitable[dict]],
        bot: Optional["OthmanBot"] = None
    ) -> None:
        """
        Initialize scheduler.

        Args:
            callback: Async function to call for reconciliation (returns stats dict)
            bot: Optional bot reference for webhook alerts on errors
        """
        self.callback = callback
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._running = False

        # Schedule time: 00:00 EST (midnight)
        self.schedule_hour = 0
        self.schedule_minute = 0

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Karma reconciliation scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("🔄 Karma Reconciliation Scheduler Started", [
            ("Schedule", "nightly at 00:00 EST (full scan)"),
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
                    logger.info("🔄 Starting nightly karma reconciliation (full scan)...")
                    try:
                        stats = await self.callback()
                        logger.success("✅ Nightly Karma Reconciliation Complete", [
                            ("Threads", str(stats.get('threads_scanned', 0))),
                            ("Messages", str(stats.get('messages_scanned', 0))),
                            ("Added", f"+{stats.get('votes_added', 0)}"),
                            ("Removed", f"-{stats.get('votes_removed', 0)}"),
                        ])
                        # Log success to webhook
                        await self._send_reconciliation_webhook("Nightly (00:00 EST)", stats, success=True)

                        # Run orphan vote cleanup after karma reconciliation
                        if self.bot:
                            await self._run_orphan_cleanup()

                        # Refresh footer avatar and bot banner at midnight
                        await refresh_avatar()
                        await refresh_banner()

                    except Exception as e:
                        logger.error("Nightly Karma Reconciliation Failed", [
                            ("Error Type", type(e).__name__),
                            ("Error", str(e)),
                        ])
                        # Send to webhook for reconciliation errors
                        await self._send_error_webhook("Karma Reconciliation Failed", str(e))
                        await self._send_reconciliation_webhook("Nightly (00:00 EST)", {"error": str(e)}, success=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error In Karma Reconciliation Scheduler", [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)),
                ])
                # Send to webhook for scheduler errors
                await self._send_error_webhook("Karma Scheduler Error", str(e))
                # Wait 1 hour before retrying on error
                await asyncio.sleep(SECONDS_PER_HOUR)

    async def _send_error_webhook(self, error_type: str, error_msg: str) -> None:
        """Send error to webhook if bot is available."""
        try:
            if self.bot and hasattr(self.bot, 'webhook_alerts') and self.bot.webhook_alerts:
                await self.bot.webhook_alerts.send_error_alert(error_type, error_msg)
        except Exception:
            pass  # Don't fail on webhook error

    async def _send_reconciliation_webhook(self, trigger: str, stats: dict, success: bool) -> None:
        """Send reconciliation results to webhook if bot is available."""
        # Logging now handled by tree logger automatically
        pass

    async def _run_orphan_cleanup(self) -> None:
        """Run orphan vote cleanup and log results."""
        try:
            logger.info("🧹 Starting orphan vote cleanup...")
            orphan_stats = await cleanup_orphan_votes(self.bot)

            if orphan_stats.get("orphans_found", 0) > 0:
                logger.success("🧹 Orphan Vote Cleanup Complete", [
                    ("Orphans Found", str(orphan_stats.get("orphans_found", 0))),
                    ("Votes Cleaned", str(orphan_stats.get("votes_cleaned", 0))),
                    ("Karma Reversed", str(orphan_stats.get("karma_reversed", 0))),
                ])
            else:
                logger.info("🧹 Orphan Vote Cleanup Complete - No Orphans Found")

            # Send to webhook
            await self._send_orphan_cleanup_webhook(orphan_stats)

        except Exception as e:
            logger.error("Orphan Vote Cleanup Failed", [
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])
            await self._send_error_webhook("Orphan Vote Cleanup Failed", str(e))

    async def _send_orphan_cleanup_webhook(self, stats: dict) -> None:
        """Send orphan cleanup results to webhook if bot is available."""
        # Logging now handled by tree logger automatically
        pass


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["KarmaReconciliationScheduler"]
