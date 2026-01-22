"""
OthmanBot - Debate Numbering Reconciliation Scheduler
=====================================================

Nightly scheduled debate numbering reconciliation at 00:15 NY_TZ.
Scans all non-deprecated debates and fixes any gaps in numbering.

Also runs hourly checks for unnumbered threads (missed during bot downtime).

Features rate limit awareness with automatic backoff.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Awaitable, Optional, Any

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, SECONDS_PER_HOUR, NY_TZ, DISCORD_API_DELAY, LOG_TITLE_PREVIEW_LENGTH, THREAD_NAME_PREVIEW_LENGTH
from src.core.emojis import UPVOTE_EMOJI, PARTICIPATE_EMOJI
from src.utils import edit_thread_with_retry, add_reactions_with_delay, send_message_with_retry
from src.utils.discord_rate_limit import log_http_error
from src.services.debates.analytics import calculate_debate_analytics, generate_analytics_embed

# Rate limit backoff settings
RATE_LIMIT_BASE_DELAY = 5.0  # Base delay when rate limited (seconds)
RATE_LIMIT_MAX_DELAY = 60.0  # Maximum backoff delay (seconds)

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Debate Numbering Reconciliation
# =============================================================================

async def reconcile_debate_numbering(bot: "OthmanBot") -> dict:
    """
    Scan all non-deprecated debates and fix any gaps in numbering.

    Args:
        bot: The OthmanBot instance

    Returns:
        Dict with reconciliation stats
    """
    stats = {
        "threads_scanned": 0,
        "gaps_found": 0,
        "threads_renumbered": 0,
        "errors": 0,
    }

    logger.info("🔢 Starting Numbering Reconciliation Scan", [
        ("Forum ID", str(DEBATES_FORUM_ID)),
    ])

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            logger.warning("Debates Forum Not Found For Numbering Reconciliation", [
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])
            return stats

        logger.info("📂 Scanning Debates Forum", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
            ("Total Threads", str(len(debates_forum.threads))),
        ])

        # Collect all non-deprecated debate threads with their numbers
        debate_threads: list[tuple[int, "discord.Thread"]] = []
        deprecated_count = 0

        # Get Open Discussion thread ID to skip it
        open_discussion_thread_id = None
        if hasattr(bot, 'open_discussion') and bot.open_discussion:
            open_discussion_thread_id = bot.open_discussion.get_thread_id()

        for thread in debates_forum.threads:
            # Skip deprecated threads
            if thread.name.startswith("[DEPRECATED]"):
                deprecated_count += 1
                continue

            # Skip Open Discussion thread (no numbering)
            if open_discussion_thread_id and thread.id == open_discussion_thread_id:
                continue

            debate_num = _extract_debate_number(thread.name)
            if debate_num is not None:
                debate_threads.append((debate_num, thread))
                stats["threads_scanned"] += 1

        if not debate_threads:
            logger.info("No Debate Threads Found For Numbering Reconciliation", [
                ("Action", "Skipping reconciliation"),
            ])
            return stats

        # Sort by debate number
        debate_threads.sort(key=lambda x: x[0])

        # Log the current state
        numbers_found = [num for num, _ in debate_threads]
        logger.info("📊 Debate Threads Found", [
            ("Active Threads", str(len(debate_threads))),
            ("Deprecated", str(deprecated_count)),
            ("Number Range", f"#{numbers_found[0]} - #{numbers_found[-1]}" if numbers_found else "N/A"),
        ])

        # Check for gaps and fix them
        expected_num = 1
        threads_to_rename = []

        for current_num, thread in debate_threads:
            if current_num != expected_num:
                # Gap found - this thread needs renumbering
                stats["gaps_found"] += 1
                threads_to_rename.append((thread, current_num, expected_num))
                logger.info("🔍 Gap Detected", [
                    ("Current", f"#{current_num}"),
                    ("Expected", f"#{expected_num}"),
                    ("Thread", thread.name[:THREAD_NAME_PREVIEW_LENGTH]),
                ])
            expected_num += 1

        if not threads_to_rename:
            logger.success("✅ Numbering Reconciliation Complete - No Gaps Found", [
                ("Threads Scanned", str(stats["threads_scanned"])),
                ("All Sequential", "Yes"),
            ])
            return stats

        logger.info("🔧 Starting Gap Repair", [
            ("Gaps Found", str(len(threads_to_rename))),
            ("Threads To Renumber", str(len(threads_to_rename))),
        ])

        # Fix the gaps by renumbering (with adaptive rate limit handling)
        adaptive_delay = DISCORD_API_DELAY
        consecutive_rate_limits = 0

        for thread, old_num, new_num in threads_to_rename:
            try:
                # Extract title part after the number
                title_match = re.match(r'^\d+\s*\|\s*(.+)$', thread.name)
                if title_match:
                    title = title_match.group(1)
                    new_name = f"{new_num} | {title}"

                    success = await edit_thread_with_retry(thread, name=new_name)

                    if success:
                        stats["threads_renumbered"] += 1
                        # Success - gradually reduce delay
                        consecutive_rate_limits = max(0, consecutive_rate_limits - 1)
                        adaptive_delay = max(DISCORD_API_DELAY, adaptive_delay * 0.9)

                        logger.success("✅ Renumbered Debate Thread", [
                            ("Old", f"#{old_num}"),
                            ("New", f"#{new_num}"),
                            ("Title", title[:THREAD_NAME_PREVIEW_LENGTH]),
                        ])
                    else:
                        # edit_thread_with_retry returned False (exhausted retries)
                        stats["errors"] += 1
                        consecutive_rate_limits += 1
                        adaptive_delay = min(adaptive_delay * 1.5, RATE_LIMIT_MAX_DELAY)
                        logger.warning("Thread Renumber Failed After Retries", [
                            ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                            ("Adaptive Delay", f"{adaptive_delay:.1f}s"),
                        ])

                    # Use adaptive delay between operations
                    await asyncio.sleep(adaptive_delay)

            except discord.HTTPException as e:
                if e.status == 429:
                    # Rate limited - back off significantly
                    retry_after = getattr(e, 'retry_after', RATE_LIMIT_BASE_DELAY)
                    consecutive_rate_limits += 1
                    adaptive_delay = min(adaptive_delay * 2, RATE_LIMIT_MAX_DELAY)
                    logger.warning("Renumbering Rate Limited", [
                        ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                        ("Retry After", f"{retry_after:.1f}s"),
                        ("Consecutive Limits", str(consecutive_rate_limits)),
                    ])
                    await asyncio.sleep(retry_after + 2.0)
                else:
                    log_http_error(e, "Renumber Thread", [
                        ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                        ("Old Number", f"#{old_num}"),
                        ("New Number", f"#{new_num}"),
                    ])
                stats["errors"] += 1
            except Exception as e:
                logger.error("Failed To Renumber Thread", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Error", str(e)),
                ])
                stats["errors"] += 1

        # Update the counter in database to match the highest number
        highest_num = 0
        if debate_threads:
            highest_num = len(debate_threads) - stats["errors"]
            if hasattr(bot, 'debates_service') and bot.debates_service is not None:
                await asyncio.to_thread(bot.debates_service.db.set_debate_counter, highest_num)

        logger.success("🎉 Numbering Reconciliation Complete", [
            ("Threads Scanned", str(stats["threads_scanned"])),
            ("Gaps Found", str(stats["gaps_found"])),
            ("Threads Renumbered", str(stats["threads_renumbered"])),
            ("Errors", str(stats["errors"])),
            ("Final Counter", str(highest_num)),
        ])

    except Exception as e:
        logger.error("Failed To Reconcile Debate Numbering", [
            ("Error", str(e)),
        ])
        stats["errors"] += 1

    return stats


def _extract_debate_number(thread_name: str) -> Optional[int]:
    """
    Extract the debate number from a thread name.

    Args:
        thread_name: Thread name like "5 | Best football player?"

    Returns:
        The debate number or None if not found
    """
    match = re.match(r'^(\d+)\s*\|', thread_name)
    if match:
        return int(match.group(1))
    return None


def _has_number_prefix(thread_name: str) -> bool:
    """Check if thread name has a debate number prefix."""
    return bool(re.match(r'^\d+\s*\|\s*', thread_name))


# =============================================================================
# Unnumbered Thread Check (Hourly)
# =============================================================================

async def check_unnumbered_threads(bot: "OthmanBot") -> dict:
    """
    Find and number any threads that missed auto-numbering.

    This catches threads created during bot downtime/restarts.

    Args:
        bot: The OthmanBot instance

    Returns:
        Dict with stats
    """
    stats = {
        "threads_checked": 0,
        "threads_numbered": 0,
        "errors": 0,
    }

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum or not isinstance(debates_forum, discord.ForumChannel):
            logger.debug("Unnumbered Check Skipped (Forum Not Found)", [])
            return stats

        # Get Open Discussion thread ID to skip
        open_discussion_id = None
        if hasattr(bot, 'debates_service') and bot.debates_service:
            open_discussion_id = await asyncio.to_thread(bot.debates_service.db.get_open_discussion_thread_id)

        unnumbered_threads = []

        # Find unnumbered threads
        for thread in debates_forum.threads:
            if thread is None or thread.archived:
                continue

            stats["threads_checked"] += 1

            # Skip Open Discussion
            if open_discussion_id and thread.id == open_discussion_id:
                continue

            # Skip closed/deprecated/stale threads
            if any(thread.name.startswith(prefix) for prefix in ["[CLOSED]", "[DEPRECATED]", "[STALE]"]):
                continue

            # Check if thread has a number prefix
            if not _has_number_prefix(thread.name):
                unnumbered_threads.append(thread)

        if not unnumbered_threads:
            logger.debug("Unnumbered Thread Check Complete (None Found)", [
                ("Checked", str(stats["threads_checked"])),
            ])
            return stats

        logger.tree("Found Unnumbered Threads", [
            ("Count", str(len(unnumbered_threads))),
        ], emoji="🔢")

        # Number each unnumbered thread
        for thread in unnumbered_threads:
            try:
                success = await _number_single_thread(bot, thread)
                if success:
                    stats["threads_numbered"] += 1
                else:
                    stats["errors"] += 1
                await asyncio.sleep(DISCORD_API_DELAY)
            except Exception as e:
                stats["errors"] += 1
                logger.warning("Failed To Number Thread", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Error", str(e)[:50]),
                ])

        logger.tree("Unnumbered Thread Check Complete", [
            ("Checked", str(stats["threads_checked"])),
            ("Numbered", str(stats["threads_numbered"])),
            ("Errors", str(stats["errors"])),
        ], emoji="🔢")

    except Exception as e:
        logger.warning("Unnumbered Thread Check Failed", [
            ("Error", str(e)[:80]),
        ])
        stats["errors"] += 1

    return stats


async def _number_single_thread(bot: "OthmanBot", thread: discord.Thread) -> bool:
    """
    Assign a debate number to a single unnumbered thread.

    Args:
        bot: The OthmanBot instance
        thread: The thread to number

    Returns:
        True if successful
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return False

    db = bot.debates_service.db

    try:
        # Get next debate number
        debate_number = await asyncio.to_thread(db.get_next_debate_number)

        # Build new name
        original_name = thread.name
        new_name = f"{debate_number} | {original_name}"
        if len(new_name) > 100:
            new_name = new_name[:97] + "..."

        # Rename thread
        rename_success = await edit_thread_with_retry(thread, name=new_name)
        if not rename_success:
            logger.warning("Failed To Rename Unnumbered Thread", [
                ("Thread", original_name[:LOG_TITLE_PREVIEW_LENGTH]),
            ])
            return False

        logger.tree("Thread Numbered (Hourly Check)", [
            ("Number", f"#{debate_number}"),
            ("Thread", original_name[:LOG_TITLE_PREVIEW_LENGTH]),
            ("Thread ID", str(thread.id)),
        ], emoji="🔢")

        # Add upvote reaction to starter message if missing
        try:
            starter_message = await thread.fetch_message(thread.id)
            if starter_message and not starter_message.author.bot:
                # Check if upvote already exists
                has_upvote = any(str(r.emoji) == UPVOTE_EMOJI for r in starter_message.reactions)
                if not has_upvote:
                    await starter_message.add_reaction(UPVOTE_EMOJI)

                # Track creator
                await db.set_debate_creator_async(thread.id, starter_message.author.id)
        except discord.NotFound:
            pass
        except Exception:
            pass

        # Add analytics embed if missing
        try:
            analytics_msg_id = await db.get_analytics_message_async(thread.id)
            if not analytics_msg_id:
                logger.info("Adding Missing Analytics Embed (Hourly Check)", [
                    ("Thread", thread.name[:THREAD_NAME_PREVIEW_LENGTH]),
                    ("Thread ID", str(thread.id)),
                    ("Reason", "No analytics_message_id in database"),
                ])
                analytics = await calculate_debate_analytics(thread, db)
                embed = await generate_analytics_embed(bot, analytics)
                analytics_message = await send_message_with_retry(thread, embed=embed)

                if analytics_message:
                    await add_reactions_with_delay(analytics_message, [PARTICIPATE_EMOJI])
                    try:
                        await analytics_message.pin()
                        await asyncio.sleep(DISCORD_API_DELAY)
                        async for msg in thread.history(limit=5):
                            if msg.type == discord.MessageType.pins_add:
                                await msg.delete()
                                break
                    except discord.HTTPException:
                        pass
                    await db.set_analytics_message_async(thread.id, analytics_message.id)
                    logger.debug("Analytics Embed Added And Stored", [
                        ("Thread ID", str(thread.id)),
                        ("Message ID", str(analytics_message.id)),
                    ])
        except Exception as e:
            logger.warning("Failed To Add Analytics Embed", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)[:50]),
            ])

        return True

    except Exception as e:
        logger.warning("Thread Numbering Failed", [
            ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
            ("Error", str(e)[:50]),
        ])
        return False


