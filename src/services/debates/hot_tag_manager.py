"""
Othman Discord Bot - Hot Tag Manager
=====================================

Background task that evaluates and assigns the "Hot" tag to debate threads
once daily at midnight EST.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import discord
from discord.ext import tasks
from datetime import datetime, time
from typing import Optional, TYPE_CHECKING
from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, DISCORD_ARCHIVED_THREADS_LIMIT, NY_TZ, LOG_TITLE_PREVIEW_LENGTH
from src.utils import edit_thread_with_retry
from src.services.debates.tags import DEBATE_TAGS, should_have_hot_tag

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

MIDNIGHT_EST = time(hour=0, minute=0, tzinfo=NY_TZ)
"""Time when hot tag evaluation runs (midnight EST)."""


# =============================================================================
# Hot Tag Manager Class
# =============================================================================

class HotTagManager:
    """
    Manages the dynamic "Hot" tag on debate threads.

    DESIGN:
    - Runs once daily at midnight EST
    - Evaluates all threads against activity thresholds
    - Adds "Hot" tag to threads that meet criteria
    - Removes "Hot" tag from threads that no longer meet criteria
    - Much less spammy than frequent evaluations
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
            logger.info("Hot Tag Manager Started", [
                ("Schedule", "Daily at 00:00 EST"),
            ])

    async def stop(self) -> None:
        """Stop the background task."""
        if self.manage_hot_tags.is_running():
            self.manage_hot_tags.cancel()
            logger.info("Hot Tag Manager Stopped")

    # -------------------------------------------------------------------------
    # Main Loop - Runs Daily at Midnight EST
    # -------------------------------------------------------------------------

    @tasks.loop(time=MIDNIGHT_EST)
    async def manage_hot_tags(self) -> None:
        """
        Daily evaluation of all debate threads for Hot tag status.

        DESIGN:
        - Runs once at midnight EST
        - Checks all active and recently archived threads
        - Adds Hot tag to threads meeting activity threshold
        - Removes Hot tag from threads no longer meeting threshold
        - Single daily evaluation prevents notification spam
        """
        try:
            debates_forum = self.bot.get_channel(DEBATES_FORUM_ID)

            if not debates_forum:
                logger.error("Debates Forum Not Found", [
                    ("Forum ID", str(DEBATES_FORUM_ID)),
                ])
                return

            logger.info("🔥 Starting Daily Hot Tag Evaluation", [
                ("Time", datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M EST")),
            ])

            added_count = 0
            removed_count = 0
            kept_count = 0
            checked_count = 0

            # Process all active threads
            for thread in debates_forum.threads:
                if thread is None:
                    continue
                result = await self._evaluate_thread(thread)
                if result == "added":
                    added_count += 1
                elif result == "removed":
                    removed_count += 1
                elif result == "kept":
                    kept_count += 1
                checked_count += 1
                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)

            # Process recently archived threads
            async for thread in debates_forum.archived_threads(limit=DISCORD_ARCHIVED_THREADS_LIMIT):
                if thread is None:
                    continue
                result = await self._evaluate_thread(thread)
                if result == "added":
                    added_count += 1
                elif result == "removed":
                    removed_count += 1
                elif result == "kept":
                    kept_count += 1
                checked_count += 1
                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)

            logger.success("🔥 Daily Hot Tag Evaluation Complete", [
                ("Threads Checked", str(checked_count)),
                ("Tags Added", str(added_count)),
                ("Tags Removed", str(removed_count)),
                ("Tags Kept", str(kept_count)),
            ])

        except discord.HTTPException as e:
            logger.error("Discord API Error In Hot Tag Evaluation", [
                ("Error", str(e)),
            ])
        except Exception as e:
            logger.error("Error In Daily Hot Tag Evaluation", [
                ("Error", str(e)),
                ("Error Type", type(e).__name__),
            ])

    @manage_hot_tags.before_loop
    async def before_manage_hot_tags(self) -> None:
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()
        logger.info("Hot Tag Manager Ready", [
            ("Next Run", "00:00 EST"),
        ])

    # -------------------------------------------------------------------------
    # Thread Evaluation
    # -------------------------------------------------------------------------

    async def _evaluate_thread(self, thread: discord.Thread) -> str:
        """
        Evaluate a single thread for Hot tag status.

        Args:
            thread: The Discord thread to evaluate

        Returns:
            "added" if Hot tag was added
            "removed" if Hot tag was removed
            "kept" if Hot tag was kept (already had and still deserves)
            "none" if no change needed (didn't have and doesn't deserve)
        """
        try:
            # Skip deprecated threads
            if thread.name.startswith("[DEPRECATED]"):
                return "none"

            # Get thread metrics
            message_count = self._get_message_count(thread)
            hours_since_last = await self._get_hours_since_last_message(thread)

            # Determine if thread deserves Hot tag
            deserves_hot = should_have_hot_tag(message_count, hours_since_last)

            # Check current Hot tag status
            current_tag_ids = [tag.id for tag in thread.applied_tags]
            has_hot = self.hot_tag_id in current_tag_ids

            if deserves_hot and not has_hot:
                # Add Hot tag
                await self._add_hot_tag(thread)
                logger.info("🔥 Hot Tag Added", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Messages", str(message_count)),
                    ("Last Activity", f"{hours_since_last:.1f}h ago"),
                ])

                # Log to webhook
                if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_hot_tag_added(
                        thread.name, thread.id,
                        f"{message_count} messages, active {hours_since_last:.1f}h ago"
                    )
                return "added"

            elif not deserves_hot and has_hot:
                # Remove Hot tag
                await self._remove_hot_tag(thread)
                logger.info("❄️ Hot Tag Removed", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Messages", str(message_count)),
                    ("Last Activity", f"{hours_since_last:.1f}h ago"),
                ])

                # Log to webhook
                if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_hot_tag_removed(
                        thread.name, thread.id,
                        f"No longer meets criteria ({message_count} msgs, {hours_since_last:.1f}h inactive)"
                    )
                return "removed"

            elif deserves_hot and has_hot:
                # Keep Hot tag (still deserves it)
                return "kept"

            return "none"

        except discord.HTTPException as e:
            logger.warning("Discord API Error Evaluating Thread", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
            ])
            return "none"
        except Exception as e:
            logger.error("Error Evaluating Thread", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
            ])
            return "none"

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _get_message_count(self, thread: discord.Thread) -> int:
        """
        Get the total number of messages in a thread.

        Args:
            thread: The Discord thread

        Returns:
            Number of messages (from thread.message_count property)
        """
        return thread.message_count if hasattr(thread, 'message_count') else 0

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
                # Fetch only the most recent message
                messages = [msg async for msg in thread.history(limit=1)]
                if messages:
                    last_activity = messages[0].created_at
                else:
                    last_activity = thread.created_at

            now = datetime.now(NY_TZ)

            # Convert to timezone-aware if needed
            if last_activity.tzinfo is None:
                # Discord timestamps are UTC, convert properly
                from datetime import timezone
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            # Convert both to UTC for accurate comparison
            delta = now.astimezone(NY_TZ) - last_activity.astimezone(NY_TZ)
            return max(0.0, delta.total_seconds() / 3600)

        except Exception as e:
            logger.warning("Error Getting Last Message Time", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
            ])
            # Fallback: return value that won't qualify for hot tag
            return 999.0

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
            current_tags = list(thread.applied_tags)
            debates_forum = thread.parent

            if not debates_forum:
                return

            hot_tag = discord.utils.get(debates_forum.available_tags, id=self.hot_tag_id)

            if hot_tag:
                current_tags.append(hot_tag)
                await edit_thread_with_retry(thread, applied_tags=current_tags[:5])
            else:
                logger.error("Hot Tag Object Not Found In Forum Tags")

        except discord.HTTPException as e:
            logger.warning("Failed To Add Hot Tag", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
            ])

    async def _remove_hot_tag(self, thread: discord.Thread) -> None:
        """
        Remove the Hot tag from a thread.

        Args:
            thread: The Discord thread
        """
        try:
            current_tags = [tag for tag in thread.applied_tags if tag.id != self.hot_tag_id]
            await edit_thread_with_retry(thread, applied_tags=current_tags)

        except discord.HTTPException as e:
            logger.warning("Failed To Remove Hot Tag", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["HotTagManager"]
