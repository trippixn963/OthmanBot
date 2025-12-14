"""
Othman Discord Bot - Case Archive Scheduler
============================================

Background task that archives inactive case threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from discord.ext import tasks

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Case Archive Scheduler
# =============================================================================

class CaseArchiveScheduler:
    """
    Scheduler that periodically archives inactive case threads.

    DESIGN:
    - Runs every 24 hours (once daily)
    - Archives case threads inactive for 7+ days
    - Keeps forum clean while preserving case history
    """

    # Archive threads inactive for this many days
    DAYS_INACTIVE = 7

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the case archive scheduler.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot

    async def start(self) -> None:
        """Start the scheduler."""
        if not self._archive_inactive_cases.is_running():
            self._archive_inactive_cases.start()
            logger.info("Case Archive Scheduler Started", [
                ("Interval", "24 hours"),
                ("Inactivity Threshold", f"{self.DAYS_INACTIVE} days"),
            ])

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self._archive_inactive_cases.is_running():
            self._archive_inactive_cases.cancel()
            logger.info("Case Archive Scheduler Stopped")

    @tasks.loop(hours=24)
    async def _archive_inactive_cases(self) -> None:
        """Archive inactive case threads."""
        try:
            if not hasattr(self.bot, 'case_log_service') or not self.bot.case_log_service:
                return

            if not self.bot.case_log_service.enabled:
                return

            logger.info("Case Archive: Starting Daily Archive Check")

            archived_count = await self.bot.case_log_service.archive_inactive_cases(
                days_inactive=self.DAYS_INACTIVE
            )

            if archived_count > 0:
                logger.tree("Case Archive: Daily Archive Complete", [
                    ("Threads Archived", str(archived_count)),
                    ("Inactivity Threshold", f"{self.DAYS_INACTIVE} days"),
                ], emoji="📦")
            else:
                logger.info("Case Archive: No Inactive Threads To Archive")

        except Exception as e:
            logger.error("Error In Case Archive Check", [
                ("Error", str(e)),
            ])

    @_archive_inactive_cases.before_loop
    async def _before_archive(self) -> None:
        """Wait until the bot is ready before starting."""
        await self.bot.wait_until_ready()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseArchiveScheduler"]
