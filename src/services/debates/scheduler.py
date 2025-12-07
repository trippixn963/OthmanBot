"""
Othman Discord Bot - Debates Scheduler
=======================================

Scheduler for posting hot debates every 3 hours.

Posts at: 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 EST

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Any

from src.core.logger import logger
from src.core.config import SCHEDULER_ERROR_RETRY


# =============================================================================
# Debates Scheduler Class
# =============================================================================

class DebatesScheduler:
    """Scheduler for automated hot debate posting every 3 hours."""

    def __init__(
        self,
        post_callback: Callable[[], Any],
        state_filename: str = "debates_scheduler_state.json",
    ) -> None:
        """
        Initialize the debates scheduler.

        Args:
            post_callback: Async function to call when posting
            state_filename: JSON file for state persistence
        """
        self.post_callback: Callable[[], Any] = post_callback
        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.state_file: Path = Path(f"data/{state_filename}")
        self.state_file.parent.mkdir(exist_ok=True)

        # Posts every 3 hours at these hours (EST)
        self.post_hours: list[int] = [0, 3, 6, 9, 12, 15, 18, 21]

        self._load_state()

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load scheduler state from file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    data: dict[str, Any] = json.load(f)
                    self.is_running = data.get("is_running", False)
                    logger.info("🔥 Loaded Debates Scheduler State", [
                        ("Status", "RUNNING" if self.is_running else "STOPPED"),
                    ])
        except Exception as e:
            logger.warning("Failed To Load Debates Scheduler State", [
                ("Error", str(e)),
            ])
            self.is_running = False

    def _save_state(self) -> None:
        """Save scheduler state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump({"is_running": self.is_running}, f, indent=2)
        except Exception as e:
            logger.warning("Failed To Save Debates Scheduler State", [
                ("Error", str(e)),
            ])

    # -------------------------------------------------------------------------
    # Start/Stop Controls
    # -------------------------------------------------------------------------

    async def start(self, post_immediately: bool = False) -> bool:
        """
        Start the automated posting schedule.

        Args:
            post_immediately: If True, post immediately then start 3-hour schedule

        Returns:
            True if started successfully, False if already running
        """
        if post_immediately:
            logger.info("🔥 Posting hot debate immediately (test mode)")
            await self.post_callback()

        if self.task and not self.task.done():
            logger.warning("Debates scheduler task is already running")
            return False

        self.is_running = True
        self._save_state()

        self.task = asyncio.create_task(self._schedule_loop())

        next_post: datetime = self._calculate_next_post_time()
        logger.success(
            f"🔥 Debates scheduler started - "
            f"Next post at {next_post.strftime('%I:%M %p')}"
        )
        return True

    async def stop(self) -> bool:
        """
        Stop the automated posting schedule.

        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running:
            logger.warning("Debates scheduler is not running")
            return False

        self.is_running = False
        self._save_state()

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.success("🔥 Debates scheduler stopped")
        return True

    # -------------------------------------------------------------------------
    # Scheduling Loop
    # -------------------------------------------------------------------------

    async def _schedule_loop(self) -> None:
        """
        Main scheduling loop - runs every 3 hours at configured times.

        DESIGN: Posts hot debate every 3 hours at specific times
        Calculates wait time dynamically to maintain consistent intervals
        Handles errors gracefully to keep scheduler running
        """
        while self.is_running:
            try:
                next_post_time: datetime = self._calculate_next_post_time()
                wait_seconds: float = (next_post_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.info("🔥 Next Hot Debate Post Scheduled", [
                        ("Time", next_post_time.strftime('%I:%M %p')),
                        ("Wait", f"{wait_seconds / 60:.1f} minutes"),
                    ])
                    await asyncio.sleep(wait_seconds)

                if self.is_running:
                    logger.info("🔥⏰ 3-Hourly Hot Debate Post Triggered")
                    try:
                        await self.post_callback()
                    except Exception as e:
                        logger.error("Failed To Post Hot Debate", [
                            ("Error", str(e)),
                        ])

            except asyncio.CancelledError:
                logger.info("Debates scheduler loop cancelled")
                break
            except Exception as e:
                logger.error("Debates Scheduler Loop Error", [
                    ("Error", str(e)),
                ])
                await asyncio.sleep(SCHEDULER_ERROR_RETRY)

    def _calculate_next_post_time(self) -> datetime:
        """
        Calculate the next post time (every 3 hours).

        Returns:
            datetime object for next post time

        DESIGN: Posts at 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00
        Finds the next scheduled hour from current time
        """
        now: datetime = datetime.now()
        current_hour: int = now.hour

        # Find next post hour
        next_hour: Optional[int] = None
        for hour in self.post_hours:
            if hour > current_hour:
                next_hour = hour
                break

        # If no hour found today, use first hour tomorrow
        if next_hour is None:
            next_post: datetime = (now + timedelta(days=1)).replace(
                hour=self.post_hours[0], minute=0, second=0, microsecond=0
            )
        else:
            next_post: datetime = now.replace(
                hour=next_hour, minute=0, second=0, microsecond=0
            )

        return next_post

    # -------------------------------------------------------------------------
    # Status Methods
    # -------------------------------------------------------------------------

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
                next_post.strftime("%I:%M %p") if next_post else "N/A"
            ),
            "next_post_in_minutes": (
                int((next_post - datetime.now()).total_seconds() / 60)
                if next_post
                else None
            ),
        }


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DebatesScheduler"]
