"""
Othman Discord Bot - Content Rotation Scheduler
================================================

Unified scheduler that rotates between news, soccer, and gaming content hourly.

Features:
- Hourly content rotation (News → Soccer → Gaming → repeat)
- Skips content types with no new unposted articles
- Saves OpenAI API tokens by posting only 1 content type per hour
- State persistence across restarts

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Any
from enum import Enum

from src.core.logger import logger


# =============================================================================
# Content Types
# =============================================================================

class ContentType(Enum):
    """Enum for content types in rotation."""
    NEWS = "news"
    SOCCER = "soccer"
    GAMING = "gaming"


# =============================================================================
# Content Rotation Scheduler
# =============================================================================

class ContentRotationScheduler:
    """
    Unified scheduler that rotates between news, soccer, and gaming content.

    Posts one content type per hour in rotation: News → Soccer → Gaming → repeat.
    If a content type has no new unposted content, it skips to the next type.

    This reduces OpenAI API token usage by posting less frequently while still
    ensuring all content types are covered.
    """

    def __init__(
        self,
        news_callback: Callable[[], Any],
        soccer_callback: Callable[[], Any],
        gaming_callback: Callable[[], Any],
        news_scraper: Any,
        soccer_scraper: Any,
        gaming_scraper: Any,
    ) -> None:
        """
        Initialize the content rotation scheduler.

        Args:
            news_callback: Async function to call when posting news
            soccer_callback: Async function to call when posting soccer
            gaming_callback: Async function to call when posting gaming
            news_scraper: News scraper instance (to check for new content)
            soccer_scraper: Soccer scraper instance (to check for new content)
            gaming_scraper: Gaming scraper instance (to check for new content)
        """
        self.callbacks = {
            ContentType.NEWS: news_callback,
            ContentType.SOCCER: soccer_callback,
            ContentType.GAMING: gaming_callback,
        }

        self.scrapers = {
            ContentType.NEWS: news_scraper,
            ContentType.SOCCER: soccer_scraper,
            ContentType.GAMING: gaming_scraper,
        }

        self.emojis = {
            ContentType.NEWS: "📰",
            ContentType.SOCCER: "⚽",
            ContentType.GAMING: "🎮",
        }

        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None

        # State persistence
        self.state_file: Path = Path("data/content_rotation_state.json")
        self.state_file.parent.mkdir(exist_ok=True)

        # Load saved state or start with news
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

                    # Load next content type (default to news if invalid)
                    next_type_str = data.get("next_content_type", "news")
                    try:
                        self.next_content_type = ContentType(next_type_str)
                    except ValueError:
                        self.next_content_type = ContentType.NEWS

                    logger.info(
                        f"🔄 Loaded content rotation state: "
                        f"{'RUNNING' if self.is_running else 'STOPPED'}, "
                        f"next={self.next_content_type.value}"
                    )
            else:
                # Default: start with news
                self.next_content_type = ContentType.NEWS
                logger.info("🔄 Starting fresh content rotation (beginning with news)")
        except Exception as e:
            logger.warning(f"Failed to load content rotation state: {e}")
            self.is_running = False
            self.next_content_type = ContentType.NEWS

    def _save_state(self) -> None:
        """Save scheduler state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump({
                    "is_running": self.is_running,
                    "next_content_type": self.next_content_type.value,
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save content rotation state: {e}")

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
            logger.info("🔄 Posting content immediately (test mode)")
            await self._post_next_content()

        if self.task and not self.task.done():
            logger.warning("Content rotation scheduler is already running")
            return False

        self.is_running = True
        self._save_state()

        self.task = asyncio.create_task(self._schedule_loop())

        next_post: datetime = self._calculate_next_post_time()
        logger.success(
            f"🔄 Content rotation scheduler started - "
            f"Next post at {next_post.strftime('%I:%M %p')} ({self.next_content_type.value})"
        )
        return True

    async def stop(self) -> bool:
        """
        Stop the automated posting schedule.

        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running:
            logger.warning("Content rotation scheduler is not running")
            return False

        self.is_running = False
        self._save_state()

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.success("🔄 Content rotation scheduler stopped")
        return True

    # -------------------------------------------------------------------------
    # Scheduling Loop
    # -------------------------------------------------------------------------

    async def _schedule_loop(self) -> None:
        """
        Main scheduling loop - posts one content type per hour in rotation.

        DESIGN: Rotates through news → soccer → gaming hourly
        Skips content types with no new unposted articles
        Falls back to news if all content types are exhausted
        """
        while self.is_running:
            try:
                next_post_time: datetime = self._calculate_next_post_time()
                wait_seconds: float = (next_post_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    emoji = self.emojis[self.next_content_type]
                    logger.info(
                        f"{emoji} Next content rotation post scheduled for "
                        f"{next_post_time.strftime('%I:%M %p')} "
                        f"({self.next_content_type.value}) "
                        f"(in {wait_seconds / 60:.1f} minutes)"
                    )
                    await asyncio.sleep(wait_seconds)

                if self.is_running:
                    await self._post_next_content()

            except asyncio.CancelledError:
                logger.info("Content rotation scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Content rotation scheduler loop error: {e}")
                await asyncio.sleep(300)  # Retry after 5 minutes on error

    async def _post_next_content(self) -> None:
        """
        Post the next content type in rotation.

        Tries to post current content type. If no new content is available,
        tries the next type in rotation. If all types are exhausted, goes
        back to news.
        """
        attempts = 0
        max_attempts = 3  # Try all 3 content types

        while attempts < max_attempts:
            content_type = self.next_content_type
            emoji = self.emojis[content_type]
            callback = self.callbacks[content_type]
            scraper = self.scrapers[content_type]

            logger.info(f"{emoji}⏰ Hourly content rotation triggered: {content_type.value}")

            # Check if this content type has new unposted articles
            if scraper and await self._has_new_content(content_type, scraper):
                # Post this content type
                try:
                    await callback()
                    logger.success(f"{emoji} Posted {content_type.value} content successfully")

                    # Move to next content type in rotation for next hour
                    self._rotate_to_next_type()
                    self._save_state()
                    return

                except Exception as e:
                    logger.error(f"Failed to post {content_type.value}: {e}")
                    # Still rotate even if posting failed
                    self._rotate_to_next_type()
                    self._save_state()
                    return
            else:
                # No new content for this type, try next type
                logger.info(f"{emoji} No new {content_type.value} content available - skipping to next type")
                self._rotate_to_next_type()
                attempts += 1

        # All content types exhausted - log and wait for next hour
        logger.warning("🔄 No new content available from any source - skipping this hour")

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
            elif content_type == ContentType.SOCCER:
                articles = await scraper.fetch_latest_soccer_news(max_articles=1, hours_back=24)
            else:  # GAMING
                articles = await scraper.fetch_latest_gaming_news(max_articles=1, hours_back=24)

            # If we got articles, there's new content
            # The scrapers already filter out posted content
            return bool(articles)

        except Exception as e:
            logger.error(f"Error checking for new {content_type.value} content: {e}")
            return False

    def _rotate_to_next_type(self) -> None:
        """Move to the next content type in rotation."""
        if self.next_content_type == ContentType.NEWS:
            self.next_content_type = ContentType.SOCCER
        elif self.next_content_type == ContentType.SOCCER:
            self.next_content_type = ContentType.GAMING
        else:  # GAMING
            self.next_content_type = ContentType.NEWS

    def _calculate_next_post_time(self) -> datetime:
        """
        Calculate the next hourly post time (on the hour).

        Returns:
            datetime object for next post time
        """
        now: datetime = datetime.now()

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
                int((next_post - datetime.now()).total_seconds() / 60)
                if next_post
                else None
            ),
        }


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ContentRotationScheduler", "ContentType"]
