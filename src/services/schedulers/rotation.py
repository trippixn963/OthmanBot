"""
OthmanBot - Content Rotation Scheduler
================================================

Unified scheduler that rotates between news and soccer content hourly.

Features:
- Hourly content rotation (News → Soccer → repeat)
- Skips content types with no new unposted articles
- Saves OpenAI API tokens by posting only 1 content type per hour
- State persistence across restarts

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable, Any
from enum import Enum

from src.core.logger import logger
from src.core.config import SCHEDULER_ERROR_RETRY, BOT_DISABLED_CHECK_INTERVAL, NY_TZ
from src.services.database import get_db


# =============================================================================
# Content Types
# =============================================================================

class ContentType(Enum):
    """Enum for content types in rotation."""
    NEWS = "news"
    SOCCER = "soccer"


# =============================================================================
# Content Rotation Scheduler
# =============================================================================

class ContentRotationScheduler:
    """
    Unified scheduler that rotates between news and soccer content.

    Posts one content type per hour in rotation: News → Soccer → repeat.
    If a content type has no new unposted content, it skips to the next type.

    This reduces OpenAI API token usage by posting less frequently while still
    ensuring all content types are covered.
    """

    def __init__(
        self,
        news_callback: Callable[[], Any],
        soccer_callback: Callable[[], Any],
        news_scraper: Any,
        soccer_scraper: Any,
        bot: Any = None,
    ) -> None:
        """
        Initialize the content rotation scheduler.

        Args:
            news_callback: Async function to call when posting news
            soccer_callback: Async function to call when posting soccer
            news_scraper: News scraper instance (to check for new content)
            soccer_scraper: Soccer scraper instance (to check for new content)
            bot: Bot instance (to check disabled state)
        """
        self.bot = bot
        self.callbacks = {
            ContentType.NEWS: news_callback,
            ContentType.SOCCER: soccer_callback,
        }

        self.scrapers = {
            ContentType.NEWS: news_scraper,
            ContentType.SOCCER: soccer_scraper,
        }

        self.emojis = {
            ContentType.NEWS: "📰",
            ContentType.SOCCER: "⚽",
        }

        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self._db = get_db()

        # Load saved state or start with news
        self._load_state()

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load scheduler state from database."""
        try:
            state = self._db.get_scheduler_state("content_rotation")

            if state:
                self.is_running = state.get("is_running", False)

                # Load next content type from extra_data (default to news if invalid)
                extra_data = state.get("extra_data") or {}
                next_type_str = extra_data.get("next_content_type", "news")
                try:
                    self.next_content_type = ContentType(next_type_str)
                except ValueError:
                    self.next_content_type = ContentType.NEWS

                logger.info("🔄 Loaded Content Rotation State", [
                    ("Status", "RUNNING" if self.is_running else "STOPPED"),
                    ("Next Type", self.next_content_type.value),
                ])
            else:
                # Default: start with news
                self.next_content_type = ContentType.NEWS
                logger.info("🔄 Starting Fresh Content Rotation", [
                    ("Starting With", "news"),
                ])
        except Exception as e:
            logger.warning("🔄 Failed to Load Content Rotation State", [
                ("Error", str(e)),
            ])
            self.is_running = False
            self.next_content_type = ContentType.NEWS

    def _save_state(self) -> None:
        """Save scheduler state to database."""
        try:
            self._db.set_scheduler_state(
                scheduler_name="content_rotation",
                is_running=self.is_running,
                extra_data={"next_content_type": self.next_content_type.value}
            )
        except Exception as e:
            logger.warning("🔄 Failed to Save Content Rotation State", [
                ("Error", str(e)),
            ])

    # -------------------------------------------------------------------------
    # Task Exception Handling
    # -------------------------------------------------------------------------

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle exceptions from the scheduler task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.tree("Rotation Scheduler Task Exception", [
                ("Error Type", type(exc).__name__),
                ("Error", str(exc)[:100]),
            ], emoji="❌")

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
            logger.info("🔄 Test Mode Triggered", [
                ("Action", "Posting content immediately"),
            ])
            await self._post_next_content()

        if self.task and not self.task.done():
            logger.warning("🔄 Scheduler Already Running", [
                ("Action", "Skipping start"),
            ])
            return False

        self.is_running = True
        self._save_state()

        self.task = asyncio.create_task(self._schedule_loop())
        self.task.add_done_callback(self._handle_task_exception)

        next_post: datetime = self._calculate_next_post_time()
        logger.success("🔄 Content Rotation Scheduler Started", [
            ("Next Post", next_post.strftime('%I:%M %p')),
            ("Content Type", self.next_content_type.value),
        ])
        return True

    async def stop(self) -> bool:
        """
        Stop the automated posting schedule.

        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running:
            logger.warning("🔄 Scheduler Not Running", [
                ("Action", "Cannot stop"),
            ])
            return False

        self.is_running = False
        self._save_state()

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.success("🔄 Content Rotation Scheduler Stopped", [
            ("Status", "Task cancelled"),
        ])
        return True

    # -------------------------------------------------------------------------
    # Scheduling Loop
    # -------------------------------------------------------------------------

    async def _schedule_loop(self) -> None:
        """
        Main scheduling loop - posts one content type per hour in rotation.

        DESIGN: Rotates through news → soccer hourly
        Skips content types with no new unposted articles
        Falls back to news if all content types are exhausted
        """
        while self.is_running:
            try:
                # Check if bot is disabled
                if self.bot and getattr(self.bot, 'disabled', False):
                    await asyncio.sleep(BOT_DISABLED_CHECK_INTERVAL)
                    continue

                next_post_time: datetime = self._calculate_next_post_time()
                wait_seconds: float = (next_post_time - datetime.now(NY_TZ)).total_seconds()

                if wait_seconds > 0:
                    emoji = self.emojis[self.next_content_type]
                    logger.tree("Next Content Rotation Scheduled", [
                        ("Content Type", self.next_content_type.value),
                        ("Time", next_post_time.strftime('%I:%M %p')),
                        ("In", f"{wait_seconds / 60:.1f} minutes"),
                    ], emoji=emoji)
                    await asyncio.sleep(wait_seconds)

                # Check again after sleep in case bot was disabled while waiting
                if self.bot and getattr(self.bot, 'disabled', False):
                    continue

                if self.is_running:
                    await self._post_next_content()

            except asyncio.CancelledError:
                logger.info("🔄 Scheduler Loop Cancelled", [
                    ("Type", "Content Rotation"),
                ])
                break
            except Exception as e:
                logger.error("🔄 Scheduler Loop Error", [
                    ("Type", "Content Rotation"),
                    ("Error", str(e)),
                    ("Retry In", "5 minutes"),
                ])
                await asyncio.sleep(SCHEDULER_ERROR_RETRY)

    async def _post_next_content(self) -> None:
        """
        Post the next content type in rotation.

        Tries to post current content type. If no new content is available,
        tries the next type in rotation. If all types are exhausted, goes
        back to news.
        """
        attempts = 0
        max_attempts = 2  # Try both content types

        while attempts < max_attempts:
            content_type = self.next_content_type
            emoji = self.emojis[content_type]
            callback = self.callbacks[content_type]
            scraper = self.scrapers[content_type]

            logger.tree("Hourly Content Rotation Triggered", [
                ("Content Type", content_type.value),
            ], emoji=emoji)

            # Check if this content type has new unposted articles
            if scraper and await self._has_new_content(content_type, scraper):
                # Post this content type
                try:
                    await callback()
                    logger.tree("Content Posted Successfully", [
                        ("Content Type", content_type.value),
                    ], emoji="✅")

                    # Move to next content type in rotation for next hour
                    self._rotate_to_next_type()
                    self._save_state()
                    return

                except Exception as e:
                    logger.tree("Failed to Post Content", [
                        ("Content Type", content_type.value),
                        ("Error", str(e)),
                    ], emoji="❌")
                    # Still rotate even if posting failed
                    self._rotate_to_next_type()
                    self._save_state()
                    return
            else:
                # No new content for this type, try next type
                logger.tree("No New Content Available", [
                    ("Content Type", content_type.value),
                    ("Action", "Skipping to next type"),
                ], emoji=emoji)
                self._rotate_to_next_type()
                attempts += 1

        # All content types exhausted - log and wait for next hour
        logger.warning("🔄 No Content Available", [
            ("Sources Checked", "All (news, soccer)"),
            ("Action", "Skipping this hour"),
        ])

    async def _has_new_content(self, content_type: ContentType, scraper: Any) -> bool:
        """
        Check if a content type has new unposted articles.

        Args:
            content_type: The content type to check
            scraper: The scraper instance for this content type

        Returns:
            True if there are new unposted articles, False otherwise
        """
        try:
            # Fetch articles using the appropriate method for each scraper type
            if content_type == ContentType.NEWS:
                articles = await scraper.fetch_latest_news(max_articles=1, hours_back=24)
            else:  # SOCCER
                articles = await scraper.fetch_latest_soccer_news(max_articles=1, hours_back=24)

            # If we got articles, there's new content
            # The scrapers already filter out posted content
            return bool(articles)

        except Exception as e:
            logger.error("🔄 Content Check Error", [
                ("Content Type", content_type.value),
                ("Error", str(e)),
            ])
            return False

    def _rotate_to_next_type(self) -> None:
        """Move to the next content type in rotation."""
        if self.next_content_type == ContentType.NEWS:
            self.next_content_type = ContentType.SOCCER
        else:  # SOCCER
            self.next_content_type = ContentType.NEWS

    def _calculate_next_post_time(self) -> datetime:
        """
        Calculate the next hourly post time (on the hour).

        Returns:
            datetime object for next post time
        """
        now: datetime = datetime.now(NY_TZ)

        # Always schedule for the next hour to prevent double-posting
        # when a post completes within the same minute it was scheduled
        next_post: datetime = (now + timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0
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
            "next_content_type": self.next_content_type.value,
            "next_post_time": (
                next_post.strftime("%I:%M %p") if next_post else "N/A"
            ),
            "next_post_in_minutes": (
                int((next_post - datetime.now(NY_TZ)).total_seconds() / 60)
                if next_post
                else None
            ),
        }


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ContentRotationScheduler", "ContentType"]
