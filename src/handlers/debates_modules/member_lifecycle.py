"""
OthmanBot - Debates Member Lifecycle Handlers
==============================================

Handles member join/leave events for debate participants.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, NY_TZ, EmbedColors, EmbedIcons
from src.utils import edit_thread_with_retry
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Member Leave Handler
# =============================================================================

async def on_member_remove_handler(bot: "OthmanBot", member: discord.Member) -> None:
    """
    Event handler for member leaving the server.

    Args:
        bot: The OthmanBot instance
        member: The member who left

    DESIGN: Only tracks users who have participated in debates at least once.
    When a debate participant leaves:
    1. Check if they have debate participation history
    2. Get their stats before cleanup
    3. Remove their votes (karma effects reversed)
    4. Close any open debate threads they created
    5. Log to case thread if they have one
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        logger.debug("Member Remove Handler Skipped", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Reason", "Debates service not available"),
        ])
        return

    db = bot.debates_service.db

    # Check if this user is a debate participant
    has_participation = await asyncio.to_thread(db.has_debate_participation, member.id)
    if not has_participation:
        logger.debug("Member Left (Not A Debate Participant)", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
        ])
        return

    # Get user stats
    user_analytics = await asyncio.to_thread(db.get_user_analytics, member.id)
    debates_participated = user_analytics.get('debates_participated', 0)
    debates_created = user_analytics.get('debates_created', 0)

    # Get current karma
    karma_data = await asyncio.to_thread(db.get_user_karma, member.id)
    current_karma = karma_data.total_karma

    # Check if user has a case log
    case_log = await asyncio.to_thread(db.get_case_log, member.id)
    case_id = case_log.get('case_id') if case_log else None

    # NOTE: We do NOT remove votes when a member leaves.
    # - Votes they cast on others represent genuine community engagement
    # - Votes others cast on their posts represent hard work that should be preserved
    # - Votes are only cleaned up when threads/messages are actually DELETED
    # This preserves karma for all participants even when the thread owner leaves.

    # Close any open debate threads created by this user (but keep all votes)
    threads_closed = await _close_user_debate_threads(bot, member)

    # Log to main logs
    logger.warning("👋 Debate Participant Left Server", [
        ("User", f"{member.name} ({member.display_name})"),
        ("ID", str(member.id)),
        ("Debates Participated", str(debates_participated)),
        ("Debates Created", str(debates_created)),
        ("Karma", str(current_karma)),
        ("Threads Closed", str(threads_closed)),
        ("Votes Preserved", "Yes"),
        ("Has Case ID", f"[{case_id:04d}]" if case_id else "No"),
    ])

    # Log to case thread if they have one
    if hasattr(bot, 'case_log_service') and bot.case_log_service:
        try:
            await bot.case_log_service.log_member_left(
                user_id=member.id,
                user_name=member.name,
                user_avatar_url=member.display_avatar.url
            )
            logger.debug("Case Log Updated (Member Left)", [
                ("User", f"{member.name} ({member.display_name})"),
                ("ID", str(member.id)),
                ("Case ID", f"[{case_id:04d}]" if case_id else "N/A"),
            ])
        except Exception as e:
            logger.tree("Failed to Update Case Log (Member Left)", [
                ("User", f"{member.name} ({member.display_name})"),
                ("ID", str(member.id)),
                ("Error", str(e)[:80]),
            ], emoji="⚠️")
    else:
        logger.debug("Case Log Service Not Available", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Event", "Member Left"),
        ])


