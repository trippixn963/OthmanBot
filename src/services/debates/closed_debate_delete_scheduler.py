"""
OthmanBot - Closed Debate Delete Scheduler
==========================================

Background task that auto-deletes closed debates after 24 hours
if they haven't been reopened via an approved appeal.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

CHECK_INTERVAL_MINUTES = 30
"""How often to check for debates due for deletion."""


# =============================================================================
# Closed Debate Delete Scheduler
# =============================================================================

class ClosedDebateDeleteScheduler:
    """
    Scheduler that periodically checks for and deletes closed debates.

    DESIGN:
    - Runs every 30 minutes to check for debates due for deletion
    - Only deletes debates where:
      1. scheduled_deletion_at has passed
      2. No approved appeal exists (reopened_at is NULL)
    - Logs all deletions with comprehensive tree logging
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the closed debate delete scheduler.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot
        logger.tree("Closed Debate Delete Scheduler Initialized", [
            ("Check Interval", f"{CHECK_INTERVAL_MINUTES} minutes"),
            ("Auto-Delete After", "24 hours"),
        ], emoji="🗑️")

    async def start(self) -> None:
        """Start the scheduler."""
        if not self._check_debates_for_deletion.is_running():
            self._check_debates_for_deletion.start()
            logger.info("Closed Debate Delete Scheduler Started", [
                ("Interval", f"{CHECK_INTERVAL_MINUTES} minutes"),
            ])

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self._check_debates_for_deletion.is_running():
            self._check_debates_for_deletion.cancel()
            logger.info("Closed Debate Delete Scheduler Stopped", [
                ("Status", "Task cancelled"),
            ])

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def _check_debates_for_deletion(self) -> None:
        """Check for and delete debates that are due for deletion."""
        try:
            if not hasattr(self.bot, 'debates_service') or not self.bot.debates_service:
                logger.debug("Closed Debate Delete Check Skipped", [
                    ("Reason", "Debates service not ready"),
                ])
                return

            db = self.bot.debates_service.db

            # Get debates scheduled for deletion
            try:
                debates_to_delete = await asyncio.to_thread(db.get_debates_scheduled_for_deletion)
            except Exception as e:
                logger.error("Failed To Query Debates For Deletion", [
                    ("Error", str(e)),
                ])
                return

            if not debates_to_delete:
                logger.debug("No Closed Debates Due For Deletion", [
                    ("Status", "Nothing to delete"),
                ])
                return

            logger.tree("Processing Closed Debates For Deletion", [
                ("Debates Found", str(len(debates_to_delete))),
            ], emoji="🗑️")

            # Get the debates forum
            forum = self.bot.get_channel(DEBATES_FORUM_ID)
            if not forum:
                logger.error("Debates Forum Not Found", [
                    ("Forum ID", str(DEBATES_FORUM_ID)),
                    ("Action", "Skipping deletion"),
                ])
                return

            deleted_count = 0
            failed_count = 0

            for debate in debates_to_delete:
                try:
                    thread_id = debate['thread_id']
                    thread_name = debate['thread_name']
                    owner_id = debate['user_id']
                    closure_id = debate['id']

                    # Check if there's an approved appeal for this thread
                    has_approved_appeal = await self._check_approved_appeal(thread_id, owner_id)

                    if has_approved_appeal:
                        logger.info("Skipping Deletion - Appeal Approved", [
                            ("Thread", f"{thread_name} ({thread_id})"),
                            ("Owner ID", str(owner_id) if owner_id else "Unknown"),
                        ])
                        # Cancel the scheduled deletion
                        await asyncio.to_thread(db.cancel_scheduled_deletion, thread_id)
                        continue

                    # Try to get the thread
                    thread = None
                    try:
                        thread = await self.bot.fetch_channel(thread_id)
                    except discord.NotFound:
                        logger.warning("Thread Already Deleted", [
                            ("Thread", f"{thread_name} ({thread_id})"),
                        ])
                        # Mark as processed
                        await asyncio.to_thread(db.mark_closure_deleted, closure_id)
                        continue
                    except discord.Forbidden:
                        logger.warning("No Permission To Access Thread", [
                            ("Thread", f"{thread_name} ({thread_id})"),
                        ])
                        failed_count += 1
                        continue
                    except Exception as e:
                        logger.warning("Failed To Fetch Thread", [
                            ("Thread", f"{thread_name} ({thread_id})"),
                            ("Error", str(e)),
                        ])
                        failed_count += 1
                        continue

                    if not isinstance(thread, discord.Thread):
                        logger.warning("Channel Is Not A Thread", [
                            ("Channel ID", str(thread_id)),
                            ("Type", type(thread).__name__),
                        ])
                        failed_count += 1
                        continue

                    # Delete the thread
                    try:
                        await thread.delete()

                        logger.tree("Closed Debate Auto-Deleted", [
                            ("Thread", f"{thread_name} ({thread_id})"),
                            ("Owner ID", str(owner_id) if owner_id else "Unknown"),
                            ("Closed By", str(debate['closed_by'])),
                            ("Reason", debate['reason'][:50] if debate['reason'] else "No reason"),
                            ("Closed At", debate['created_at']),
                            ("Scheduled For", debate['scheduled_deletion_at']),
                        ], emoji="🗑️")

                        # Mark as deleted in database
                        await asyncio.to_thread(db.mark_closure_deleted, closure_id)

                        # Clean up thread data
                        try:
                            await asyncio.to_thread(db.delete_thread_data, thread_id)
                        except Exception as e:
                            logger.warning("Failed To Clean Up Thread Data", [
                                ("Thread ID", str(thread_id)),
                                ("Error", str(e)),
                            ])

                        deleted_count += 1

                        # Small delay between deletions to avoid rate limits
                        await asyncio.sleep(1.0)

                    except discord.Forbidden:
                        logger.warning("No Permission To Delete Thread", [
                            ("Thread", f"{thread_name} ({thread_id})"),
                        ])
                        failed_count += 1
                    except discord.HTTPException as e:
                        logger.error("Failed To Delete Thread (HTTP Error)", [
                            ("Thread", f"{thread_name} ({thread_id})"),
                            ("Status", str(e.status)),
                            ("Error", str(e)),
                        ])
                        failed_count += 1

                except Exception as e:
                    logger.error("Error Processing Debate For Deletion", [
                        ("Debate", str(debate)),
                        ("Error", str(e)),
                    ])
                    failed_count += 1

            # Summary log
            if deleted_count > 0 or failed_count > 0:
                logger.tree("Closed Debate Deletion Complete", [
                    ("Deleted", str(deleted_count)),
                    ("Failed", str(failed_count)),
                    ("Total Processed", str(len(debates_to_delete))),
                ], emoji="✅" if failed_count == 0 else "⚠️")

        except Exception as e:
            logger.error("Error In Closed Debate Delete Check", [
                ("Error", str(e)),
            ])
            # Send to webhook for critical scheduler errors
            try:
                if hasattr(self.bot, 'webhook_alerts') and self.bot.webhook_alerts:
                    await self.bot.webhook_alerts.send_error_alert(
                        "Closed Debate Delete Scheduler Error",
                        str(e)
                    )
            except Exception:
                pass  # Don't fail on webhook error

    async def _check_approved_appeal(self, thread_id: int, owner_id: int) -> bool:
        """
        Check if there's an approved appeal for this thread closure.

        Args:
            thread_id: The thread ID
            owner_id: The debate owner's user ID

        Returns:
            True if an approved appeal exists
        """
        if not owner_id:
            return False

        try:
            db = self.bot.debates_service.db

            # Check appeals table for approved appeal with action_type='close' and action_id=thread_id
            def check_appeal():
                with db._lock:
                    conn = db._get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        """SELECT 1 FROM appeals
                           WHERE user_id = ? AND action_type = 'close' AND action_id = ?
                           AND status = 'approved' LIMIT 1""",
                        (owner_id, thread_id)
                    )
                    return cursor.fetchone() is not None

            return await asyncio.to_thread(check_appeal)

        except Exception as e:
            logger.warning("Failed To Check Appeal Status", [
                ("Thread ID", str(thread_id)),
                ("Owner ID", str(owner_id)),
                ("Error", str(e)),
            ])
            # Fail-safe: don't delete if we can't verify appeal status
            return True

    @_check_debates_for_deletion.before_loop
    async def _before_check(self) -> None:
        """Wait until the bot is ready before starting."""
        await self.bot.wait_until_ready()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ClosedDebateDeleteScheduler"]
