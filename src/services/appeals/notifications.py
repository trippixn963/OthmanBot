"""
OthmanBot - Appeals Notifications
=================================

User notification (DM) logic for appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.core.config import NY_TZ, EmbedIcons
from src.utils.discord_rate_limit import log_http_error
from src.utils.footer import set_footer
from src.views.appeals import ACTION_TYPE_LABELS
from src.services.appeals.constants import COLOR_APPEAL_APPROVED, COLOR_APPEAL_DENIED

if TYPE_CHECKING:
    from src.bot import OthmanBot


async def send_appeal_result_dm(
    bot: "OthmanBot",
    user_id: int,
    action_type: str,
    approved: bool,
    reviewed_by: Union[discord.User, discord.Member],
    appeal_id: Optional[int] = None,
    denial_reason: Optional[str] = None,
) -> bool:
    """Send DM to user with appeal result."""
    # Find the user
    user: Optional[discord.User] = None

    try:
        user = await bot.fetch_user(user_id)
    except discord.NotFound:
        logger.warning("Appeal: Could not find user for DM", [
            ("ID", str(user_id)),
        ])
        return False

    if not user:
        return False

    action_label = ACTION_TYPE_LABELS.get(action_type, action_type.title())
    now = datetime.now(NY_TZ)

    if approved:
        embed = discord.Embed(
            title=f"{EmbedIcons.APPROVED} Appeal Approved",
            description=(
                "Your appeal has been approved and the action has been reversed."
            ),
            color=COLOR_APPEAL_APPROVED,
            timestamp=now,
        )
        embed.set_thumbnail(url=reviewed_by.display_avatar.url)
        embed.add_field(
            name="Action Reversed",
            value=action_label,
            inline=True,
        )
        embed.add_field(
            name="What's Next?",
            value="You can now participate in debates again.",
            inline=False,
        )
    else:
        embed = discord.Embed(
            title=f"{EmbedIcons.DENIED} Appeal Denied",
            description=(
                "Your appeal has been reviewed and denied."
            ),
            color=COLOR_APPEAL_DENIED,
            timestamp=now,
        )
        embed.set_thumbnail(url=reviewed_by.display_avatar.url)
        embed.add_field(
            name="Action",
            value=f"{action_label} remains",
            inline=True,
        )

    embed.add_field(
        name="Reviewed By",
        value=reviewed_by.display_name,
        inline=True,
    )
    embed.add_field(
        name="Time",
        value=f"<t:{int(now.timestamp())}:f>",
        inline=True,
    )

    if appeal_id:
        embed.add_field(
            name="Appeal ID",
            value=f"`#{appeal_id}`",
            inline=True,
        )

    if not approved and denial_reason:
        reason_display = denial_reason[:1000] + "..." if len(denial_reason) > 1000 else denial_reason
        embed.add_field(
            name="Reason",
            value=reason_display,
            inline=False,
        )

    set_footer(embed)

    try:
        await user.send(embed=embed)
        logger.info("Appeal Result DM Sent", [
            ("User", f"{user.name} ({user.display_name})"),
            ("ID", str(user_id)),
            ("Approved", str(approved)),
        ])
        return True
    except discord.Forbidden:
        logger.warning("Appeal: Could not send DM - DMs disabled", [
            ("User", f"{user.name} ({user.display_name})"),
            ("ID", str(user_id)),
        ])
        return False
    except discord.HTTPException as e:
        log_http_error(e, "Appeal Result DM", [
            ("User", f"{user.name} ({user.display_name})"),
            ("ID", str(user_id)),
            ("Approved", str(approved)),
        ])
        return False


__all__ = ["send_appeal_result_dm"]
