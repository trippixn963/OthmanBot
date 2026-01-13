"""
OthmanBot - Appeals Embeds
==========================

Embed building and updating for appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.core.config import NY_TZ, EmbedIcons
from src.utils.discord_rate_limit import log_http_error
from src.views.appeals import AppealReviewView, ACTION_TYPE_LABELS
from src.services.appeals.constants import (
    COLOR_APPEAL_SUBMITTED,
    COLOR_APPEAL_APPROVED,
    COLOR_APPEAL_DENIED,
)

if TYPE_CHECKING:
    from src.bot import OthmanBot


async def post_appeal_to_case_thread(
    bot: "OthmanBot",
    appeal_id: int,
    user: Union[discord.User, discord.Member],
    action_type: str,
    action_id: int,
    reason: str,
    additional_context: Optional[str],
) -> None:
    """Post appeal embed to user's case thread."""
    db = bot.debates_service.db if bot.debates_service else None

    if not bot.case_log_service or not db:
        logger.warning("Case log service not available for appeal posting")
        return

    # Get or create case thread
    case = db.get_case_log(user.id)
    if not case:
        logger.info("No case thread exists for appeal user", [
            ("User ID", str(user.id)),
        ])
        return

    # Get the case thread
    case_thread = await bot.case_log_service.thread_manager.get_case_thread(case["thread_id"])
    if not case_thread:
        logger.warning("Could not find case thread for appeal", [
            ("Thread ID", str(case["thread_id"])),
        ])
        return

    # Get the original moderator who took the action
    action_by_id: Optional[int] = None
    if action_type == "disallow":
        ban_history = db.get_user_ban_history(user.id, limit=1)
        if ban_history:
            action_by_id = ban_history[0].get("banned_by")
    elif action_type == "close":
        closure = db.get_closure_by_thread_id(action_id)
        if closure:
            action_by_id = closure.get("closed_by")

    # Build the appeal embed
    now = datetime.now(NY_TZ)
    action_label = ACTION_TYPE_LABELS.get(action_type, action_type.title())

    embed = discord.Embed(
        title="\U0001f4dd Appeal Submitted",
        color=COLOR_APPEAL_SUBMITTED,
        timestamp=now,
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(
        name="Action Being Appealed",
        value=action_label,
        inline=True,
    )

    if action_type == "close":
        embed.add_field(
            name="Thread",
            value=f"<#{action_id}>",
            inline=True,
        )

    if action_by_id:
        embed.add_field(
            name="Action By",
            value=f"<@{action_by_id}>",
            inline=True,
        )

    embed.add_field(
        name="Submitted",
        value=f"<t:{int(now.timestamp())}:R>",
        inline=True,
    )

    embed.add_field(
        name="Reason for Appeal",
        value=reason[:1024],
        inline=False,
    )

    if additional_context:
        embed.add_field(
            name="Additional Context",
            value=additional_context[:1024],
            inline=False,
        )
    else:
        embed.add_field(
            name="Additional Context",
            value="_None provided_",
            inline=False,
        )

    embed.set_footer(
        text=f"Appeal #{appeal_id} | User can appeal once per action",
    )

    # Create review view with Approve/Deny buttons
    view = AppealReviewView(appeal_id=appeal_id)

    # Send to case thread
    message = await case_thread.send(embed=embed, view=view)

    # Store message ID so we can edit it when approved/denied
    if message and db:
        db.set_appeal_case_message_id(appeal_id, message.id)

    logger.info("Appeal Posted to Case Thread", [
        ("Appeal ID", str(appeal_id)),
        ("Case Thread ID", str(case["thread_id"])),
        ("Message ID", str(message.id) if message else "None"),
    ])


async def update_appeal_embed_status(
    bot: "OthmanBot",
    appeal_id: int,
    decision: str,
    reviewed_by: Union[discord.User, discord.Member],
    denial_reason: Optional[str] = None,
) -> bool:
    """
    Edit the existing appeal embed in case thread to show the decision.

    Args:
        bot: The OthmanBot instance
        appeal_id: The appeal ID
        decision: Either "approved" or "denied"
        reviewed_by: The moderator who reviewed
        denial_reason: Optional reason for denial

    Returns:
        True if successful, False otherwise
    """
    db = bot.debates_service.db if bot.debates_service else None
    if not db:
        return False

    # Get the appeal with case_message_id
    appeal = db.get_appeal(appeal_id)
    if not appeal:
        logger.warning("Cannot update appeal embed - appeal not found", [
            ("Appeal ID", str(appeal_id)),
        ])
        return False

    case_message_id = appeal.get("case_message_id")
    if not case_message_id:
        logger.warning("Cannot update appeal embed - no case_message_id stored", [
            ("Appeal ID", str(appeal_id)),
        ])
        return False

    if not bot.case_log_service:
        return False

    case = db.get_case_log(appeal["user_id"])
    if not case:
        return False

    case_thread = await bot.case_log_service.thread_manager.get_case_thread(case["thread_id"])
    if not case_thread:
        logger.warning("Cannot update appeal embed - case thread not found", [
            ("Thread ID", str(case["thread_id"])),
        ])
        return False

    try:
        message = await case_thread.fetch_message(case_message_id)
        if not message or not message.embeds:
            logger.warning("Cannot update appeal embed - message has no embeds", [
                ("Message ID", str(case_message_id)),
            ])
            return False

        old_embed = message.embeds[0]
        now = datetime.now(NY_TZ)

        # Determine new color and title based on decision
        if decision == "approved":
            new_color = COLOR_APPEAL_APPROVED
            new_title = f"{EmbedIcons.APPROVED} Appeal Approved"
            decision_field_name = "Approved By"
            decision_field_value = f"<@{reviewed_by.id}>"
        else:
            new_color = COLOR_APPEAL_DENIED
            new_title = f"{EmbedIcons.DENIED} Appeal Denied"
            decision_field_name = "Denied By"
            decision_field_value = f"<@{reviewed_by.id}>"

        # Create new embed with updated info
        new_embed = discord.Embed(
            title=new_title,
            color=new_color,
            timestamp=old_embed.timestamp,
        )

        if old_embed.thumbnail:
            new_embed.set_thumbnail(url=old_embed.thumbnail.url)

        # Copy existing fields
        for field in old_embed.fields:
            new_embed.add_field(
                name=field.name,
                value=field.value,
                inline=field.inline,
            )

        # Add review decision field
        new_embed.add_field(
            name=decision_field_name,
            value=decision_field_value,
            inline=True,
        )

        new_embed.add_field(
            name="Reviewed",
            value=f"<t:{int(now.timestamp())}:R>",
            inline=True,
        )

        if decision == "denied" and denial_reason:
            new_embed.add_field(
                name="Denial Reason",
                value=denial_reason[:1024],
                inline=False,
            )

        new_embed.set_footer(
            text=f"Appeal #{appeal_id} | {decision.title()}",
        )

        # Edit the message - remove the view (buttons) since it's been reviewed
        await message.edit(embed=new_embed, view=None)

        logger.info("Appeal Embed Updated", [
            ("Appeal ID", str(appeal_id)),
            ("Decision", decision),
            ("Reviewed By", f"{reviewed_by.name} ({reviewed_by.display_name})"),
            ("ID", str(reviewed_by.id)),
        ])
        return True

    except discord.NotFound:
        logger.warning("Cannot update appeal embed - message not found", [
            ("Message ID", str(case_message_id)),
        ])
        return False
    except discord.HTTPException as e:
        log_http_error(e, "Update Appeal Embed", [
            ("Appeal ID", str(appeal_id)),
            ("Decision", decision),
        ])
        return False


__all__ = [
    "post_appeal_to_case_thread",
    "update_appeal_embed_status",
]
