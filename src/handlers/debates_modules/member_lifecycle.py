"""
OthmanBot - Debates Member Lifecycle Handlers
==============================================

Handles member join/leave events for debate participants.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger

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
    4. Log to case thread if they have one
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return

    db = bot.debates_service.db

    # Check if this user is a debate participant
    if not db.has_debate_participation(member.id):
        logger.debug("Member Left (Not A Debate Participant)", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
        ])
        return

    # Get user stats
    user_analytics = db.get_user_analytics(member.id)
    debates_participated = user_analytics.get('debates_participated', 0)
    debates_created = user_analytics.get('debates_created', 0)

    # Get current karma
    karma_data = db.get_user_karma(member.id)
    current_karma = karma_data.total_karma

    # Check if user has a case log
    case_log = db.get_case_log(member.id)
    case_id = case_log.get('case_id') if case_log else None

    # Remove all votes cast by this user
    result = db.remove_votes_by_user(member.id)
    votes_removed = result.get("votes_removed", 0)

    if votes_removed > 0:
        logger.info("👋 Removed Leaving User's Votes", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
            ("Votes Removed", str(votes_removed)),
        ])

    # Log to main logs
    logger.warning("👋 Debate Participant Left Server", [
        ("User", f"{member.name} ({member.display_name})"),
        ("ID", str(member.id)),
        ("Debates Participated", str(debates_participated)),
        ("Debates Created", str(debates_created)),
        ("Karma", str(current_karma)),
        ("Votes Removed", str(votes_removed)),
        ("Has Case ID", f"[{case_id:04d}]" if case_id else "No"),
    ])

    # Log to case thread if they have one
    if hasattr(bot, 'case_log_service') and bot.case_log_service:
        await bot.case_log_service.log_member_left(
            user_id=member.id,
            user_name=member.name,
            user_avatar_url=member.display_avatar.url
        )


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
        return

    db = bot.debates_service.db

    # Check if this user is a debate participant
    if not db.has_debate_participation(member.id):
        logger.debug("Member Joined (Not A Debate Participant)", [
            ("User", f"{member.name} ({member.display_name})"),
            ("ID", str(member.id)),
        ])
        return

    # Get user stats
    user_analytics = db.get_user_analytics(member.id)
    debates_participated = user_analytics.get('debates_participated', 0)
    debates_created = user_analytics.get('debates_created', 0)

    # Check if user has a case log
    case_log = db.get_case_log(member.id)
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
        await bot.case_log_service.log_member_rejoined(member)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "on_member_remove_handler",
    "on_member_join_handler",
]
