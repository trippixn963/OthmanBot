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
from datetime import datetime, time, timezone
from typing import Optional, List, TYPE_CHECKING
from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, DISCORD_ARCHIVED_THREADS_LIMIT, NY_TZ, LOG_TITLE_PREVIEW_LENGTH
from src.utils import edit_thread_with_retry
from src.services.debates.tags import DEBATE_TAGS, should_have_hot_tag, HOT_MIN_MESSAGES, HOT_MAX_INACTIVITY_HOURS

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

MIDNIGHT_EST = time(hour=0, minute=0, tzinfo=NY_TZ)
"""Time when hot tag evaluation runs (midnight EST)."""

RATE_LIMIT_DELAY: float = 0.5
"""Delay between thread evaluations to avoid rate limits (seconds)."""


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
        logger.debug("Hot Tag Manager Initialized", [
            ("Hot Tag ID", str(self.hot_tag_id)),
            ("Min Messages", str(HOT_MIN_MESSAGES)),
            ("Max Inactivity", f"{HOT_MAX_INACTIVITY_HOURS}h"),
        ])

    # -------------------------------------------------------------------------
    # Start/Stop Controls
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background task."""
        if not self.manage_hot_tags.is_running():
            self.manage_hot_tags.start()
            logger.info("🔥 Hot Tag Manager Started", [
                ("Schedule", "Daily at 00:00 EST"),
                ("Criteria", f"≥{HOT_MIN_MESSAGES} msgs + active within {HOT_MAX_INACTIVITY_HOURS}h"),
            ])

    async def stop(self) -> None:
        """Stop the background task."""
        if self.manage_hot_tags.is_running():
            self.manage_hot_tags.cancel()
            logger.info("🔥 Hot Tag Manager Stopped")

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
        start_time = datetime.now(NY_TZ)

        logger.info("=" * 60)
        logger.info("🔥 DAILY HOT TAG EVALUATION STARTED", [
            ("Time", start_time.strftime("%Y-%m-%d %H:%M:%S EST")),
            ("Criteria", f"≥{HOT_MIN_MESSAGES} messages AND active within {HOT_MAX_INACTIVITY_HOURS}h"),
        ])
        logger.info("=" * 60)

        try:
            debates_forum = self.bot.get_channel(DEBATES_FORUM_ID)

            if not debates_forum:
                logger.error("🔥 Hot Tag Evaluation ABORTED - Forum Not Found", [
                    ("Forum ID", str(DEBATES_FORUM_ID)),
                    ("Reason", "Channel not found or bot lacks access"),
                ])
                return

            logger.debug("Forum Channel Retrieved", [
                ("Forum Name", getattr(debates_forum, 'name', 'Unknown')),
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])

            # Statistics tracking
            stats = {
                "added": 0,
                "removed": 0,
                "kept": 0,
                "skipped_deprecated": 0,
                "skipped_no_change": 0,
                "errors": 0,
                "active_checked": 0,
                "archived_checked": 0,
            }

            # Track threads for summary
            added_threads: List[str] = []
            removed_threads: List[str] = []
            kept_threads: List[str] = []

            # Process all active threads
            logger.info("📋 Processing Active Threads...")
            active_thread_count = len(debates_forum.threads)
            logger.debug("Active Threads Found", [("Count", str(active_thread_count))])

            for idx, thread in enumerate(debates_forum.threads, 1):
                if thread is None:
                    logger.warning("Null Thread Encountered", [("Index", str(idx))])
                    continue

                result, thread_name = await self._evaluate_thread_with_logging(thread, idx, active_thread_count)
                stats["active_checked"] += 1

                if result == "added":
                    stats["added"] += 1
                    added_threads.append(thread_name)
                elif result == "removed":
                    stats["removed"] += 1
                    removed_threads.append(thread_name)
                elif result == "kept":
                    stats["kept"] += 1
                    kept_threads.append(thread_name)
                elif result == "skipped_deprecated":
                    stats["skipped_deprecated"] += 1
                elif result == "error":
                    stats["errors"] += 1
                else:
                    stats["skipped_no_change"] += 1

                # Rate limit delay
                await asyncio.sleep(RATE_LIMIT_DELAY)

            # Process recently archived threads
            logger.info("📋 Processing Archived Threads...")
            archived_idx = 0

            async for thread in debates_forum.archived_threads(limit=DISCORD_ARCHIVED_THREADS_LIMIT):
                archived_idx += 1
                if thread is None:
                    logger.warning("Null Archived Thread Encountered", [("Index", str(archived_idx))])
                    continue

                result, thread_name = await self._evaluate_thread_with_logging(
                    thread, archived_idx, DISCORD_ARCHIVED_THREADS_LIMIT, is_archived=True
                )
                stats["archived_checked"] += 1

                if result == "added":
                    stats["added"] += 1
                    added_threads.append(thread_name)
                elif result == "removed":
                    stats["removed"] += 1
                    removed_threads.append(thread_name)
                elif result == "kept":
                    stats["kept"] += 1
                    kept_threads.append(thread_name)
                elif result == "skipped_deprecated":
                    stats["skipped_deprecated"] += 1
                elif result == "error":
                    stats["errors"] += 1
                else:
                    stats["skipped_no_change"] += 1

                # Rate limit delay
                await asyncio.sleep(RATE_LIMIT_DELAY)

            # Calculate duration
            end_time = datetime.now(NY_TZ)
            duration = (end_time - start_time).total_seconds()

            # Log comprehensive summary
            logger.info("=" * 60)
            logger.success("🔥 DAILY HOT TAG EVALUATION COMPLETE", [
                ("Duration", f"{duration:.1f}s"),
                ("Active Checked", str(stats["active_checked"])),
                ("Archived Checked", str(stats["archived_checked"])),
                ("Total Checked", str(stats["active_checked"] + stats["archived_checked"])),
            ])

            logger.info("📊 Hot Tag Changes Summary", [
                ("Tags Added", str(stats["added"])),
                ("Tags Removed", str(stats["removed"])),
                ("Tags Kept", str(stats["kept"])),
                ("No Hot Tag", str(stats["skipped_no_change"])),
                ("Deprecated Skipped", str(stats["skipped_deprecated"])),
                ("Errors", str(stats["errors"])),
            ])

            # Log specific thread changes
            if added_threads:
                logger.info("🔥 Threads That GAINED Hot Tag", [
                    ("Count", str(len(added_threads))),
                    ("Threads", ", ".join(added_threads[:5]) + ("..." if len(added_threads) > 5 else "")),
                ])

            if removed_threads:
                logger.info("❄️ Threads That LOST Hot Tag", [
                    ("Count", str(len(removed_threads))),
                    ("Threads", ", ".join(removed_threads[:5]) + ("..." if len(removed_threads) > 5 else "")),
                ])

            if kept_threads:
                logger.debug("🔥 Threads That KEPT Hot Tag", [
                    ("Count", str(len(kept_threads))),
                    ("Threads", ", ".join(kept_threads[:5]) + ("..." if len(kept_threads) > 5 else "")),
                ])

            logger.info("=" * 60)

            # Send webhook summary
            if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
                await self.bot.interaction_logger.log_hot_tag_evaluation_summary(
                    stats=stats,
                    duration=duration,
                    added_threads=added_threads,
                    removed_threads=removed_threads
                )

        except discord.HTTPException as e:
            logger.error("🔥 Hot Tag Evaluation FAILED - Discord API Error", [
                ("Error", str(e)),
                ("Error Code", str(e.code) if hasattr(e, 'code') else "N/A"),
                ("Status", str(e.status) if hasattr(e, 'status') else "N/A"),
            ])
        except Exception as e:
            logger.error("🔥 Hot Tag Evaluation FAILED - Unexpected Error", [
                ("Error", str(e)),
                ("Error Type", type(e).__name__),
            ])

    @manage_hot_tags.before_loop
    async def before_manage_hot_tags(self) -> None:
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

        # Calculate time until next run
        now = datetime.now(NY_TZ)
        next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.hour >= 0:
            from datetime import timedelta
            next_midnight += timedelta(days=1)
        time_until = next_midnight - now
        hours_until = time_until.total_seconds() / 3600

        logger.info("🔥 Hot Tag Manager Ready", [
            ("Next Run", next_midnight.strftime("%Y-%m-%d %H:%M EST")),
            ("Time Until", f"{hours_until:.1f}h"),
            ("Criteria", f"≥{HOT_MIN_MESSAGES} msgs + ≤{HOT_MAX_INACTIVITY_HOURS}h inactive"),
        ])

    # -------------------------------------------------------------------------
    # Thread Evaluation
    # -------------------------------------------------------------------------

    async def _evaluate_thread_with_logging(
        self,
        thread: discord.Thread,
        idx: int,
        total: int,
        is_archived: bool = False
    ) -> tuple[str, str]:
        """
        Evaluate a thread with comprehensive logging.

        Returns:
            Tuple of (result_code, thread_name_preview)
        """
        thread_preview = thread.name[:LOG_TITLE_PREVIEW_LENGTH]
        thread_type = "Archived" if is_archived else "Active"

        try:
            # Skip deprecated threads
            if thread.name.startswith("[DEPRECATED]"):
                logger.debug(f"[{idx}/{total}] Skipping Deprecated Thread", [
                    ("Thread", thread_preview),
                    ("Type", thread_type),
                ])
                return "skipped_deprecated", thread_preview

            # Get thread metrics
            message_count = self._get_message_count(thread)
            hours_since_last = await self._get_hours_since_last_message(thread)

            # Determine if thread deserves Hot tag
            deserves_hot = should_have_hot_tag(message_count, hours_since_last)

            # Check current Hot tag status
            current_tag_ids = [tag.id for tag in thread.applied_tags]
            has_hot = self.hot_tag_id in current_tag_ids

            # Log evaluation details
            logger.debug(f"[{idx}/{total}] Evaluating Thread", [
                ("Thread", thread_preview),
                ("Type", thread_type),
                ("Messages", str(message_count)),
                ("Last Activity", f"{hours_since_last:.1f}h ago"),
                ("Has Hot Tag", "Yes" if has_hot else "No"),
                ("Deserves Hot", "Yes" if deserves_hot else "No"),
                ("Meets Msg Threshold", "Yes" if message_count >= HOT_MIN_MESSAGES else f"No ({message_count}<{HOT_MIN_MESSAGES})"),
                ("Meets Activity Threshold", "Yes" if hours_since_last <= HOT_MAX_INACTIVITY_HOURS else f"No ({hours_since_last:.1f}>{HOT_MAX_INACTIVITY_HOURS})"),
            ])

            if deserves_hot and not has_hot:
                # Add Hot tag
                await self._add_hot_tag(thread)
                logger.info(f"🔥 [{idx}/{total}] Hot Tag ADDED", [
                    ("Thread", thread_preview),
                    ("Thread ID", str(thread.id)),
                    ("Type", thread_type),
                    ("Messages", str(message_count)),
                    ("Last Activity", f"{hours_since_last:.1f}h ago"),
                    ("Reason", f"≥{HOT_MIN_MESSAGES} msgs AND active within {HOT_MAX_INACTIVITY_HOURS}h"),
                ])

                # Log to webhook
                if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_hot_tag_added(
                        thread.name, thread.id,
                        f"{message_count} messages, active {hours_since_last:.1f}h ago"
                    )
                return "added", thread_preview

            elif not deserves_hot and has_hot:
                # Remove Hot tag
                reason_parts = []
                if message_count < HOT_MIN_MESSAGES:
                    reason_parts.append(f"only {message_count} msgs (need {HOT_MIN_MESSAGES})")
                if hours_since_last > HOT_MAX_INACTIVITY_HOURS:
                    reason_parts.append(f"inactive {hours_since_last:.1f}h (max {HOT_MAX_INACTIVITY_HOURS}h)")
                reason = " AND ".join(reason_parts) if reason_parts else "criteria not met"

                await self._remove_hot_tag(thread)
                logger.info(f"❄️ [{idx}/{total}] Hot Tag REMOVED", [
                    ("Thread", thread_preview),
                    ("Thread ID", str(thread.id)),
                    ("Type", thread_type),
                    ("Messages", str(message_count)),
                    ("Last Activity", f"{hours_since_last:.1f}h ago"),
                    ("Reason", reason),
                ])

                # Log to webhook
                if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_hot_tag_removed(
                        thread.name, thread.id,
                        f"No longer meets criteria: {reason}"
                    )
                return "removed", thread_preview

            elif deserves_hot and has_hot:
                # Keep Hot tag (still deserves it)
                logger.debug(f"[{idx}/{total}] Hot Tag KEPT", [
                    ("Thread", thread_preview),
                    ("Messages", str(message_count)),
                    ("Last Activity", f"{hours_since_last:.1f}h ago"),
                ])
                return "kept", thread_preview

            # No hot tag and doesn't deserve one
            logger.debug(f"[{idx}/{total}] No Hot Tag (Not Qualified)", [
                ("Thread", thread_preview),
                ("Messages", str(message_count)),
                ("Last Activity", f"{hours_since_last:.1f}h ago"),
            ])
            return "none", thread_preview

        except discord.HTTPException as e:
            logger.warning(f"[{idx}/{total}] Discord API Error Evaluating Thread", [
                ("Thread", thread_preview),
                ("Error", str(e)),
                ("Error Code", str(e.code) if hasattr(e, 'code') else "N/A"),
            ])
            return "error", thread_preview
        except Exception as e:
            logger.error(f"[{idx}/{total}] Error Evaluating Thread", [
                ("Thread", thread_preview),
                ("Error", str(e)),
                ("Error Type", type(e).__name__),
            ])
            return "error", thread_preview

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
        count = thread.message_count if hasattr(thread, 'message_count') and thread.message_count else 0
        return count

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
                source = "archive_timestamp"
            else:
                # Fetch only the most recent message
                messages = [msg async for msg in thread.history(limit=1)]
                if messages:
                    last_activity = messages[0].created_at
                    source = "last_message"
                else:
                    last_activity = thread.created_at
                    source = "created_at"

            now = datetime.now(NY_TZ)

            # Convert to timezone-aware if needed
            if last_activity.tzinfo is None:
                # Discord timestamps are UTC
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            # Convert both to same timezone for accurate comparison
            delta = now - last_activity.astimezone(NY_TZ)
            hours = max(0.0, delta.total_seconds() / 3600)

            logger.debug("Last Activity Calculated", [
                ("Thread", thread.name[:30]),
                ("Source", source),
                ("Last Activity", last_activity.strftime("%Y-%m-%d %H:%M UTC")),
                ("Hours Ago", f"{hours:.2f}"),
            ])

            return hours

        except Exception as e:
            logger.warning("Error Getting Last Message Time", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
                ("Error Type", type(e).__name__),
                ("Fallback", "999.0h (won't qualify)"),
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
            current_tag_names = [t.name for t in current_tags]
            debates_forum = thread.parent

            if not debates_forum:
                logger.warning("Cannot Add Hot Tag - No Parent Forum", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Thread ID", str(thread.id)),
                ])
                return

            hot_tag = discord.utils.get(debates_forum.available_tags, id=self.hot_tag_id)

            if hot_tag:
                current_tags.append(hot_tag)
                new_tag_names = [t.name for t in current_tags[:5]]

                await edit_thread_with_retry(thread, applied_tags=current_tags[:5])

                logger.debug("Hot Tag Successfully Added", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Previous Tags", ", ".join(current_tag_names) or "None"),
                    ("New Tags", ", ".join(new_tag_names)),
                ])
            else:
                logger.error("Hot Tag Object Not Found In Forum Tags", [
                    ("Expected ID", str(self.hot_tag_id)),
                    ("Forum", getattr(debates_forum, 'name', 'Unknown')),
                ])

        except discord.HTTPException as e:
            logger.warning("Failed To Add Hot Tag", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
                ("Error Code", str(e.code) if hasattr(e, 'code') else "N/A"),
            ])

    async def _remove_hot_tag(self, thread: discord.Thread) -> None:
        """
        Remove the Hot tag from a thread.

        Args:
            thread: The Discord thread
        """
        try:
            old_tags = [t.name for t in thread.applied_tags]
            current_tags = [tag for tag in thread.applied_tags if tag.id != self.hot_tag_id]
            new_tags = [t.name for t in current_tags]

            await edit_thread_with_retry(thread, applied_tags=current_tags)

            logger.debug("Hot Tag Successfully Removed", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Previous Tags", ", ".join(old_tags)),
                ("New Tags", ", ".join(new_tags) or "None"),
            ])

        except discord.HTTPException as e:
            logger.warning("Failed To Remove Hot Tag", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
                ("Error Code", str(e.code) if hasattr(e, 'code') else "N/A"),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["HotTagManager"]
