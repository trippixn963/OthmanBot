"""
Othman Discord Bot - Gaming Scheduler Service
==============================================

Manages automated hourly gaming news posting with state persistence.

Features:
- Hourly scheduling at :40 past each hour
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


class GamingScheduler:
    """Manages automated hourly gaming news posting schedule."""

    def __init__(self, post_callback: Callable[[], Any]) -> None:
        """
        Initialize the gaming scheduler.

        Args:
            post_callback: Async function to call when posting gaming news
        """
        self.post_callback: Callable[[], Any] = post_callback
        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.state_file: Path = Path("data/gaming_scheduler_state.json")
        self.state_file.parent.mkdir(exist_ok=True)

        # DESIGN: 1-hour interval for gaming news (24 posts per day)
        # Same frequency as news and soccer for consistent content flow
        # Posts at :40 past each hour to complete 3-way stagger
        self.interval_hours: int = 1

        # DESIGN: Load saved state to resume after restarts
        self._load_state()

    def _load_state(self) -> None:
        """Load scheduler state from file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    data: dict[str, Any] = json.load(f)
                    self.is_running = data.get("is_running", False)
                    logger.info(
                        f"🎮 Loaded gaming scheduler state: {'RUNNING' if self.is_running else 'STOPPED'}"
                    )
        except Exception as e:
            logger.warning(f"Failed to load gaming scheduler state: {e}")
            self.is_running = False

    def _save_state(self) -> None:
        """Save scheduler state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump({"is_running": self.is_running}, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save gaming scheduler state: {e}")

    async def start(self, post_immediately: bool = False) -> bool:
        """
        Start the automated gaming news posting schedule.

        Args:
            post_immediately: If True, post gaming news immediately then start hourly schedule

        Returns:
            True if started successfully, False if already running
        """
        # DESIGN: Post immediately if requested
        if post_immediately:
            logger.info("🎮 Posting gaming news immediately (test mode)")
            await self.post_callback()

        # DESIGN: Check if background task is already running
        if self.task and not self.task.done():
            logger.warning("Gaming scheduler task is already running")
            return False

        self.is_running = True
        self._save_state()

        # DESIGN: Create background task for hourly posting at :40
        self.task = asyncio.create_task(self._schedule_loop())

        next_post: datetime = self._calculate_next_post_time()
        logger.success(
            f"🎮 Gaming scheduler started - Next post at {next_post.strftime('%I:%M %p %Z')}"
        )
        return True

    async def stop(self) -> bool:
        """
        Stop the automated gaming news posting schedule.

        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running:
            logger.warning("Gaming scheduler is not running")
            return False

        self.is_running = False
        self._save_state()

        # DESIGN: Cancel background task gracefully
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.success("🎮 Gaming scheduler stopped")
        return True

    async def _schedule_loop(self) -> None:
        """
        Main scheduling loop - runs every hour at :40.

        DESIGN: Posts gaming news every hour at :40 (12:40, 1:40, 2:40, etc.)
        Completes the 3-way stagger: News at :00, Soccer at :20, Gaming at :40
        """
        while self.is_running:
            try:
                # DESIGN: Calculate exact wait time until next :40 mark
                next_post_time: datetime = self._calculate_next_post_time()
                wait_seconds: float = (next_post_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.info(
                        f"🎮 Next gaming post scheduled for {next_post_time.strftime('%I:%M %p %Z')} "
                        f"(in {wait_seconds / 60:.1f} minutes)"
                    )
                    await asyncio.sleep(wait_seconds)

                # DESIGN: Post gaming news if still running after wait
                if self.is_running:
                    logger.info("🎮⏰ Hourly gaming post triggered")
                    try:
                        await self.post_callback()
                    except Exception as e:
                        logger.error(f"Failed to post gaming news: {e}")
                        # DESIGN: Continue scheduling even if one post fails

            except asyncio.CancelledError:
                logger.info("Gaming scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Gaming scheduler loop error: {e}")
                # DESIGN: Wait 15 minutes before retry on error
                await asyncio.sleep(900)

    def _calculate_next_post_time(self) -> datetime:
        """
        Calculate the next hourly post time at :40 past each hour.

        Returns:
            datetime object for next post time

        DESIGN: Posts every hour at 40 minutes past (12:40, 1:40, 2:40, etc.)
        Staggered schedule: News at :00, Soccer at :20, Gaming at :40
        """
        now: datetime = datetime.now()

        # DESIGN: Calculate next :40 boundary each hour
        # This staggers gaming posts 40 minutes after news, 20 minutes after soccer
        if now.minute < 40:
            # Before :40, post at current hour :40
            next_post: datetime = now.replace(minute=40, second=0, microsecond=0)
        else:
            # After :40, post at next hour :40
            next_post: datetime = (now + timedelta(hours=1)).replace(
                minute=40, second=0, microsecond=0
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
