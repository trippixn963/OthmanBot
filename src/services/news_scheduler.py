"""
Othman Discord Bot - News Scheduler Service
===========================================

Manages automated hourly news posting with state persistence.

Features:
- Hourly scheduling on the hour
- Background async task
- Start/stop controls
- State persistence across restarts
- Next post time tracking

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Any

from src.core.logger import logger


class NewsScheduler:
    """Manages automated hourly news posting schedule."""

    def __init__(self, post_callback: Callable[[], Any]) -> None:
        """
        Initialize the news scheduler.

        Args:
            post_callback: Async function to call when posting news
        """
        self.post_callback: Callable[[], Any] = post_callback
        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.state_file: Path = Path("data/scheduler_state.json")
        self.state_file.parent.mkdir(exist_ok=True)

        # DESIGN: Load saved state to resume after restarts
        # Tracks whether scheduler was running before shutdown
        self._load_state()

    def _load_state(self) -> None:
        """Load scheduler state from file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    data: dict[str, Any] = json.load(f)
                    self.is_running = data.get("is_running", False)
                    logger.info(
                        f"Loaded scheduler state: {'RUNNING' if self.is_running else 'STOPPED'}"
                    )
        except Exception as e:
            logger.warning(f"Failed to load scheduler state: {e}")
            self.is_running = False

    def _save_state(self) -> None:
        """Save scheduler state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump({"is_running": self.is_running}, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save scheduler state: {e}")

    async def start(self, post_immediately: bool = False) -> bool:
        """
        Start the automated news posting schedule.

        Args:
            post_immediately: If True, post news immediately then start hourly schedule

        Returns:
            True if started successfully, False if already running
        """
        if self.is_running:
            logger.warning("Scheduler is already running")
            return False

        self.is_running = True
        self._save_state()

        # DESIGN: Optional immediate post for testing or first run
        # Useful when you want to see results immediately
        if post_immediately:
            logger.info("🚀 Posting news immediately (test mode)")
            await self.post_callback()

        # DESIGN: Create background task for hourly posting
        # Task runs indefinitely until stopped
        # Separate task prevents blocking main bot operations
        self.task = asyncio.create_task(self._schedule_loop())

        next_post: datetime = self._calculate_next_post_time()
        logger.success(
            f"News scheduler started - Next post at {next_post.strftime('%I:%M %p %Z')}"
        )
        return True

    async def stop(self) -> bool:
        """
        Stop the automated news posting schedule.

        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running:
            logger.warning("Scheduler is not running")
            return False

        self.is_running = False
        self._save_state()

        # DESIGN: Cancel background task gracefully
        # Allow current operation to complete before stopping
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.success("News scheduler stopped")
        return True

    async def _schedule_loop(self) -> None:
        """
        Main scheduling loop - runs hourly on the hour.

        DESIGN: Posts news every hour at :00 minutes
        Calculates wait time dynamically to sync with clock
        Handles errors gracefully to keep scheduler running
        """
        while self.is_running:
            try:
                # DESIGN: Calculate exact wait time until next hour
                # Ensures posts happen consistently at top of each hour
                # Example: Current time 3:45 PM → wait 15 minutes → post at 4:00 PM
                next_post_time: datetime = self._calculate_next_post_time()
                wait_seconds: float = (next_post_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.info(
                        f"Next news post scheduled for {next_post_time.strftime('%I:%M %p %Z')} "
                        f"(in {wait_seconds / 60:.1f} minutes)"
                    )
                    await asyncio.sleep(wait_seconds)

                # DESIGN: Post news if still running after wait
                # Check is_running again in case stop() was called during sleep
                if self.is_running:
                    logger.info("⏰ Hourly news post triggered")
                    try:
                        await self.post_callback()
                    except Exception as e:
                        logger.error(f"Failed to post news: {e}")
                        # DESIGN: Continue scheduling even if one post fails
                        # One failure shouldn't stop all future posts

            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                # DESIGN: Wait 5 minutes before retry on error
                # Prevents rapid error loops while allowing recovery
                await asyncio.sleep(300)

    def _calculate_next_post_time(self) -> datetime:
        """
        Calculate the next hourly post time (top of next hour).

        Returns:
            datetime object for next post time
        """
        # DESIGN: Always post at :00 minutes of the hour
        # If current time is 3:45, next post is 4:00
        # If current time is 3:00, next post is 4:00 (not immediately)
        now: datetime = datetime.now()
        next_hour: datetime = (now + timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0
        )
        return next_hour

    def get_next_post_time(self) -> Optional[datetime]:
        """
        Get the next scheduled post time.

        Returns:
            datetime of next post, or None if scheduler not running
        """
        if not self.is_running:
            return None
        return self._calculate_next_post_time()

    def get_status(self) -> dict[str, Any]:
        """
        Get current scheduler status.

        Returns:
            Dictionary with status information
        """
        next_post: Optional[datetime] = self.get_next_post_time()

        return {
            "is_running": self.is_running,
            "next_post_time": (
                next_post.strftime("%I:%M %p %Z") if next_post else "N/A"
            ),
            "next_post_in_minutes": (
                int((next_post - datetime.now()).total_seconds() / 60)
                if next_post
                else None
            ),
        }
