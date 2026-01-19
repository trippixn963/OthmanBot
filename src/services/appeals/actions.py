"""
OthmanBot - Appeals Actions
===========================

Action reversal logic for approved appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID
from src.utils import edit_thread_with_retry

if TYPE_CHECKING:
    from src.bot import OthmanBot


async def undo_action(
    bot: "OthmanBot",
    user_id: int,
    action_type: str,
    action_id: int,
    reviewed_by: Union[discord.User, discord.Member],
) -> bool:
    """
    Undo the moderation action.

    For disallow: Remove the ban
    For close: Reopen the thread

    Returns:
        True if successful, False otherwise
    """
    if action_type == "disallow":
        return await undo_disallow(bot, user_id, reviewed_by)
    elif action_type == "close":
        return await undo_close(bot, user_id, action_id, reviewed_by)
    else:
        logger.warning("Unknown action type for appeal undo", [
            ("Action Type", action_type),
        ])
        return False


async def undo_disallow(
    bot: "OthmanBot",
    user_id: int,
    reviewed_by: Union[discord.User, discord.Member],
) -> bool:
    """Remove debate ban for user."""
    db = bot.debates_service.db if bot.debates_service else None
    if not db:
        return False

    # Remove all bans for this user
    success = await asyncio.to_thread(db.remove_debate_ban, user_id, None)

    if success:
        logger.info("Appeal: Disallow Undone", [
            ("User ID", str(user_id)),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.display_name})"),
            ("ID", str(reviewed_by.id)),
        ])

        # Update ban_history to mark as removed via appeal
        try:
            await asyncio.to_thread(
                db.update_ban_history_removal,
                user_id,
                reviewed_by.id,
                "Appeal approved"
            )
        except Exception as e:
            logger.warning("Failed to update ban history for appeal", [
                ("User ID", str(user_id)),
                ("Error", str(e)),
            ])

        # Log to case thread
        try:
            if bot.case_log_service:
                member = None
                for guild in bot.guilds:
                    member = guild.get_member(user_id)
                    if member:
                        break

                await bot.case_log_service.log_unban(
                    user_id=user_id,
                    unbanned_by=reviewed_by,
                    scope="all debates",
                    display_name=member.display_name if member else f"User {user_id}",
                    reason="Appeal approved",
                )
        except Exception as e:
            logger.warning("Failed to log appeal unban to case system", [
                ("Error", str(e)),
            ])

    return success


async def undo_close(
    bot: "OthmanBot",
    user_id: int,
    thread_id: int,
    reviewed_by: Union[discord.User, discord.Member],
) -> bool:
    """Reopen a closed thread."""
    db = bot.debates_service.db if bot.debates_service else None

    # Find the thread
    thread: Optional[discord.Thread] = None

    for guild in bot.guilds:
        try:
            thread = guild.get_thread(thread_id)
            if not thread:
                thread = await guild.fetch_channel(thread_id)
        except (discord.NotFound, discord.Forbidden):
            continue

        if thread and isinstance(thread, discord.Thread):
            break

    if not thread:
        logger.warning("Appeal: Could not find thread to reopen", [
            ("Thread ID", str(thread_id)),
        ])
        return False

    # Verify it's in debates forum
    if thread.parent_id != DEBATES_FORUM_ID:
        logger.warning("Appeal: Thread not in debates forum", [
            ("Thread ID", str(thread_id)),
            ("Parent ID", str(thread.parent_id)),
        ])
        return False

    # Verify it's closed
    if not thread.name.startswith("[CLOSED]"):
        logger.info("Appeal: Thread already open", [
            ("Thread ID", str(thread_id)),
        ])
        return True  # Already open, consider success

    # Try to get original thread name from closure_history
    original_name = None
    original_num = None
    if db:
        closure_record = await asyncio.to_thread(db.get_closure_by_thread_id, thread_id)
        if closure_record and closure_record.get("thread_name"):
            original_name = closure_record["thread_name"]
            num_match = re.match(r'^(\d+)\s*\|\s*(.+)$', original_name)
            if num_match:
                original_num = int(num_match.group(1))
                logger.info("Appeal: Found original thread number in history", [
                    ("Thread ID", str(thread_id)),
                    ("Original Number", str(original_num)),
                ])

    # If we have the original name, use it directly
    if original_name and original_num:
        new_name = original_name
    else:
        # Fallback: extract title and get next number
        title = thread.name
        if title.startswith("[CLOSED] | "):
            title = title[11:]
        elif title.startswith("[CLOSED]"):
            title = title[8:].lstrip(" |")

        # Handle legacy format
        legacy_match = re.match(r'^\d+\s*\|\s*(.+)$', title)
        if legacy_match:
            title = legacy_match.group(1)

        # Get next debate number
        next_num = 1
        if db:
            next_num = await asyncio.to_thread(db.get_next_debate_number)

        new_name = f"{next_num} | {title}"

    if len(new_name) > 100:
        new_name = new_name[:97] + "..."

    # Reopen thread
    try:
        await edit_thread_with_retry(thread, name=new_name, archived=False, locked=False)
        logger.info("Appeal: Thread Reopened", [
            ("Thread ID", str(thread_id)),
            ("New Name", new_name),
        ])

        # Update closure_history to mark as reopened via appeal
        if db:
            try:
                await asyncio.to_thread(
                    db.update_closure_history_reopened,
                    thread_id,
                    reviewed_by.id
                )
            except Exception as e:
                logger.warning("Failed to update closure history for appeal", [
                    ("Thread ID", str(thread_id)),
                    ("Error", str(e)),
                ])

        return True
    except Exception as e:
        logger.error("Appeal: Failed to reopen thread", [
            ("Thread ID", str(thread_id)),
            ("Error", str(e)),
        ])
        return False


__all__ = [
    "undo_action",
    "undo_disallow",
    "undo_close",
]
