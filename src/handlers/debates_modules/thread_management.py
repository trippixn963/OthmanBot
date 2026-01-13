"""
OthmanBot - Debates Thread Management
=====================================

Thread numbering, renumbering, and deletion handling.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
from typing import Optional, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, DISCORD_API_DELAY
from src.utils import edit_thread_with_retry
from src.utils.discord_rate_limit import log_http_error

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Debate Number Utilities
# =============================================================================

async def get_next_debate_number(bot: "OthmanBot") -> int:
    """
    Get and increment the debate counter atomically.

    Uses database atomic increment to prevent race conditions when multiple
    threads are created simultaneously. Falls back to timestamp-based number
    if database is unavailable.

    Args:
        bot: The OthmanBot instance

    Returns:
        Next debate number (guaranteed unique)
    """
    try:
        if hasattr(bot, 'debates_service') and bot.debates_service is not None:
            return bot.debates_service.db.get_next_debate_number()
        else:
            logger.warning("🔢 Debates service not available - using fallback")
            import time
            return int(time.time()) % 100000
    except Exception as e:
        logger.error("🔢 Failed To Get Debate Number - Using Fallback", [
            ("Error", str(e)),
            ("Fallback", "Returning timestamp-based number to avoid duplicates"),
        ])
        import time
        return int(time.time()) % 100000


def extract_debate_number(thread_name: str) -> Optional[int]:
    """
    Extract debate number from thread name.

    Args:
        thread_name: Thread name in format "N | Title"

    Returns:
        Debate number or None if not numbered
    """
    parts = thread_name.split("|", 1)
    if len(parts) >= 1:
        try:
            return int(parts[0].strip())
        except ValueError:
            return None
    return None


# =============================================================================
# Thread Renumbering
# =============================================================================

async def renumber_debates_after_deletion(bot: "OthmanBot", deleted_number: int) -> int:
    """
    Renumber all debates with numbers higher than the deleted one.

    When debate #5 is deleted, debates 6, 7, 8... become 5, 6, 7...

    Args:
        bot: The OthmanBot instance
        deleted_number: The debate number that was deleted

    Returns:
        Number of threads renumbered
    """
    debates_forum = bot.get_channel(DEBATES_FORUM_ID)
    if not debates_forum or not isinstance(debates_forum, discord.ForumChannel):
        logger.warning("Debates forum not available for renumbering", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
            ("Type", type(debates_forum).__name__ if debates_forum else "None"),
        ])
        return 0

    renumbered_count = 0
    threads_to_renumber = []

    try:
        # Collect all threads (active + archived)
        all_threads = list(debates_forum.threads)
        async for archived_thread in debates_forum.archived_threads(limit=100):
            all_threads.append(archived_thread)

        # Find threads with numbers higher than deleted
        for thread in all_threads:
            thread_number = extract_debate_number(thread.name)
            if thread_number is not None and thread_number > deleted_number:
                threads_to_renumber.append((thread, thread_number))

        # Sort by number (ascending) to rename in order
        threads_to_renumber.sort(key=lambda x: x[1])

        # Track successfully renamed threads
        successfully_renamed = set()

        # Rename each thread
        for thread, old_number in threads_to_renumber:
            new_number = old_number - 1
            parts = thread.name.split("|", 1)
            if len(parts) == 2:
                title_part = parts[1].strip()
                new_name = f"{new_number} | {title_part}"
            else:
                new_name = thread.name.replace(str(old_number), str(new_number), 1)

            try:
                await edit_thread_with_retry(thread, name=new_name)
                renumbered_count += 1
                successfully_renamed.add(thread.id)
                logger.info("🔢 Debate Renumbered", [
                    ("Old Number", f"#{old_number}"),
                    ("New Number", f"#{new_number}"),
                    ("Thread", title_part if len(parts) == 2 else thread.name),
                    ("Thread ID", str(thread.id)),
                ])
                await asyncio.sleep(DISCORD_API_DELAY)
            except discord.HTTPException as e:
                log_http_error(e, "Renumber Debate", [
                    ("Thread", thread.name),
                    ("Old Number", f"#{old_number}"),
                    ("New Number", f"#{new_number}"),
                ])

        # Update the debate counter
        if threads_to_renumber:
            renumbered_ids = {
                t[0].id: t[1] for t in threads_to_renumber
                if t[0].id in successfully_renamed
            }

            max_number = 0
            for thread in all_threads:
                if thread.id in renumbered_ids:
                    max_number = max(max_number, renumbered_ids[thread.id] - 1)
                else:
                    num = extract_debate_number(thread.name)
                    if num is not None:
                        max_number = max(max_number, num)

            try:
                if hasattr(bot, 'debates_service') and bot.debates_service is not None:
                    bot.debates_service.db.set_debate_counter(max_number)
                logger.info("🔢 Debate Counter Updated", [
                    ("New Count", str(max_number)),
                    ("Renamed", str(len(successfully_renamed))),
                    ("Failed", str(len(threads_to_renumber) - len(successfully_renamed))),
                ])
            except Exception as e:
                logger.warning("🔢 Failed To Update Debate Counter", [
                    ("Error", str(e)),
                ])

    except discord.HTTPException as e:
        log_http_error(e, "Renumber Debates Batch", [
            ("Deleted Number", f"#{deleted_number}"),
            ("Renumbered So Far", str(renumbered_count)),
        ])

    return renumbered_count


# =============================================================================
# Thread Delete Handler
# =============================================================================

async def on_thread_delete_handler(bot: "OthmanBot", thread: discord.Thread) -> None:
    """
    Event handler for thread deletion in debates forum.

    Args:
        bot: The OthmanBot instance
        thread: The thread that was deleted

    DESIGN: When a debate thread is deleted:
    1. Extract the deleted debate's number
    2. Renumber all debates with higher numbers
    3. Update the debate counter
    """
    if thread.parent_id != DEBATES_FORUM_ID:
        return

    deleted_number = extract_debate_number(thread.name)

    if deleted_number is None:
        logger.debug("🗑️ Non-Numbered Debate Thread Deleted", [
            ("Thread", thread.name),
            ("Thread ID", str(thread.id)),
        ])
        return

    logger.warning("🗑️ Debate Thread Deleted", [
        ("Number", f"#{deleted_number}"),
        ("Thread", thread.name),
        ("Thread ID", str(thread.id)),
    ])

    # Clean up database records
    if hasattr(bot, 'debates_service') and bot.debates_service is not None:
        try:
            bot.debates_service.db.delete_thread_data(thread.id)
            logger.debug("🗄️ Thread Database Records Cleaned", [
                ("Thread ID", str(thread.id)),
            ])
        except sqlite3.Error as e:
            logger.warning("🗄️ Failed To Clean Thread Database", [
                ("Error", str(e)),
            ])

    # Renumber remaining debates
    renumbered = await renumber_debates_after_deletion(bot, deleted_number)

    if renumbered > 0:
        logger.success("🔢 Debate Renumbering Complete", [
            ("Deleted", f"#{deleted_number}"),
            ("Renumbered", str(renumbered)),
        ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "get_next_debate_number",
    "extract_debate_number",
    "renumber_debates_after_deletion",
    "on_thread_delete_handler",
]
