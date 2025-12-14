"""
Othman Discord Bot - Debate Numbering Reconciliation Scheduler
===============================================================

Nightly scheduled debate numbering reconciliation at 00:15 NY_TZ.
Scans all non-deprecated debates and fixes any gaps in numbering.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable, Optional

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, SECONDS_PER_HOUR, NY_TZ
from src.utils import edit_thread_with_retry

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

    logger.info("🔢 Starting Numbering Reconciliation Scan")

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            logger.warning("Debates Forum Not Found For Numbering Reconciliation")
            return stats

        logger.info("📂 Scanning Debates Forum", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
            ("Total Threads", str(len(debates_forum.threads))),
        ])

        # Collect all non-deprecated debate threads with their numbers
        debate_threads: list[tuple[int, "discord.Thread"]] = []
        deprecated_count = 0

        for thread in debates_forum.threads:
            if thread.name.startswith("[DEPRECATED]"):
                deprecated_count += 1
                continue

            debate_num = _extract_debate_number(thread.name)
            if debate_num is not None:
                debate_threads.append((debate_num, thread))
                stats["threads_scanned"] += 1

        if not debate_threads:
            logger.info("No Debate Threads Found For Numbering Reconciliation")
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
                    ("Thread", thread.name[:40]),
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

        # Fix the gaps by renumbering
        for thread, old_num, new_num in threads_to_rename:
            try:
                # Extract title part after the number
                title_match = re.match(r'^\d+\s*\|\s*(.+)$', thread.name)
                if title_match:
                    title = title_match.group(1)
                    new_name = f"{new_num} | {title}"

                    await edit_thread_with_retry(thread, name=new_name)
                    stats["threads_renumbered"] += 1

                    logger.success("✅ Renumbered Debate Thread", [
                        ("Old", f"#{old_num}"),
                        ("New", f"#{new_num}"),
                        ("Title", title[:40]),
                    ])

                    # Rate limit protection (retry helper already handles some delay)
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error("Failed To Renumber Thread", [
                    ("Thread", thread.name[:30]),
                    ("Error", str(e)),
                ])
                stats["errors"] += 1

        # Update the counter file to match the highest number
        if debate_threads:
            highest_num = len(debate_threads) - stats["errors"]
            await _update_counter(highest_num)

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


async def _update_counter(new_value: int) -> None:
    """Update the debate counter file."""
    counter_file = Path("data/debate_counter.json")
    try:
        counter_file.parent.mkdir(exist_ok=True)
        with open(counter_file, "w") as f:
            json.dump({"count": new_value}, f)  # Use "count" to match debates.py
        logger.info("Updated Debate Counter", [
            ("Value", str(new_value)),
        ])
    except Exception as e:
        logger.error("Failed To Update Debate Counter", [
            ("Error", str(e)),
        ])


# =============================================================================
# Numbering Reconciliation Scheduler
# =============================================================================

class NumberingReconciliationScheduler:
    """
    Scheduler for nightly debate numbering reconciliation.

    Runs at 00:00 NY_TZ every night to ensure debate numbers are sequential.
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

        # Schedule time: 00:15 NY_TZ (15 minutes after midnight)
        self.schedule_hour = 0
        self.schedule_minute = 15

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Numbering reconciliation scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Numbering Reconciliation Scheduler Started", [
            ("Schedule", "nightly at 00:15 NY_TZ"),
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
        logger.info("Numbering reconciliation scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
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
                    logger.info("Starting nightly numbering reconciliation...")
                    try:
                        stats = await self.callback()
                        logger.success("Nightly Numbering Reconciliation Complete", [
                            ("Gaps Fixed", str(stats.get('threads_renumbered', 0))),
                        ])
                    except Exception as e:
                        logger.error("Nightly Numbering Reconciliation Failed", [
                            ("Error Type", type(e).__name__),
                            ("Error", str(e)),
                        ])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error In Numbering Reconciliation Scheduler", [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)),
                ])
                # Wait 1 hour before retrying on error
                await asyncio.sleep(SECONDS_PER_HOUR)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["NumberingReconciliationScheduler", "reconcile_debate_numbering"]
