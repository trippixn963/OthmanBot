"""
Othman Discord Bot - Soccer Scheduler Service
=============================================

Manages automated 3-hour soccer news posting with state persistence.

Features:
- 3-hour scheduling intervals
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


class SoccerScheduler:
    """Manages automated 3-hour soccer news posting schedule."""

    def __init__(self, post_callback: Callable[[], Any]) -> None:
        """
        Initialize the soccer scheduler.

        Args:
            post_callback: Async function to call when posting soccer news
        """
        self.post_callback: Callable[[], Any] = post_callback
        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.state_file: Path = Path("data/soccer_scheduler_state.json")
        self.state_file.parent.mkdir(exist_ok=True)

        # DESIGN: 1-hour interval for soccer news (24 posts per day)
        # Same frequency as regular news to keep sports channel active
        # Users want consistent hourly updates for sports content
        self.interval_hours: int = 1

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
                        f"⚽ Loaded soccer scheduler state: {'RUNNING' if self.is_running else 'STOPPED'}"
                    )
        except Exception as e:
            logger.warning(f"Failed to load soccer scheduler state: {e}")
            self.is_running = False

    def _save_state(self) -> None:
        """Save scheduler state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump({"is_running": self.is_running}, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save soccer scheduler state: {e}")

    async def start(self, post_immediately: bool = False) -> bool:
        """
        Start the automated soccer news posting schedule.

        Args:
            post_immediately: If True, post soccer news immediately then start hourly schedule

        Returns:
            True if started successfully, False if already running
        """
        # DESIGN: Post immediately if requested, even if scheduler is already running
        # This allows testing the bot without restarting from scratch
        if post_immediately:
            logger.info("⚽ Posting soccer news immediately (test mode)")
            await self.post_callback()

        # DESIGN: Check if background task is already running (not just state flag)
        # State file may say "running" but task could have crashed
        # Always create new task if none exists or previous task is done
        if self.task and not self.task.done():
            logger.warning("Soccer scheduler task is already running")
            return False

        self.is_running = True
        self._save_state()

        # DESIGN: Create background task for hourly interval posting
        # Task runs indefinitely until stopped
        # Separate task prevents blocking main bot operations
        self.task = asyncio.create_task(self._schedule_loop())

        next_post: datetime = self._calculate_next_post_time()
        logger.success(
            f"⚽ Soccer scheduler started - Next post at {next_post.strftime('%I:%M %p %Z')}"
        )
        return True

    async def stop(self) -> bool:
        """
        Stop the automated soccer news posting schedule.

        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running:
            logger.warning("Soccer scheduler is not running")
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

        logger.success("⚽ Soccer scheduler stopped")
        return True

    async def _schedule_loop(self) -> None:
        """
        Main scheduling loop - runs every hour.

        DESIGN: Posts soccer news every hour (24 times per day)
        Calculates wait time dynamically to maintain consistent intervals
        Handles errors gracefully to keep scheduler running
        """
        while self.is_running:
            try:
                # DESIGN: Calculate exact wait time until next hour mark
                # Ensures posts happen consistently every hour
                # Example: Current time 2:15 PM → wait 45 minutes → post at 3:00 PM
                next_post_time: datetime = self._calculate_next_post_time()
                wait_seconds: float = (next_post_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.info(
                        f"⚽ Next soccer post scheduled for {next_post_time.strftime('%I:%M %p %Z')} "
                        f"(in {wait_seconds / 60:.1f} minutes)"
                    )
                    await asyncio.sleep(wait_seconds)

                # DESIGN: Post soccer news if still running after wait
                # Check is_running again in case stop() was called during sleep
                if self.is_running:
                    logger.info("⚽⏰ Hourly soccer post triggered")
                    try:
                        await self.post_callback()
                    except Exception as e:
                        logger.error(f"Failed to post soccer news: {e}")
                        # DESIGN: Continue scheduling even if one post fails
                        # One failure shouldn't stop all future posts

            except asyncio.CancelledError:
                logger.info("Soccer scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Soccer scheduler loop error: {e}")
                # DESIGN: Wait 15 minutes before retry on error
                # Prevents rapid error loops while allowing recovery
                await asyncio.sleep(900)

    def _calculate_next_post_time(self) -> datetime:
        """
        Calculate the next hourly post time.

        Returns:
            datetime object for next post time

        DESIGN: Posts every hour on the hour mark (1:00, 2:00, 3:00, etc.)
        Same as news scheduler to maintain consistency
        """
        now: datetime = datetime.now()

        # DESIGN: Calculate next hour boundary
        # Always post at the top of each hour (minute=0, second=0)
        if now.minute == 0 and now.second == 0:
            # If exactly on the hour, wait for next hour
            next_post: datetime = now + timedelta(hours=1)
        else:
            # Otherwise, go to next hour boundary
            next_post: datetime = (now + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )

        return next_post

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
            "interval_hours": self.interval_hours,
        }