# =============================================================================
# Numbering Reconciliation Scheduler
# =============================================================================

class NumberingReconciliationScheduler:
    """
    Scheduler for debate numbering reconciliation.

    - Nightly at 00:15 NY_TZ: Full reconciliation (fix gaps in numbering)
    - Hourly: Check for unnumbered threads (catch threads created during downtime)
    """

    def __init__(
        self,
        callback: Callable[[], Awaitable[dict]],
        bot: Optional[Any] = None
    ) -> None:
        """
        Initialize scheduler.

        Args:
            callback: Async function to call for reconciliation (returns stats dict)
            bot: Optional bot reference for webhook alerts on errors
        """
        self.callback = callback
        self.bot = bot
        self._nightly_task: asyncio.Task | None = None
        self._hourly_task: asyncio.Task | None = None
        self._running = False

        # Schedule time: 00:35 EST
        self.schedule_hour = 0
        self.schedule_minute = 35

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle exceptions from the scheduler task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.tree("Numbering Scheduler Task Exception", [
                ("Error Type", type(exc).__name__),
                ("Error", str(exc)[:100]),
            ], emoji="❌")

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Numbering Reconciliation Scheduler Already Running", [
                ("Action", "Skipping start"),
            ])
            return

        self._running = True

        # Start nightly reconciliation task
        self._nightly_task = asyncio.create_task(self._nightly_scheduler_loop())
        self._nightly_task.add_done_callback(self._handle_task_exception)

        # Start hourly unnumbered check task
        self._hourly_task = asyncio.create_task(self._hourly_scheduler_loop())
        self._hourly_task.add_done_callback(self._handle_task_exception)

        logger.tree("Numbering Reconciliation Scheduler Started", [
            ("Nightly", "00:15 EST (full reconciliation)"),
            ("Hourly", "Every hour (unnumbered check)"),
        ], emoji="🔢")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False

        # Cancel nightly task
        if self._nightly_task:
            self._nightly_task.cancel()
            try:
                await self._nightly_task
            except asyncio.CancelledError:
                pass
            self._nightly_task = None

        # Cancel hourly task
        if self._hourly_task:
            self._hourly_task.cancel()
            try:
                await self._hourly_task
            except asyncio.CancelledError:
                pass
            self._hourly_task = None

        logger.tree("Numbering Reconciliation Scheduler Stopped", [], emoji="🔢")

    async def _nightly_scheduler_loop(self) -> None:
        """Nightly reconciliation scheduler loop (00:15 EST)."""
        while self._running:
            try:
                # Calculate time until next 00:00 NY_TZ
                now = datetime.now(NY_TZ)
                target_time = now.replace(
                    hour=self.schedule_hour,
                    minute=self.schedule_minute,
                    second=0,
                    microsecond=0
                )

                # If we've already passed today's target time, schedule for tomorrow
                if now >= target_time:
                    target_time += timedelta(days=1)

                wait_seconds = (target_time - now).total_seconds()

                logger.info("Next Numbering Reconciliation Scheduled", [
                    ("Time", target_time.strftime('%Y-%m-%d %H:%M %Z')),
                    ("Wait", f"{wait_seconds / 3600:.1f} hours"),
                ])

                # Wait until target time
                await asyncio.sleep(wait_seconds)

                # Run reconciliation
                if self._running:
                    logger.info("Starting Nightly Numbering Reconciliation", [
                        ("Mode", "Full scan"),
                    ])
                    try:
                        stats = await self.callback()
                        logger.success("Nightly Numbering Reconciliation Complete", [
                            ("Gaps Fixed", str(stats.get('threads_renumbered', 0))),
                        ])
                        # Log success to webhook
                        await self._send_reconciliation_webhook("Nightly (00:15 EST)", stats, success=True)
                    except Exception as e:
                        logger.error("Nightly Numbering Reconciliation Failed", [
                            ("Error Type", type(e).__name__),
                            ("Error", str(e)),
                        ])
                        # Send to webhook for reconciliation errors
                        await self._send_error_webhook("Numbering Reconciliation Failed", str(e))
                        await self._send_reconciliation_webhook("Nightly (00:15 EST)", {"error": str(e)}, success=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error In Numbering Reconciliation Scheduler", [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)),
                ])
                # Send to webhook for scheduler errors
                await self._send_error_webhook("Numbering Scheduler Error", str(e))
                # Wait 1 hour before retrying on error
                await asyncio.sleep(SECONDS_PER_HOUR)

    async def _hourly_scheduler_loop(self) -> None:
        """Hourly loop to check for unnumbered threads at the top of each hour EST."""
        while self._running:
            try:
                # Calculate time until next hour mark (e.g., 1:00, 2:00, 3:00 EST)
                now = datetime.now(NY_TZ)
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                wait_seconds = (next_hour - now).total_seconds()

                logger.debug("Hourly Unnumbered Check Scheduled", [
                    ("Next Run", next_hour.strftime("%H:%M EST")),
                    ("Wait", f"{wait_seconds / 60:.1f} min"),
                ])

                # Wait until the top of the next hour
                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                logger.debug("Starting Hourly Unnumbered Thread Check", [
                    ("Time", datetime.now(NY_TZ).strftime("%H:%M EST")),
                ])

                if self.bot:
                    try:
                        stats = await check_unnumbered_threads(self.bot)
                        if stats["threads_numbered"] > 0:
                            logger.tree("Hourly Unnumbered Check Complete", [
                                ("Threads Numbered", str(stats["threads_numbered"])),
                                ("Errors", str(stats["errors"])),
                            ], emoji="🔢")
                    except Exception as e:
                        logger.warning("Hourly Unnumbered Check Failed", [
                            ("Error", str(e)[:80]),
                        ])
                        await self._send_error_webhook("Hourly Unnumbered Check Failed", str(e))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Error In Hourly Scheduler Loop", [
                    ("Error", str(e)[:80]),
                ])
                # Wait 5 minutes before retrying on error
                await asyncio.sleep(300)

    async def _send_error_webhook(self, error_type: str, error_msg: str) -> None:
        """Send error to webhook if bot is available."""
        try:
            if self.bot and hasattr(self.bot, 'webhook_alerts') and self.bot.webhook_alerts:
                await self.bot.webhook_alerts.send_error_alert(error_type, error_msg)
        except Exception:
            pass  # Don't fail on webhook error

    async def _send_reconciliation_webhook(self, trigger: str, stats: dict, success: bool) -> None:
        """Send reconciliation results to webhook if bot is available."""
        # Logging now handled by tree logger automatically
        pass


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "NumberingReconciliationScheduler",
    "reconcile_debate_numbering",
    "check_unnumbered_threads",
]
