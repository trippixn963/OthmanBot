"""
OthmanBot - Notification Embeds
===============================

Embed building functions for ban notifications.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.config import NY_TZ, EmbedIcons, EMBED_NO_VALUE
from src.utils import get_ordinal
from src.utils.footer import set_footer
from src.services.notifications.constants import COLOR_BAN, COLOR_UNBAN, COLOR_EXPIRED

if TYPE_CHECKING:
    from src.bot import OthmanBot


def format_scope(scope: str, thread_id: Optional[int] = None) -> str:
    """
    Format the scope for display in the embed.

    Args:
        scope: Raw scope string
        thread_id: Optional thread ID

    Returns:
        Formatted scope string
    """
    if thread_id:
        return f"`Specific Thread`\n<#{thread_id}>"
    elif "all" in scope.lower():
        return "`All Debates`"
    else:
        return f"`{scope}`"


def build_ban_embed(
    user: Union[discord.User, discord.Member],
    banned_by: Union[discord.User, discord.Member],
    scope: str,
    duration: str,
    expires_at: Optional[datetime] = None,
    thread_id: Optional[int] = None,
    reason: Optional[str] = None,
    past_ban_count: int = 0
) -> discord.Embed:
    """Build the ban notification embed."""
    embed = discord.Embed(
        title=f"{EmbedIcons.BAN} You Have Been Banned from Debates",
        description=(
            "You have been banned from participating in debate threads.\n"
            "Please review the details below."
        ),
        color=COLOR_BAN,
        timestamp=datetime.now(NY_TZ)
    )

    embed.set_thumbnail(url=banned_by.display_avatar.url)

    # Core fields
    embed.add_field(
        name="Banned By",
        value=f"{banned_by.display_name}",
        inline=True
    )
    embed.add_field(
        name="Scope",
        value=format_scope(scope, thread_id),
        inline=True
    )
    embed.add_field(
        name="Duration",
        value=f"`{duration}`",
        inline=True
    )

    # Expiry time
    if expires_at:
        embed.add_field(
            name="Expires",
            value=f"<t:{int(expires_at.timestamp())}:F>\n(<t:{int(expires_at.timestamp())}:R>)",
            inline=True
        )
    else:
        embed.add_field(
            name="Expires",
            value="`Never (Permanent)`",
            inline=True
        )

    # Thread link if specific thread
    if thread_id:
        embed.add_field(
            name="Thread ID",
            value=f"`{thread_id}`",
            inline=True
        )

    # Reason
    embed.add_field(
        name="Reason",
        value=reason[:1024] if reason else EMBED_NO_VALUE,
        inline=False
    )

    # Past ban history
    if past_ban_count > 0:
        ordinal = get_ordinal(past_ban_count + 1)
        embed.add_field(
            name=f"{EmbedIcons.WARNING} Ban History",
            value=f"This is your **{ordinal}** ban from debates.",
            inline=True
        )

        # Consequence warning
        if past_ban_count == 1:
            consequence_warning = (
                "This is your second ban. Further violations may result in "
                "longer ban durations or permanent removal from debates."
            )
        elif past_ban_count == 2:
            consequence_warning = (
                "This is your third ban. Continued violations will likely "
                "result in permanent removal from debates."
            )
        else:
            consequence_warning = (
                "You have been banned multiple times. Any further violations "
                "will result in permanent removal from debates."
            )

        embed.add_field(
            name=f"{EmbedIcons.ALERT} Warning",
            value=consequence_warning,
            inline=False
        )

    # Server join date (if available as Member)
    if isinstance(user, discord.Member) and user.joined_at:
        embed.add_field(
            name="Member Since",
            value=f"<t:{int(user.joined_at.timestamp())}:D>",
            inline=True
        )

    # What's Next guidance
    embed.add_field(
        name="What's Next?",
        value="You may appeal this decision using the button below.",
        inline=False
    )

    set_footer(embed)
    return embed


def build_unban_embed(
    unbanned_by: Union[discord.User, discord.Member],
    scope: str,
    thread_id: Optional[int] = None,
    reason: Optional[str] = None
) -> discord.Embed:
    """Build the unban notification embed."""
    embed = discord.Embed(
        title=f"{EmbedIcons.UNBAN} You Have Been Unbanned from Debates",
        description=(
            "Your debate ban has been lifted!\n"
            "You can now participate in debate threads again."
        ),
        color=COLOR_UNBAN,
        timestamp=datetime.now(NY_TZ)
    )

    embed.set_thumbnail(url=unbanned_by.display_avatar.url)

    # Core fields
    embed.add_field(
        name="Unbanned By",
        value=f"{unbanned_by.display_name}",
        inline=True
    )
    embed.add_field(
        name="Scope",
        value=format_scope(scope, thread_id),
        inline=True
    )

    # Thread link if specific thread
    if thread_id:
        embed.add_field(
            name="Thread ID",
            value=f"`{thread_id}`",
            inline=True
        )

    # Reason/Note
    if reason:
        embed.add_field(
            name="Reason",
            value=reason[:1024],
            inline=False
        )

    # What's Next guidance
    embed.add_field(
        name="What's Next?",
        value=(
            "You can now participate in debates again.\n"
            "React with ✅ to the rules message if required."
        ),
        inline=False
    )

    set_footer(embed)
    return embed


async def build_expiry_embed(
    bot: "OthmanBot",
    scope: str,
    thread_id: Optional[int] = None,
    reason: Optional[str] = None,
    banned_by_id: Optional[int] = None,
    created_at: Optional[str] = None,
) -> discord.Embed:
    """Build the ban expiry notification embed."""
    embed = discord.Embed(
        title=f"{EmbedIcons.EXPIRED} Your Debate Ban Has Expired",
        description=(
            "Your temporary ban from debates has expired!\n"
            "You can now participate in debate threads again."
        ),
        color=COLOR_EXPIRED,
        timestamp=datetime.now(NY_TZ)
    )

    # Set bot avatar as thumbnail (system action)
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    # Core fields
    embed.add_field(
        name="Action",
        value="`Automatic Unban`",
        inline=True
    )
    embed.add_field(
        name="Scope",
        value=format_scope(scope, thread_id),
        inline=True
    )

    # Thread link if specific thread
    if thread_id:
        embed.add_field(
            name="Thread ID",
            value=f"`{thread_id}`",
            inline=True
        )

    # Add banned by (fetch moderator name if possible)
    if banned_by_id:
        try:
            banned_by_user = await bot.fetch_user(banned_by_id)
            banned_by_display = banned_by_user.display_name
        except Exception:
            banned_by_display = f"User {banned_by_id}"
        embed.add_field(
            name="Originally Banned By",
            value=banned_by_display,
            inline=True
        )

    # When ban was created
    if created_at:
        try:
            from datetime import datetime as dt
            created_dt = dt.fromisoformat(created_at.replace("Z", "+00:00"))
            embed.add_field(
                name="Banned On",
                value=f"<t:{int(created_dt.timestamp())}:F>",
                inline=True
            )
        except Exception:
            embed.add_field(
                name="Banned On",
                value=created_at,
                inline=True
            )

    # Original ban reason
    if reason:
        embed.add_field(
            name="Original Reason",
            value=reason[:1024],
            inline=False
        )

    # What's Next guidance
    embed.add_field(
        name="What's Next?",
        value=(
            "You can now participate in debates again.\n"
            "Please follow the rules to avoid future bans."
        ),
        inline=False
    )

    set_footer(embed)
    return embed


__all__ = [
    "format_scope",
    "build_ban_embed",
    "build_unban_embed",
    "build_expiry_embed",
]
