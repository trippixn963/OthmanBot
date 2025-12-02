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
from datetime import datetime, timezone
from typing import Optional
from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID
from src.services.debates.tags import DEBATE_TAGS, should_add_hot_tag, should_remove_hot_tag


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

    def __init__(self, bot):
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

    async def start(self):
        """Start the background task."""
        if not self.manage_hot_tags.is_running():
            self.manage_hot_tags.start()
            logger.info("Hot tag manager started")

    async def stop(self):
        """Stop the background task."""
        if self.manage_hot_tags.is_running():
            self.manage_hot_tags.cancel()
            logger.info("Hot tag manager stopped")

    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------

    @tasks.loop(minutes=10)
    async def manage_hot_tags(self):
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
                logger.error(f"Debates forum not found: {DEBATES_FORUM_ID}")
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
            async for thread in debates_forum.archived_threads(limit=50):
                if await self._process_thread(thread):
                    added_count += 1
                elif await self._should_remove_hot(thread):
                    removed_count += 1
                checked_count += 1

            logger.info(
                f"Hot tag cycle complete: {checked_count} threads checked, "
                f"{added_count} tags added, {removed_count} tags removed"
            )

        except Exception as e:
            logger.error(f"Error in Hot tag management cycle: {e}")

    @manage_hot_tags.before_loop
    async def before_manage_hot_tags(self):
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
                    logger.info(
                        f"Added Hot tag to '{thread.name}' "
                        f"({message_count} messages in {hours_since_creation:.1f}h)"
                    )
                    return True

            return False

        except Exception as e:
            logger.error(f"Error processing thread '{thread.name}': {e}")
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
                logger.info(
                    f"Removed Hot tag from '{thread.name}' "
                    f"({hours_since_last:.1f}h since last message)"
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking Hot tag removal for '{thread.name}': {e}")
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
        now = datetime.now(timezone.utc)
        created_at = thread.created_at

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

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

            now = datetime.now(timezone.utc)

            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            delta = now - last_activity
            return delta.total_seconds() / 3600

        except Exception as e:
            logger.error(f"Error getting last message time for '{thread.name}': {e}")
            # Fallback to creation time
            return self._get_hours_since_creation(thread)

    # -------------------------------------------------------------------------
    # Tag Operations
    # -------------------------------------------------------------------------

    async def _add_hot_tag(self, thread: discord.Thread):
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

                # Update thread tags (max 5 tags allowed by Discord)
                await thread.edit(applied_tags=current_tags[:5])
            else:
                logger.error(f"Hot tag object not found in forum tags")

        except Exception as e:
            logger.error(f"Failed to add Hot tag to '{thread.name}': {e}")

    async def _remove_hot_tag(self, thread: discord.Thread):
        """
        Remove the Hot tag from a thread.

        Args:
            thread: The Discord thread
        """
        try:
            # Get current tags, excluding the Hot tag
            current_tags = [tag for tag in thread.applied_tags if tag.id != self.hot_tag_id]

            # Update thread tags
            await thread.edit(applied_tags=current_tags)

        except Exception as e:
            logger.error(f"Failed to remove Hot tag from '{thread.name}': {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["HotTagManager"]
