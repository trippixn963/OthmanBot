"""
Othman Discord Bot - Hot Tag Manager
=====================================

Background task that dynamically manages the "Hot" tag on debate threads
based on activity levels.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord.ext import tasks
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, DISCORD_ARCHIVED_THREADS_LIMIT, NY_TZ
from src.utils import edit_thread_with_retry
from src.services.debates.tags import DEBATE_TAGS, should_add_hot_tag, should_remove_hot_tag

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Hot Tag Manager Class
# =============================================================================

class HotTagManager:
    """
    Manages the dynamic "Hot" tag on debate threads.

    DESIGN:
    - Runs every 10 minutes to check all active debate threads
    - Adds "Hot" tag to threads with high activity
    - Removes "Hot" tag from threads that have become inactive
    - Never interferes with other tags (religion, politics, etc.)
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the Hot Tag Manager.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self.hot_tag_id = DEBATE_TAGS["hot"]

    # -------------------------------------------------------------------------
    # Start/Stop Controls
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background task."""
        if not self.manage_hot_tags.is_running():
            self.manage_hot_tags.start()
            logger.info("Hot tag manager started")

    async def stop(self) -> None:
        """Stop the background task."""
        if self.manage_hot_tags.is_running():
            self.manage_hot_tags.cancel()
            logger.info("Hot tag manager stopped")

    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------

    @tasks.loop(minutes=10)
    async def manage_hot_tags(self) -> None:
        """
        Periodically check all debate threads and manage Hot tags.

        DESIGN:
        - Checks both active and recently archived threads
        - Calculates activity metrics for each thread
        - Adds/removes Hot tag based on criteria from tags.py
        - Logs all tag changes for monitoring
        """
        try:
            debates_forum = self.bot.get_channel(DEBATES_FORUM_ID)

            if not debates_forum:
                logger.error("Debates Forum Not Found", [
                    ("Forum ID", str(DEBATES_FORUM_ID)),
                ])
                return

            logger.info("Starting Hot tag management cycle")

            added_count = 0
            removed_count = 0
            checked_count = 0

            # Check all active threads
            for thread in debates_forum.threads:
                if await self._process_thread(thread):
                    added_count += 1
                elif await self._should_remove_hot(thread):
                    removed_count += 1
                checked_count += 1

            # Check recently archived threads (in case they were just archived)
            async for thread in debates_forum.archived_threads(limit=DISCORD_ARCHIVED_THREADS_LIMIT):
                if await self._process_thread(thread):
                    added_count += 1
                elif await self._should_remove_hot(thread):
                    removed_count += 1
                checked_count += 1

            logger.info("🔥 Hot Tag Cycle Complete", [
                ("Threads Checked", str(checked_count)),
                ("Tags Added", str(added_count)),
                ("Tags Removed", str(removed_count)),
            ])

        except Exception as e:
            logger.error("Error In Hot Tag Management Cycle", [
                ("Error", str(e)),
            ])

    @manage_hot_tags.before_loop
    async def before_manage_hot_tags(self) -> None:
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()
        logger.info("Hot tag manager ready to start")

    # -------------------------------------------------------------------------
    # Thread Processing
    # -------------------------------------------------------------------------

    async def _process_thread(self, thread: discord.Thread) -> bool:
        """
        Process a single thread and add Hot tag if needed.

        Args:
            thread: The Discord thread to process

        Returns:
            True if Hot tag was added, False otherwise
        """
        try:
            # Skip deprecated threads
            if thread.name.startswith("[DEPRECATED]"):
                return False

            # Get thread metrics
            message_count = await self._get_message_count(thread)
            hours_since_creation = self._get_hours_since_creation(thread)

            # Check if thread should have Hot tag
            if should_add_hot_tag(message_count, hours_since_creation):
                # Check if thread already has Hot tag
                current_tag_ids = [tag.id for tag in thread.applied_tags]

                if self.hot_tag_id not in current_tag_ids:
                    # Add Hot tag
                    await self._add_hot_tag(thread)
                    logger.info("🔥 Added Hot Tag", [
                        ("Thread", thread.name[:30]),
                        ("Messages", str(message_count)),
                        ("Age", f"{hours_since_creation:.1f}h"),
                    ])

                    # Log to webhook
                    if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
                        await self.bot.interaction_logger.log_hot_tag_added(
                            thread.name, thread.id, f"{message_count} messages in {hours_since_creation:.1f}h"
                        )
                    return True

            return False

        except Exception as e:
            logger.error("Error Processing Thread", [
                ("Thread", thread.name[:30]),
                ("Error", str(e)),
            ])
            return False

    async def _should_remove_hot(self, thread: discord.Thread) -> bool:
        """
        Check if Hot tag should be removed from a thread.

        Args:
            thread: The Discord thread to check

        Returns:
            True if Hot tag was removed, False otherwise
        """
        try:
            # Skip if thread doesn't have Hot tag
            current_tag_ids = [tag.id for tag in thread.applied_tags]
            if self.hot_tag_id not in current_tag_ids:
                return False

            # Get time since last message
            hours_since_last = await self._get_hours_since_last_message(thread)
            message_count = await self._get_message_count(thread)

            # Check if thread should lose Hot tag
            if should_remove_hot_tag(message_count, hours_since_last):
                await self._remove_hot_tag(thread)
                logger.info("🔥 Removed Hot Tag", [
                    ("Thread", thread.name[:30]),
                    ("Inactive", f"{hours_since_last:.1f}h"),
                ])

                # Log to webhook
                if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_hot_tag_removed(
                        thread.name, thread.id, f"Inactive for {hours_since_last:.1f}h"
                    )
                return True

            return False

        except Exception as e:
            logger.error("Error Checking Hot Tag Removal", [
                ("Thread", thread.name[:30]),
                ("Error", str(e)),
            ])
            return False

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    async def _get_message_count(self, thread: discord.Thread) -> int:
        """
        Get the total number of messages in a thread.

        Args:
            thread: The Discord thread

        Returns:
            Number of messages (estimate from thread.message_count if available)
        """
        # Use the cached message_count property if available
        # Note: This may be slightly inaccurate, but it's much faster than fetching all messages
        return thread.message_count if hasattr(thread, 'message_count') else 0

    def _get_hours_since_creation(self, thread: discord.Thread) -> float:
        """
        Calculate hours since thread was created.

        Args:
            thread: The Discord thread

        Returns:
            Hours since creation
        """
        now = datetime.now(NY_TZ)
        created_at = thread.created_at

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=NY_TZ)

        delta = now - created_at
        return delta.total_seconds() / 3600

    async def _get_hours_since_last_message(self, thread: discord.Thread) -> float:
        """
        Calculate hours since last message in thread.

        Args:
            thread: The Discord thread

        Returns:
            Hours since last message (or since creation if no messages)
        """
        try:
            # Use archive_timestamp if thread is archived
            if thread.archived and thread.archive_timestamp:
                last_activity = thread.archive_timestamp
            else:
                # Try to get the last message timestamp
                # Fetch only the most recent message to minimize API calls
                messages = [msg async for msg in thread.history(limit=1)]
                if messages:
                    last_activity = messages[0].created_at
                else:
                    # No messages, use creation time
                    last_activity = thread.created_at

            now = datetime.now(NY_TZ)

            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=NY_TZ)

            delta = now - last_activity
            return delta.total_seconds() / 3600

        except Exception as e:
            logger.error("Error Getting Last Message Time", [
                ("Thread", thread.name[:30]),
                ("Error", str(e)),
            ])
            # Fallback to creation time
            return self._get_hours_since_creation(thread)

    # -------------------------------------------------------------------------
    # Tag Operations
    # -------------------------------------------------------------------------

    async def _add_hot_tag(self, thread: discord.Thread) -> None:
        """
        Add the Hot tag to a thread.

        Args:
            thread: The Discord thread
        """
        try:
            # Get current tags
            current_tags = list(thread.applied_tags)

            # Find the Hot tag object from the forum
            debates_forum = thread.parent
            hot_tag = discord.utils.get(debates_forum.available_tags, id=self.hot_tag_id)

            if hot_tag:
                # Add Hot tag to the list
                current_tags.append(hot_tag)

                # Update thread tags (max 5 tags allowed by Discord) with rate limit handling
                await edit_thread_with_retry(thread, applied_tags=current_tags[:5])
            else:
                logger.error("Hot Tag Object Not Found In Forum Tags")

        except Exception as e:
            logger.error("Failed To Add Hot Tag", [
                ("Thread", thread.name[:30]),
                ("Error", str(e)),
            ])

    async def _remove_hot_tag(self, thread: discord.Thread) -> None:
        """
        Remove the Hot tag from a thread.

        Args:
            thread: The Discord thread
        """
        try:
            # Get current tags, excluding the Hot tag
            current_tags = [tag for tag in thread.applied_tags if tag.id != self.hot_tag_id]

            # Update thread tags with rate limit handling
            await edit_thread_with_retry(thread, applied_tags=current_tags)

        except Exception as e:
            logger.error("Failed To Remove Hot Tag", [
                ("Thread", thread.name[:30]),
                ("Error", str(e)),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["HotTagManager"]
