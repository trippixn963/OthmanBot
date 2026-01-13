"""
OthmanBot - Case Embed Builder
==============================

Builds embeds for case log actions (bans, unbans, closes, etc.)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional

import discord

from src.core.config import NY_TZ, EmbedColors


class CaseEmbedBuilder:
    """Builds embeds for case log actions."""

    @staticmethod
    def build_ban_embed(
        user: discord.Member,
        banned_by: discord.Member,
        scope: str,
        duration: str,
        target_thread_id: Optional[int],
        reason: Optional[str] = None,
        ban_count: int = 1
    ) -> discord.Embed:
        """
        Build a ban action embed with banned user's thumbnail.

        Args:
            user: The user being banned
            banned_by: The moderator who issued the ban
            scope: Scope of the ban
            duration: Duration display string
            target_thread_id: Optional specific debate thread ID
            reason: Optional reason for the ban
            ban_count: The ban number for this user (1, 2, 3, etc.)

        Returns:
            Discord Embed for the ban action
        """
        # Title includes ban count
        title = f"🚫 User Banned (Ban #{ban_count})" if ban_count > 1 else "🚫 User Banned"

        embed = discord.Embed(
            title=title,
            color=EmbedColors.BAN
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Banned By", value=f"{banned_by.mention}", inline=True)
        embed.add_field(name="Scope", value=scope, inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True
        )

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        return embed

    @staticmethod
    def build_unban_embed(
        unbanned_by: discord.Member,
        scope: str,
        reason: Optional[str] = None,
        user_avatar_url: Optional[str] = None
    ) -> discord.Embed:
        """
        Build an unban action embed with unbanned user's thumbnail.

        Args:
            unbanned_by: The moderator who issued the unban
            scope: Scope of the unban
            reason: Optional reason for the unban
            user_avatar_url: Avatar URL of the unbanned user

        Returns:
            Discord Embed for the unban action
        """
        embed = discord.Embed(
            title="✅ User Unbanned",
            color=EmbedColors.UNBAN
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)
        embed.add_field(name="Unbanned By", value=f"{unbanned_by.mention}", inline=True)
        embed.add_field(name="Scope", value=scope, inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True
        )

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        return embed

    @staticmethod
    def build_expired_embed(
        scope: str,
        user_avatar_url: Optional[str] = None
    ) -> discord.Embed:
        """
        Build a ban expired (auto-unban) embed.

        Args:
            scope: Scope of the expired ban
            user_avatar_url: Avatar URL of the user whose ban expired

        Returns:
            Discord Embed for the expiry
        """
        embed = discord.Embed(
            title="⏰ Ban Expired (Auto-Unban)",
            color=EmbedColors.INFO
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)
        embed.add_field(name="Scope", value=scope, inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True
        )

        return embed

    @staticmethod
    def build_debate_close_embed(
        owner: discord.Member,
        closed_by: discord.Member,
        thread: discord.Thread,
        original_name: str,
        reason: str
    ) -> discord.Embed:
        """
        Build a debate close embed for case log.

        Args:
            owner: The debate owner
            closed_by: The moderator who closed the debate
            thread: The debate thread
            original_name: Original thread name
            reason: Reason for closing

        Returns:
            Discord Embed for the debate close action
        """
        embed = discord.Embed(
            title="🔒 Debate Closed",
            color=EmbedColors.CLOSE
        )
        embed.set_thumbnail(url=owner.display_avatar.url)
        embed.add_field(name="Closed By", value=f"{closed_by.mention}", inline=True)

        # Build clickable link to debate
        if thread.guild:
            debate_link = f"[{original_name[:30]}{'...' if len(original_name) > 30 else ''}](https://discord.com/channels/{thread.guild.id}/{thread.id})"
            embed.add_field(name="Debate", value=debate_link, inline=True)
        else:
            embed.add_field(name="Debate", value=f"`{original_name[:30]}`", inline=True)

        embed.add_field(name="Thread ID", value=f"`{thread.id}`", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True
        )

        embed.add_field(name="Reason", value=reason, inline=False)

        return embed

    @staticmethod
    def build_debate_reopen_embed(
        owner: discord.Member,
        reopened_by: discord.Member,
        thread: discord.Thread,
        new_name: str,
        reason: str
    ) -> discord.Embed:
        """
        Build a debate reopen embed for case log.

        Args:
            owner: The debate owner
            reopened_by: The moderator who reopened the debate
            thread: The debate thread
            new_name: Thread name after reopening
            reason: Reason for reopening

        Returns:
            Discord Embed for the debate reopen action
        """
        embed = discord.Embed(
            title="🔓 Debate Reopened",
            color=EmbedColors.UNBAN
        )
        embed.set_thumbnail(url=owner.display_avatar.url)
        embed.add_field(name="Reopened By", value=f"{reopened_by.mention}", inline=True)

        # Build clickable link to debate
        if thread.guild:
            debate_link = f"[{new_name[:30]}{'...' if len(new_name) > 30 else ''}](https://discord.com/channels/{thread.guild.id}/{thread.id})"
            embed.add_field(name="Debate", value=debate_link, inline=True)
        else:
            embed.add_field(name="Debate", value=f"`{new_name[:30]}`", inline=True)

        embed.add_field(name="Thread ID", value=f"`{thread.id}`", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True
        )

        embed.add_field(name="Reason", value=reason, inline=False)

        return embed

    @staticmethod
    def build_member_left_embed(
        user_name: str,
        user_id: int,
        user_avatar_url: Optional[str] = None
    ) -> discord.Embed:
        """
        Build embed for when a user with a case thread leaves the server.

        Args:
            user_name: The user's display name
            user_id: The user's ID
            user_avatar_url: The user's avatar URL

        Returns:
            Discord Embed for member left event
        """
        embed = discord.Embed(
            title="🚪 User Left Server",
            color=EmbedColors.CLOSE,
            description=f"**{user_name}** has left the server"
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)

        embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True
        )

        return embed

    @staticmethod
    def build_member_rejoined_embed(
        member: discord.Member,
        is_still_disallowed: bool,
        disallow_count: int,
        restriction_scopes: list
    ) -> discord.Embed:
        """
        Build embed for when a user with a case thread rejoins the server.

        Args:
            member: The member who rejoined
            is_still_disallowed: Whether the user is still disallowed
            disallow_count: Number of previous disallows
            restriction_scopes: List of scope strings if still disallowed

        Returns:
            Discord Embed for member rejoined event
        """
        # Choose embed color based on disallow status
        if is_still_disallowed:
            embed_color = EmbedColors.REJOIN_WARNING  # Red - still disallowed
            title = "🚨 Disallowed User Rejoined Server"
        else:
            embed_color = EmbedColors.REJOIN_CLEAN  # Gold - normal rejoin
            title = "🔄 User Rejoined Server"

        embed = discord.Embed(
            title=title,
            color=embed_color,
            description=f"**{member.display_name}** has rejoined the server"
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="User", value=f"{member.mention}", inline=True)
        embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True
        )

        # Add warning about previous moderation history
        if disallow_count > 0:
            embed.add_field(
                name="⚠️ Warning",
                value=f"User has **{disallow_count}** previous disallow(s) on record",
                inline=False
            )

        # If still disallowed, add prominent warning
        if is_still_disallowed and restriction_scopes:
            embed.add_field(
                name="🚫 STILL DISALLOWED",
                value=f"User rejoined while disallowed from: {', '.join(restriction_scopes)}\n"
                      f"Restriction is **still active** - leaving does not remove it!",
                inline=False
            )

        return embed

    @staticmethod
    def build_user_profile_embed(user: discord.Member) -> discord.Embed:
        """
        Build a detailed user profile embed for case threads.

        Args:
            user: The user to build the profile for

        Returns:
            Discord Embed with user profile info
        """
        embed = discord.Embed(
            title="📋 User Profile",
            color=EmbedColors.INFO
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Username", value=f"{user.name}", inline=True)
        embed.add_field(name="Display Name", value=f"{user.display_name}", inline=True)
        embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)

        # Discord account creation date
        embed.add_field(
            name="Discord Joined",
            value=f"<t:{int(user.created_at.timestamp())}:F>",
            inline=True
        )

        # Server join date (if available)
        if hasattr(user, 'joined_at') and user.joined_at:
            embed.add_field(
                name="Server Joined",
                value=f"<t:{int(user.joined_at.timestamp())}:F>",
                inline=True
            )

        # Account age
        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        account_age = CaseEmbedBuilder.format_age(created_at, now)
        embed.add_field(name="Account Age", value=account_age, inline=True)

        return embed

    @staticmethod
    def build_repeat_offender_embed(
        user: discord.Member,
        ban_count: int
    ) -> discord.Embed:
        """
        Build a repeat offender escalation embed.

        Args:
            user: The repeat offender
            ban_count: Number of bans for this user

        Returns:
            Discord Embed for repeat offender alert
        """
        embed = discord.Embed(
            title="⚠️ Repeat Offender Alert",
            color=EmbedColors.CLOSE,
            description=f"**{user.display_name}** has been disallowed **{ban_count} times**."
        )
        embed.add_field(
            name="Recommendation",
            value="Consider a **permanent disallow** for this user.\n"
                  f"Use: `/disallow user:{user.id} duration:permanent`",
            inline=False
        )
        embed.set_footer(text="This alert triggers at 3+ disallows when not permanent")
        return embed

    @staticmethod
    def format_age(start: datetime, end: datetime) -> str:
        """
        Format age as years, months, and days.

        Args:
            start: Start datetime
            end: End datetime

        Returns:
            Formatted string like "1y 6m 15d" or "6m 15d" or "15d"
        """
        # Calculate the difference
        total_days = (end - start).days

        years = total_days // 365
        remaining_days = total_days % 365
        months = remaining_days // 30
        days = remaining_days % 30

        parts = []
        if years > 0:
            parts.append(f"{years}y")
        if months > 0:
            parts.append(f"{months}m")
        if days > 0 or not parts:  # Always show days if nothing else
            parts.append(f"{days}d")

        return " ".join(parts)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseEmbedBuilder"]
