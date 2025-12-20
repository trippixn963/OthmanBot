"""
Othman Discord Bot - Base Scheduler Service
============================================

Base class for all content schedulers (news, soccer).

Features:
- Hourly scheduling at configurable minute offset
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


# =============================================================================
# Base Scheduler Class
# =============================================================================

class BaseScheduler:
    """Base class for automated content posting schedulers."""

    def __init__(
        self,
        post_callback: Callable[[], Any],
        state_filename: str,
        content_type: str,
        log_emoji: str,
        post_minute: int = 0,
        error_retry_seconds: int = 300,
    ) -> None:
        """
        Initialize the base scheduler.

        Args:
            post_callback: Async function to call when posting
            state_filename: JSON file for state persistence (e.g., "scheduler_state.json")
            content_type: Type of content for logging (e.g., "news", "soccer")
            log_emoji: Emoji for log messages (e.g., "📰", "⚽", "🎮")
            post_minute: Minute of each hour to post (0, 20, 40)
            error_retry_seconds: Seconds to wait before retry on error
        """
        self.post_callback: Callable[[], Any] = post_callback
        self.content_type: str = content_type
        self.log_emoji: str = log_emoji
        self.post_minute: int = post_minute
        self.error_retry_seconds: int = error_retry_seconds

        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.state_file: Path = Path(f"data/{state_filename}")
        self.state_file.parent.mkdir(exist_ok=True)

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
                    logger.tree("Loaded Scheduler State", [
                        ("Type", self.content_type.capitalize()),
                        ("Status", "RUNNING" if self.is_running else "STOPPED"),
                    ], emoji=self.log_emoji)
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.tree("Failed to Load Scheduler State", [
                ("Type", self.content_type.capitalize()),
                ("Error", str(e)),
            ], emoji="⚠️")
            self.is_running = False

    def _save_state(self) -> None:
        """Save scheduler state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump({"is_running": self.is_running}, f, indent=2)
        except (IOError, OSError) as e:
            logger.tree("Failed to Save Scheduler State", [
                ("Type", self.content_type.capitalize()),
                ("Error", str(e)),
            ], emoji="⚠️")

    # -------------------------------------------------------------------------
    # Start/Stop Controls
    # -------------------------------------------------------------------------

    async def start(self, post_immediately: bool = False) -> bool:
        """
        Start the automated posting schedule.

        Args:
            post_immediately: If True, post immediately then start hourly schedule

        Returns:
            True if started successfully, False if already running
        """
        if post_immediately:
            logger.tree("Test Mode Triggered", [
                ("Type", self.content_type.capitalize()),
                ("Action", "Posting immediately"),
            ], emoji=self.log_emoji)
            await self.post_callback()

        if self.task and not self.task.done():
            logger.tree("Scheduler Already Running", [
                ("Type", self.content_type.capitalize()),
            ], emoji="⚠️")
            return False

        self.is_running = True
        self._save_state()

        self.task = asyncio.create_task(self._schedule_loop())

        next_post: datetime = self._calculate_next_post_time()
        logger.tree("Scheduler Started", [
            ("Type", self.content_type.capitalize()),
            ("Next Post", next_post.strftime('%I:%M %p')),
        ], emoji="✅")
        return True

    async def stop(self) -> bool:
        """
        Stop the automated posting schedule.

        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running:
            logger.tree("Scheduler Not Running", [
                ("Type", self.content_type.capitalize()),
            ], emoji="⚠️")
            return False

        self.is_running = False
        self._save_state()

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.tree("Scheduler Stopped", [
            ("Type", self.content_type.capitalize()),
        ], emoji="✅")
        return True

    # -------------------------------------------------------------------------
    # Scheduling Loop
    # -------------------------------------------------------------------------

    async def _schedule_loop(self) -> None:
        """
        Main scheduling loop - runs every hour at configured minute.

        DESIGN: Posts content every hour at the configured minute offset
        Calculates wait time dynamically to maintain consistent intervals
        Handles errors gracefully to keep scheduler running
        """
        while self.is_running:
            try:
                next_post_time: datetime = self._calculate_next_post_time()
                wait_seconds: float = (next_post_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.tree("Next Post Scheduled", [
                        ("Type", self.content_type.capitalize()),
                        ("Time", next_post_time.strftime('%I:%M %p')),
                        ("In", f"{wait_seconds / 60:.1f} minutes"),
                    ], emoji=self.log_emoji)
                    await asyncio.sleep(wait_seconds)

                if self.is_running:
                    logger.tree("Hourly Post Triggered", [
                        ("Type", self.content_type.capitalize()),
                    ], emoji=self.log_emoji)
                    try:
                        await self.post_callback()
                    except Exception as e:
                        logger.tree("Failed to Post", [
                            ("Type", self.content_type.capitalize()),
                            ("Error", str(e)),
                        ], emoji="❌")

            except asyncio.CancelledError:
                logger.tree("Scheduler Loop Cancelled", [
                    ("Type", self.content_type.capitalize()),
                ], emoji=self.log_emoji)
                break
            except Exception as e:
                logger.tree("Scheduler Loop Error", [
                    ("Type", self.content_type.capitalize()),
                    ("Error", str(e)),
                ], emoji="❌")
                await asyncio.sleep(self.error_retry_seconds)

    def _calculate_next_post_time(self) -> datetime:
        """
        Calculate the next hourly post time.

        Returns:
            datetime object for next post time
        """
        now: datetime = datetime.now()

        if now.minute < self.post_minute:
            next_post: datetime = now.replace(
                minute=self.post_minute, second=0, microsecond=0
            )
        else:
            next_post: datetime = (now + timedelta(hours=1)).replace(
                minute=self.post_minute, second=0, microsecond=0
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

__all__ = ["BaseScheduler"]
