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
            return await asyncio.to_thread(bot.debates_service.db.get_next_debate_number)
        else:
            logger.warning("🔢 Debates Service Not Available", [
                ("Action", "Using timestamp-based fallback"),
            ])
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
                    await asyncio.to_thread(bot.debates_service.db.set_debate_counter, max_number)
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

    # Get thread owner info
    owner_name = "Unknown"
    owner_id = None
    if thread.owner:
        owner_name = f"{thread.owner.name} ({thread.owner.display_name})"
        owner_id = thread.owner_id
    elif thread.owner_id:
        owner_name = "Not in cache"
        owner_id = thread.owner_id

    # Get thread age
    thread_age = "Unknown"
    if thread.created_at:
        from datetime import datetime, timezone
        age_delta = datetime.now(timezone.utc) - thread.created_at
        if age_delta.days > 0:
            thread_age = f"{age_delta.days}d {age_delta.seconds // 3600}h"
        else:
            thread_age = f"{age_delta.seconds // 3600}h {(age_delta.seconds % 3600) // 60}m"

    log_fields = [
        ("Number", f"#{deleted_number}"),
        ("Thread", thread.name),
        ("Thread ID", str(thread.id)),
        ("Owner", owner_name),
    ]
    if owner_id:
        log_fields.append(("ID", str(owner_id)))
    log_fields.extend([
        ("Thread Age", thread_age),
        ("Was Archived", str(thread.archived)),
        ("Was Locked", str(thread.locked)),
        ("Member Count", str(thread.member_count) if thread.member_count else "Unknown"),
        ("Message Count", str(thread.message_count) if thread.message_count else "Unknown"),
    ])

    logger.warning("🗑️ Debate Thread Deleted", log_fields)

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
# Starter Message Delete Handler
# =============================================================================

async def on_message_delete_handler(
    bot: "OthmanBot",
    payload: discord.RawMessageDeleteEvent
) -> None:
    """
    Handle when any message in a debate thread is deleted.

    Cleans up votes for the deleted message and updates karma accordingly.

    Args:
        bot: The OthmanBot instance
        payload: Raw message delete event payload
    """
    # Check if this is in the debates forum
    channel = bot.get_channel(payload.channel_id)
    if not channel:
        logger.debug("Message Delete Handler Skipped (Channel Not Found)", [
            ("Channel ID", str(payload.channel_id)),
            ("Message ID", str(payload.message_id)),
        ])
        return

    # Check if channel is a thread in the debates forum
    if not isinstance(channel, discord.Thread):
        # Not a thread - skip silently (normal for non-thread channels)
        return

    if channel.parent_id != DEBATES_FORUM_ID:
        # Not in debates forum - skip silently (normal for other forums)
        return

    # Clean up votes for this message
    if hasattr(bot, 'debates_service') and bot.debates_service is not None:
        try:
            db = bot.debates_service.db
            # Check if message had any votes
            votes = db.get_message_votes(payload.message_id)
            if votes:
                # Clean up orphaned votes for this specific message
                result = db.cleanup_orphaned_votes({payload.message_id})
                if result.get("votes_deleted", 0) > 0:
                    logger.tree("Cleaned Up Votes For Deleted Message", [
                        ("Message ID", str(payload.message_id)),
                        ("Votes Removed", str(result["votes_deleted"])),
                        ("Karma Reversed", str(result["karma_reversed"])),
                    ], emoji="🧹")
        except Exception as e:
            logger.warning("Failed To Cleanup Votes For Deleted Message", [
                ("Message ID", str(payload.message_id)),
                ("Error", str(e)[:50]),
            ])


