"""
OthmanBot - Stale Debate Archive Manager
=========================================

Archives debate threads inactive for 14+ days.
Called by the centralized MaintenanceScheduler at 00:20 EST.

Author: Claude Code
Server: discord.gg/syria
"""

import asyncio
import discord
from datetime import datetime, timezone
from typing import List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, NY_TZ, LOG_TITLE_PREVIEW_LENGTH
from src.utils import edit_thread_with_retry

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

STALE_DAYS_THRESHOLD: int = 14
"""Days of inactivity before a thread is considered stale."""

RATE_LIMIT_DELAY: float = 1.0
"""Delay between thread operations to avoid rate limits (seconds)."""


# =============================================================================
# Stale Archive Manager Class
# =============================================================================

class StaleArchiveManager:
    """
    Manages automatic archival of stale debate threads.

    DESIGN:
    - Called by MaintenanceScheduler at 00:20 EST
    - Checks all active threads for inactivity
    - Archives threads inactive for 14+ days
    - Adds "[STALE]" prefix to archived threads
    - Excludes: Open Discussion, already closed/deprecated threads
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the Stale Archive Manager.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot

    # -------------------------------------------------------------------------
    # Main Archive Method
    # -------------------------------------------------------------------------

    async def archive_stale_debates(self) -> dict:
        """
        Check for and archive stale debates.

        Returns:
            Dict with archival statistics
        """
        start_time = datetime.now(NY_TZ)

        try:
            debates_forum = self.bot.get_channel(DEBATES_FORUM_ID)

            if not debates_forum or not isinstance(debates_forum, discord.ForumChannel):
                logger.tree("Stale Archive Check ABORTED - Forum Not Found", [
                    ("Forum ID", str(DEBATES_FORUM_ID)),
                ], emoji="❌")
                return {"error": "Forum not found"}

            # Get Open Discussion thread ID to skip
            open_discussion_id = None
            if hasattr(self.bot, 'debates_service') and self.bot.debates_service:
                open_discussion_id = self.bot.debates_service.db.get_open_discussion_thread_id()

            # Statistics tracking
            stats = {
                "threads_checked": 0,
                "threads_archived": 0,
                "threads_skipped_closed": 0,
                "threads_skipped_active": 0,
                "errors": 0,
            }

            archived_threads: List[str] = []

            # Process only active (non-archived) threads
            for thread in debates_forum.threads:
                if thread is None:
                    continue

                stats["threads_checked"] += 1
                thread_preview = thread.name[:LOG_TITLE_PREVIEW_LENGTH]

                # Skip already archived threads
                if thread.archived:
                    continue

                # Skip Open Discussion thread
                if open_discussion_id and thread.id == open_discussion_id:
                    logger.debug("Skipping Open Discussion Thread", [
                        ("Thread", thread_preview),
                    ])
                    continue

                # Skip already closed/deprecated/stale threads
                if any(thread.name.startswith(prefix) for prefix in ["[CLOSED]", "[DEPRECATED]", "[STALE]"]):
                    stats["threads_skipped_closed"] += 1
                    continue

                try:
                    # Check days since last activity
                    days_inactive = await self._get_days_since_last_message(thread)

                    if days_inactive >= STALE_DAYS_THRESHOLD:
                        # Archive the thread
                        await self._archive_stale_thread(thread, days_inactive)
                        stats["threads_archived"] += 1
                        archived_threads.append(f"{thread_preview} ({days_inactive:.0f}d)")

                        logger.tree("Stale Thread Archived", [
                            ("Thread", thread_preview),
                            ("Thread ID", str(thread.id)),
                            ("Days Inactive", f"{days_inactive:.0f}"),
                        ], emoji="🗄️")
                    else:
                        stats["threads_skipped_active"] += 1
                        logger.debug("Thread Still Active", [
                            ("Thread", thread_preview),
                            ("Days Inactive", f"{days_inactive:.1f}"),
                            ("Threshold", f"{STALE_DAYS_THRESHOLD}"),
                        ])

                    await asyncio.sleep(RATE_LIMIT_DELAY)

                except discord.HTTPException as e:
                    stats["errors"] += 1
                    logger.warning("Error Processing Thread", [
                        ("Thread", thread_preview),
                        ("Error", str(e)[:50]),
                    ])
                except Exception as e:
                    stats["errors"] += 1
                    logger.tree("Unexpected Error Processing Thread", [
                        ("Thread", thread_preview),
                        ("Error", str(e)[:50]),
                        ("Type", type(e).__name__),
                    ], emoji="❌")

            # Log archived threads summary
            if archived_threads:
                logger.tree("Threads Archived This Run", [
                    ("Count", str(len(archived_threads))),
                    ("Threads", ", ".join(archived_threads[:5]) + ("..." if len(archived_threads) > 5 else "")),
                ], emoji="📋")

            return stats

        except Exception as e:
            logger.tree("Stale Archive Check FAILED", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
            ], emoji="❌")
            return {"error": str(e)}

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    async def _get_days_since_last_message(self, thread: discord.Thread) -> float:
        """
        Calculate days since last message in thread.

        Args:
            thread: The Discord thread

        Returns:
            Days since last message (or since creation if no messages)
        """
        try:
            # Fetch only the most recent message
            messages = [msg async for msg in thread.history(limit=1)]
            if messages:
                last_activity = messages[0].created_at
            else:
                last_activity = thread.created_at

            now = datetime.now(NY_TZ)

            # Convert to timezone-aware if needed
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            # Calculate days
            delta = now - last_activity.astimezone(NY_TZ)
            days = max(0.0, delta.total_seconds() / 86400)  # 86400 = seconds in a day

            return days

        except Exception as e:
            logger.warning("Error Getting Last Message Time", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
            ])
            # Return 0 to be safe (won't archive)
            return 0.0

    async def _archive_stale_thread(self, thread: discord.Thread, days_inactive: float) -> None:
        """
        Archive a stale thread with [STALE] prefix.

        Args:
            thread: The Discord thread to archive
            days_inactive: Number of days the thread has been inactive
        """
        # Add [STALE] prefix if not already present
        new_name = thread.name
        if not thread.name.startswith("[STALE]"):
            new_name = f"[STALE] {thread.name}"
            # Truncate if too long
            if len(new_name) > 100:
                new_name = new_name[:97] + "..."

        # Archive the thread
        await edit_thread_with_retry(
            thread,
            name=new_name,
            archived=True,
            locked=False,  # Keep unlocked so it can be revived if needed
        )

        # Send a notification message
        try:
            await thread.send(
                f"This debate has been automatically archived after **{int(days_inactive)} days** of inactivity.\n\n"
                f"If you'd like to continue this discussion, a moderator can unarchive it."
            )
        except discord.HTTPException:
            pass  # Best effort - thread might be archived before we can send


# =============================================================================
# Standalone Function (called by MaintenanceScheduler)
# =============================================================================

async def archive_stale_debates(bot: "OthmanBot") -> dict:
    """
    Archive stale debate threads.

    Standalone function called by the centralized MaintenanceScheduler.

    Args:
        bot: The OthmanBot instance

    Returns:
        Dict with archival statistics
    """
    manager = StaleArchiveManager(bot)
    return await manager.archive_stale_debates()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["StaleArchiveManager", "archive_stale_debates"]
