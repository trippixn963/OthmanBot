"""
OthmanBot - Debate Stats Backfill & Reconciliation
==================================================

One-time backfill and nightly reconciliation for debate_participation
and debate_creators tables.

- backfill_debate_stats: One-time initial population (skips if data exists)
- reconcile_debate_stats: Nightly full rescan for accuracy
- StatsReconciliationScheduler: Runs reconciliation at 00:30 EST

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, Awaitable

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, SECONDS_PER_HOUR, NY_TZ, DISCORD_API_DELAY, LOG_TITLE_PREVIEW_LENGTH, LOG_ERROR_MESSAGE_LENGTH

if TYPE_CHECKING:
    from src.bot import OthmanBot




async def backfill_debate_stats(bot: "OthmanBot") -> dict:
    """
    Backfill debate participation and creator stats from existing threads.

    Scans all non-deprecated debate threads and:
    1. Counts messages per user per thread -> debate_participation table
    2. Records thread owner -> debate_creators table

    Args:
        bot: The OthmanBot instance

    Returns:
        Dict with backfill stats
    """
    stats = {
        "threads_scanned": 0,
        "messages_counted": 0,
        "creators_recorded": 0,
        "users_tracked": 0,
        "errors": 0,
    }

    # Check if backfill has already been done
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        logger.warning("Debates Service Not Available For Backfill", [
            ("Action", "Skipping backfill"),
        ])
        return stats

    # Check if tables already have data
    existing_participants = bot.debates_service.db.get_most_active_participants(1)
    existing_creators = bot.debates_service.db.get_top_debate_starters(1)

    if existing_participants or existing_creators:
        logger.info("📊 Backfill Skipped - Tables Already Have Data", [
            ("Participants", str(len(existing_participants))),
            ("Creators", str(len(existing_creators))),
        ])
        return stats

    logger.info("📊 Starting Debate Stats Backfill", [
        ("Forum ID", str(DEBATES_FORUM_ID)),
    ])

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            logger.warning("Debates Forum Not Found For Backfill", [
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])
            return stats

        # Collect all threads (active + archived)
        all_threads = list(debates_forum.threads)
        async for archived_thread in debates_forum.archived_threads(limit=100):
            all_threads.append(archived_thread)

        logger.info("📂 Scanning Threads For Backfill", [
            ("Total Threads", str(len(all_threads))),
        ])

        unique_users = set()

        for thread in all_threads:
            # Skip deprecated threads
            if thread.name.startswith("[DEPRECATED]"):
                continue

            stats["threads_scanned"] += 1

            try:
                # Record thread creator (skip if owner is the bot itself)
                if thread.owner_id and thread.owner_id != bot.user.id:
                    bot.debates_service.db.set_debate_creator(thread.id, thread.owner_id)
                    stats["creators_recorded"] += 1
                    unique_users.add(thread.owner_id)

                # Count messages per user in this thread
                message_counts: dict[int, int] = {}

                async for message in thread.history(limit=1000):
                    # Skip bot messages
                    if message.author.bot:
                        continue

                    user_id = message.author.id
                    message_counts[user_id] = message_counts.get(user_id, 0) + 1
                    stats["messages_counted"] += 1
                    unique_users.add(user_id)

                # Batch insert participation counts
                for user_id, count in message_counts.items():
                    # Use direct SQL for bulk insert
                    bot.debates_service.db.bulk_set_participation(
                        thread.id, user_id, count
                    )

                logger.debug("📊 Thread Scanned", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Messages", str(sum(message_counts.values()))),
                    ("Users", str(len(message_counts))),
                ])

                # Rate limit protection
                await asyncio.sleep(DISCORD_API_DELAY)

            except discord.HTTPException as e:
                logger.warning("📊 Error Scanning Thread", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Error", str(e)[:LOG_ERROR_MESSAGE_LENGTH]),
                ])
                stats["errors"] += 1
                continue

        stats["users_tracked"] = len(unique_users)

        logger.success("📊 Debate Stats Backfill Complete", [
            ("Threads Scanned", str(stats["threads_scanned"])),
            ("Messages Counted", str(stats["messages_counted"])),
            ("Creators Recorded", str(stats["creators_recorded"])),
            ("Unique Users", str(stats["users_tracked"])),
            ("Errors", str(stats["errors"])),
        ])

    except Exception as e:
        logger.error("📊 Backfill Failed", [
            ("Error", str(e)),
        ])
        stats["errors"] += 1

    return stats


# =============================================================================
# Nightly Stats Reconciliation
# =============================================================================

async def reconcile_debate_stats(bot: "OthmanBot") -> dict:
    """
    Nightly reconciliation of debate participation and creator stats.

    Unlike backfill_debate_stats, this always runs (doesn't skip if data exists).
    Performs a full rescan to ensure accuracy.

    Args:
        bot: The OthmanBot instance

    Returns:
        Dict with reconciliation stats
    """
    stats = {
        "threads_scanned": 0,
        "messages_counted": 0,
        "creators_recorded": 0,
        "users_tracked": 0,
        "errors": 0,
    }

    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        logger.warning("Debates Service Not Available For Stats Reconciliation", [
            ("Action", "Skipping reconciliation"),
        ])
        return stats

    logger.info("📊 Starting Nightly Stats Reconciliation", [
        ("Forum ID", str(DEBATES_FORUM_ID)),
    ])

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            logger.warning("Debates Forum Not Found For Stats Reconciliation", [
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])
            return stats

        # Collect all threads (active + archived)
        all_threads = list(debates_forum.threads)
        async for archived_thread in debates_forum.archived_threads(limit=100):
            all_threads.append(archived_thread)

        logger.info("📂 Scanning Threads For Stats Reconciliation", [
            ("Total Threads", str(len(all_threads))),
        ])

        unique_users = set()

        for thread in all_threads:
            # Skip deprecated threads
            if thread.name.startswith("[DEPRECATED]"):
                continue

            stats["threads_scanned"] += 1

            try:
                # Record thread creator (skip if owner is the bot itself)
                if thread.owner_id and thread.owner_id != bot.user.id:
                    bot.debates_service.db.set_debate_creator(thread.id, thread.owner_id)
                    stats["creators_recorded"] += 1
                    unique_users.add(thread.owner_id)

                # Count messages per user in this thread
                message_counts: dict[int, int] = {}

                async for message in thread.history(limit=1000):
                    # Skip bot messages
                    if message.author.bot:
                        continue

                    user_id = message.author.id
                    message_counts[user_id] = message_counts.get(user_id, 0) + 1
                    stats["messages_counted"] += 1
                    unique_users.add(user_id)

                # Update participation counts (overwrites existing data)
                for user_id, count in message_counts.items():
                    bot.debates_service.db.bulk_set_participation(
                        thread.id, user_id, count
                    )

                # Rate limit protection
                await asyncio.sleep(DISCORD_API_DELAY)

            except discord.HTTPException as e:
                logger.warning("📊 Error Scanning Thread", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                    ("Error", str(e)[:LOG_ERROR_MESSAGE_LENGTH]),
                ])
                stats["errors"] += 1
                continue

        stats["users_tracked"] = len(unique_users)

        logger.success("📊 Nightly Stats Reconciliation Complete", [
            ("Threads Scanned", str(stats["threads_scanned"])),
            ("Messages Counted", str(stats["messages_counted"])),
            ("Creators Recorded", str(stats["creators_recorded"])),
            ("Unique Users", str(stats["users_tracked"])),
            ("Errors", str(stats["errors"])),
        ])

    except Exception as e:
        logger.error("📊 Stats Reconciliation Failed", [
            ("Error", str(e)),
        ])
        stats["errors"] += 1

    return stats


# =============================================================================
# Stats Reconciliation Scheduler
# =============================================================================

class StatsReconciliationScheduler:
    """
    Scheduler for nightly debate stats reconciliation.

    Runs at 00:30 EST every night to ensure leaderboard accuracy.
    """

    def __init__(self, callback: Callable[[], Awaitable[dict]]) -> None:
        """
        Initialize scheduler.

        Args:
            callback: Async function to call for reconciliation (returns stats dict)
        """
        self.callback = callback
        self._task: asyncio.Task | None = None
        self._running = False

        # Schedule time: 00:50 EST
        self.schedule_hour = 0
        self.schedule_minute = 50

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle exceptions from the scheduler task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.tree("Stats Reconciliation Scheduler Task Exception", [
                ("Error Type", type(exc).__name__),
                ("Error", str(exc)[:100]),
            ], emoji="❌")

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Stats Reconciliation Scheduler Already Running", [
                ("Action", "Skipping start"),
            ])
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        self._task.add_done_callback(self._handle_task_exception)
        logger.info("Stats Reconciliation Scheduler Started", [
            ("Schedule", "nightly at 00:30 EST"),
        ])

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Stats Reconciliation Scheduler Stopped", [
            ("Status", "Task cancelled"),
        ])

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                # Calculate time until next 00:30 EST
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

                logger.info("Next Stats Reconciliation Scheduled", [
                    ("Time", target_time.strftime('%Y-%m-%d %H:%M %Z')),
                    ("Wait", f"{wait_seconds / 3600:.1f} hours"),
                ])

                # Wait until target time
                await asyncio.sleep(wait_seconds)

                # Run reconciliation
                if self._running:
                    logger.info("Starting Nightly Stats Reconciliation", [
                        ("Mode", "Full scan"),
                    ])
                    try:
                        stats = await self.callback()
                        logger.success("Nightly Stats Reconciliation Complete", [
                            ("Threads", str(stats.get('threads_scanned', 0))),
                            ("Messages", str(stats.get('messages_counted', 0))),
                        ])
                    except Exception as e:
                        logger.error("Nightly Stats Reconciliation Failed", [
                            ("Error", str(e)),
                        ])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error In Stats Reconciliation Scheduler", [
                    ("Error", str(e)),
                ])
                # Wait 1 hour before retrying on error
                await asyncio.sleep(SECONDS_PER_HOUR)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "backfill_debate_stats",
    "reconcile_debate_stats",
    "StatsReconciliationScheduler",
]