async def _close_user_debate_threads(bot: "OthmanBot", member: discord.Member) -> int:
    """
    Close all open debate threads created by a user who left.

    Uses database lookup instead of iterating all threads for efficiency.

    Args:
        bot: The OthmanBot instance
        member: The member who left

    Returns:
        Number of threads closed
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        logger.debug("Auto-Close Skipped", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Reason", "Debates service not available"),
        ])
        return 0

    db = bot.debates_service.db

    # Get all thread IDs created by this user from database
    thread_ids = await asyncio.to_thread(db.get_threads_by_creator, member.id)

    if not thread_ids:
        logger.tree("No Debates to Auto-Close", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Threads Found", "0"),
        ], emoji="ℹ️")
        return 0

    logger.tree("Found Debates to Auto-Close", [
        ("User", f"{member.name} ({member.display_name})"),
        ("ID", str(member.id)),
        ("Thread Count", str(len(thread_ids))),
    ], emoji="🔍")

    threads_closed = 0

    for thread_id in thread_ids:
        try:
            # Get the thread from Discord
            thread = bot.get_channel(thread_id)
            if not thread or not isinstance(thread, discord.Thread):
                logger.debug("Thread Not Found in Cache", [
                    ("Thread ID", str(thread_id)),
                    ("OP", f"{member.name} ({member.display_name})"),
                    ("ID", str(member.id)),
                    ("Reason", "Deleted or not cached"),
                ])
                continue

            # Skip already closed threads
            if thread.name.startswith("[CLOSED]"):
                logger.debug("Thread Already Closed", [
                    ("Thread", f"{thread.name} ({thread_id})"),
                    ("OP", f"{member.name} ({member.display_name})"),
                    ("ID", str(member.id)),
                ])
                continue

            # Skip locked/archived threads
            if thread.locked or thread.archived:
                logger.debug("Thread Already Locked/Archived", [
                    ("Thread", f"{thread.name} ({thread_id})"),
                    ("OP", f"{member.name} ({member.display_name})"),
                    ("ID", str(member.id)),
                    ("Locked", str(thread.locked)),
                    ("Archived", str(thread.archived)),
                ])
                continue

            # Close this thread
            original_name = thread.name

            # Extract the title without the number prefix
            title_match = re.match(r'^\d+\s*\|\s*(.+)$', thread.name)
            title = title_match.group(1) if title_match else thread.name

            # Build new name
            new_name = f"[CLOSED] | {title}"
            if len(new_name) > 100:
                new_name = new_name[:97] + "..."

            # Rename the thread
            rename_success = await edit_thread_with_retry(thread, name=new_name)

            # Lock the thread
            lock_success = await edit_thread_with_retry(thread, locked=True)

            # Send closure notification in thread
            now = datetime.now(NY_TZ)
            embed = discord.Embed(
                title=f"{EmbedIcons.CLOSE} Debate Auto-Closed",
                description="This debate has been automatically closed because the original poster left the server.",
                color=EmbedColors.CLOSE,
                timestamp=now,
            )
            embed.add_field(name="Reason", value="OP left the server", inline=False)
            embed.add_field(name="Former OP", value=f"{member.name} ({member.display_name})", inline=True)
            embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
            embed.add_field(name="Time", value=f"<t:{int(now.timestamp())}:f>", inline=True)
            set_footer(embed)

            await thread.send(embed=embed)

            threads_closed += 1

            logger.tree("Auto-Closed Debate (OP Left)", [
                ("Thread", f"{original_name} ({thread_id})"),
                ("OP", f"{member.name} ({member.display_name})"),
                ("ID", str(member.id)),
                ("Renamed", "Yes" if rename_success else "No"),
                ("Locked", "Yes" if lock_success else "No"),
            ], emoji="🔒")

        except discord.NotFound:
            logger.debug("Thread Not Found (Deleted)", [
                ("Thread ID", str(thread_id)),
                ("OP", f"{member.name} ({member.display_name})"),
                ("ID", str(member.id)),
            ])
            continue
        except Exception as e:
            logger.tree("Failed to Auto-Close Debate", [
                ("Thread ID", str(thread_id)),
                ("OP", f"{member.name} ({member.display_name})"),
                ("ID", str(member.id)),
                ("Error", str(e)[:80]),
            ], emoji="⚠️")
            continue

    # Log summary
    if threads_closed > 0:
        logger.tree("Auto-Close Summary", [
            ("OP", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Threads Found", str(len(thread_ids))),
            ("Threads Closed", str(threads_closed)),
        ], emoji="📊")

    return threads_closed


# =============================================================================
# Member Join Handler
# =============================================================================

async def on_member_join_handler(bot: "OthmanBot", member: discord.Member) -> None:
    """
    Event handler for member joining the server.

    Args:
        bot: The OthmanBot instance
        member: The member who joined

    DESIGN: Only tracks users who have participated in debates at least once.
    When a debate participant rejoins:
    1. Check if they have debate participation history
    2. Get their stats
    3. Log to case thread if they have one
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        logger.debug("Member Join Handler Skipped", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Reason", "Debates service not available"),
        ])
        return

    db = bot.debates_service.db

    # Check if this user is a debate participant
    has_participation = await asyncio.to_thread(db.has_debate_participation, member.id)
    if not has_participation:
        logger.debug("Member Joined (Not A Debate Participant)", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
        ])
        return

    # Get user stats
    user_analytics = await asyncio.to_thread(db.get_user_analytics, member.id)
    debates_participated = user_analytics.get('debates_participated', 0)
    debates_created = user_analytics.get('debates_created', 0)

    # Check if user has a case log
    case_log = await asyncio.to_thread(db.get_case_log, member.id)
    case_id = case_log.get('case_id') if case_log else None

    # Log to main logs
    logger.success("👋 Debate Participant Rejoined Server", [
        ("User", f"{member.name} ({member.display_name})"),
        ("ID", str(member.id)),
        ("Debates Participated", str(debates_participated)),
        ("Debates Created", str(debates_created)),
        ("Has Case ID", f"[{case_id:04d}]" if case_id else "No"),
    ])

    # Log to case thread if they have one
    if hasattr(bot, 'case_log_service') and bot.case_log_service:
        try:
            await bot.case_log_service.log_member_rejoined(member)
            logger.debug("Case Log Updated (Member Rejoined)", [
                ("User", f"{member.name} ({member.display_name})"),
                ("ID", str(member.id)),
                ("Case ID", f"[{case_id:04d}]" if case_id else "N/A"),
            ])
        except Exception as e:
            logger.tree("Failed to Update Case Log (Member Rejoined)", [
                ("User", f"{member.name} ({member.display_name})"),
                ("ID", str(member.id)),
                ("Error", str(e)[:80]),
            ], emoji="⚠️")
    else:
        logger.debug("Case Log Service Not Available", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Event", "Member Rejoined"),
        ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "on_member_remove_handler",
    "on_member_join_handler",
]