async def on_starter_message_delete_handler(
    bot: "OthmanBot",
    payload: discord.RawMessageDeleteEvent
) -> None:
    """
    Handle when a thread's starter message is deleted.

    When the original post of a debate thread is deleted, automatically
    delete the orphaned thread since there's nothing left to debate.

    Args:
        bot: The OthmanBot instance
        payload: Raw message delete event payload
    """
    # First, handle vote cleanup for any deleted message
    await on_message_delete_handler(bot, payload)

    # Check if this is in the debates forum
    channel = bot.get_channel(payload.channel_id)
    if not channel:
        # Channel not in cache - already logged by on_message_delete_handler
        return

    # Check if channel is a thread in the debates forum
    if not isinstance(channel, discord.Thread):
        # Not a thread - normal for non-thread channels
        return

    if channel.parent_id != DEBATES_FORUM_ID:
        # Not in debates forum - normal for other forums
        return

    # Check if the deleted message was the starter message
    # For threads, the starter message ID equals the thread ID
    if payload.message_id != channel.id:
        # Not the starter message - just a regular reply deletion (already handled above)
        return

    # Skip closed/deprecated threads
    if channel.name.startswith("[CLOSED]") or channel.name.startswith("[DEPRECATED]"):
        logger.debug("Starter Deleted In Closed Thread (Skipping)", [
            ("Thread", channel.name[:50]),
            ("Thread ID", str(channel.id)),
        ])
        return

    # This is an orphaned thread - the starter message was deleted
    thread_name = channel.name
    thread_id = channel.id

    # Get thread owner info
    owner_name = "Unknown"
    owner_id = None
    if channel.owner:
        owner_name = f"{channel.owner.name} ({channel.owner.display_name})"
        owner_id = channel.owner_id
    elif channel.owner_id:
        owner_name = "Not in cache"
        owner_id = channel.owner_id

    # Get thread age
    thread_age = "Unknown"
    if channel.created_at:
        from datetime import datetime, timezone
        age_delta = datetime.now(timezone.utc) - channel.created_at
        if age_delta.days > 0:
            thread_age = f"{age_delta.days}d {age_delta.seconds // 3600}h"
        else:
            thread_age = f"{age_delta.seconds // 3600}h {(age_delta.seconds % 3600) // 60}m"

    # Extract debate number
    debate_number = extract_debate_number(thread_name)

    log_fields = [
        ("Number", f"#{debate_number}" if debate_number else "Unnumbered"),
        ("Thread", thread_name[:50]),
        ("Thread ID", str(thread_id)),
        ("Owner", owner_name),
    ]
    if owner_id:
        log_fields.append(("ID", str(owner_id)))
    log_fields.extend([
        ("Thread Age", thread_age),
        ("Reason", "Original post was deleted - thread is now orphaned"),
        ("Action", "Auto-deleting thread"),
    ])

    logger.tree("Starter Message Deleted - Deleting Orphaned Thread", log_fields, emoji="🗑️")

    try:
        # Delete the orphaned thread
        await channel.delete()
        logger.tree("Orphaned Thread Deleted", [
            ("Thread", thread_name[:50]),
            ("Thread ID", str(thread_id)),
        ], emoji="✅")

        # Clean up database records
        if hasattr(bot, 'debates_service') and bot.debates_service is not None:
            try:
                bot.debates_service.db.delete_thread_data(thread_id)
                logger.debug("Thread Database Records Cleaned", [
                    ("Thread ID", str(thread_id)),
                ])
            except Exception as db_err:
                logger.warning("Failed To Clean Thread Database", [
                    ("Thread ID", str(thread_id)),
                    ("Error", str(db_err)[:50]),
                ])

    except discord.Forbidden:
        logger.tree("Cannot Delete Orphaned Thread (No Permission)", [
            ("Thread", thread_name[:50]),
            ("Thread ID", str(thread_id)),
        ], emoji="🚫")
    except discord.NotFound:
        logger.debug("Orphaned Thread Already Deleted", [
            ("Thread", thread_name[:50]),
            ("Thread ID", str(thread_id)),
        ])
    except discord.HTTPException as e:
        log_http_error(e, "Delete Orphaned Thread", [
            ("Thread", thread_name[:50]),
            ("Thread ID", str(thread_id)),
        ])
    except Exception as e:
        logger.tree("Unexpected Error Deleting Orphaned Thread", [
            ("Thread", thread_name[:50]),
            ("Thread ID", str(thread_id)),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:80]),
        ], emoji="❌")


# =============================================================================
# Thread Update Handler (Archive Detection)
# =============================================================================

async def on_thread_update_handler(
    bot: "OthmanBot",
    before: discord.Thread,
    after: discord.Thread
) -> None:
    """
    Handle thread updates in the debates forum.

    Detects when threads are auto-archived by Discord and logs the event.
    Also triggers orphan vote cleanup for archived threads.

    Args:
        bot: The OthmanBot instance
        before: Thread state before the update
        after: Thread state after the update
    """
    # Only handle debates forum threads
    if after.parent_id != DEBATES_FORUM_ID:
        return

    # Detect archive state change (was active, now archived)
    if not before.archived and after.archived:
        # Check if this was auto-archived (not manually via stale manager or close)
        # Stale manager adds [STALE] prefix, close adds [CLOSED] prefix
        is_manual_archive = (
            after.name.startswith("[STALE]") or
            after.name.startswith("[CLOSED]") or
            after.name.startswith("[DEPRECATED]")
        )

        if is_manual_archive:
            logger.debug("Thread Archive Detected (Manual)", [
                ("Thread", after.name[:50]),
                ("Thread ID", str(after.id)),
            ])
        else:
            logger.tree("Thread Auto-Archived By Discord", [
                ("Thread", after.name[:50]),
                ("Thread ID", str(after.id)),
                ("Reason", "Inactivity timeout"),
            ], emoji="📦")

    # Detect unarchive (thread restored)
    if before.archived and not after.archived:
        logger.tree("Thread Unarchived", [
            ("Thread", after.name[:50]),
            ("Thread ID", str(after.id)),
        ], emoji="📂")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "get_next_debate_number",
    "extract_debate_number",
    "renumber_debates_after_deletion",
    "on_thread_delete_handler",
    "on_starter_message_delete_handler",
    "on_message_delete_handler",
    "on_thread_update_handler",
]
