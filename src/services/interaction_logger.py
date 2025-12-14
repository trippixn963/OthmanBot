"""
OthmanBot - Interaction Logger Service
======================================

Logs all bot interactions to a Discord channel in the mods server.

Tracked interactions:
- Slash command usage
- Debate creation/deletion
- Karma changes
- Ban/unban actions
- Any other bot interactions

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import aiohttp
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import NY_TZ

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

# Logging webhook URL for mods server (loaded from environment)
LOG_WEBHOOK_URL = os.getenv("LOG_WEBHOOK_URL", "")

# Colors for different event types
COLOR_SUCCESS = 0x00FF00    # Green
COLOR_ERROR = 0xFF0000      # Red
COLOR_COMMAND = 0x5865F2    # Discord blurple
COLOR_KARMA = 0xFFD700      # Gold
COLOR_BAN = 0xFF4500        # Orange-red
COLOR_DEBATE = 0x3498DB     # Blue
COLOR_INFO = 0x9B59B6       # Purple
COLOR_NEWS = 0x1ABC9C       # Teal
COLOR_HOT = 0xFF6B6B        # Coral/Hot
COLOR_REACTION = 0xE67E22   # Orange
COLOR_ACCESS = 0x9B59B6     # Purple
COLOR_CLEANUP = 0x95A5A6    # Gray
COLOR_LEADERBOARD = 0xF1C40F  # Yellow/Gold


# =============================================================================
# Interaction Logger Service
# =============================================================================

class InteractionLogger:
    """Logs bot interactions via webhook."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _send_log(self, embed: discord.Embed) -> None:
        """Send a log embed via webhook."""
        if not LOG_WEBHOOK_URL:
            return

        try:
            session = await self._get_session()

            # Convert embed to dict for webhook
            embed_dict = embed.to_dict()

            payload = {
                "embeds": [embed_dict]
            }

            async with session.post(LOG_WEBHOOK_URL, json=payload) as resp:
                if resp.status not in (200, 204):
                    logger.warning("Interaction Webhook Error", [
                        ("Status", str(resp.status)),
                        ("Action", "Log not delivered"),
                    ])
        except Exception as e:
            logger.warning("Interaction Webhook Failed", [
                ("Error", str(e)),
                ("Action", "Log not delivered"),
            ])

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    # =========================================================================
    # Command Events
    # =========================================================================

    async def log_command(
        self,
        interaction: discord.Interaction,
        command_name: str,
        success: bool = True,
        error: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log when a slash command is used."""
        user = interaction.user

        # Color and status based on success
        if success:
            color = COLOR_COMMAND
            status = "✅ Success"
        else:
            color = COLOR_ERROR
            status = "❌ Failed"

        # Get NY_TZ time
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title=f"⚡ /{command_name}",
            color=color,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Add any command arguments
        if kwargs:
            args_str = " • ".join([f"**{k}:** `{v}`" for k, v in kwargs.items()])
            embed.add_field(name="Args", value=args_str, inline=False)

        # Add error info if failed
        if error:
            embed.add_field(name="Error", value=f"```{error[:200]}```", inline=False)

        # Add channel link if available
        if interaction.channel and interaction.guild:
            channel_name = getattr(interaction.channel, 'name', 'Unknown')
            channel_link = f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}"
            embed.add_field(name="Channel", value=f"[#{channel_name}]({channel_link})", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Debate Events
    # =========================================================================

    async def log_debate_created(
        self,
        thread: discord.Thread,
        creator: discord.Member,
        debate_number: int,
        title: str
    ) -> None:
        """Log when a debate thread is created."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="📝 Debate Created",
            color=COLOR_DEBATE,
        )
        embed.set_thumbnail(url=creator.display_avatar.url)
        embed.add_field(name="Creator", value=f"{creator.mention} `[{creator.id}]`", inline=True)
        embed.add_field(name="Number", value=f"`#{debate_number}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Title", value=f"`{title[:50]}{'...' if len(title) > 50 else ''}`", inline=False)

        # Thread link
        if thread.guild:
            thread_link = f"https://discord.com/channels/{thread.guild.id}/{thread.id}"
            embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

        await self._send_log(embed)

    async def log_debate_deleted(
        self,
        thread_id: int,
        thread_name: str,
        deleted_by: Optional[discord.Member] = None
    ) -> None:
        """Log when a debate thread is deleted."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🗑️ Debate Deleted",
            color=COLOR_ERROR,
        )

        if deleted_by:
            embed.set_thumbnail(url=deleted_by.display_avatar.url)
            embed.add_field(name="Deleted By", value=f"{deleted_by.mention} `[{deleted_by.id}]`", inline=True)

        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Title", value=f"`{thread_name[:50]}{'...' if len(thread_name) > 50 else ''}`", inline=False)

        await self._send_log(embed)

    # =========================================================================
    # Karma Events
    # =========================================================================

    async def log_karma_change(
        self,
        user: discord.User,
        voter: discord.User,
        change: int,
        new_total: int,
        thread_name: str
    ) -> None:
        """Log when karma is given/removed."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        is_upvote = change > 0
        emoji = "⬆️" if is_upvote else "⬇️"
        action = "Upvote" if is_upvote else "Downvote"

        embed = discord.Embed(
            title=f"{emoji} Karma {action}",
            color=COLOR_KARMA,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Recipient", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Voter", value=f"{voter.mention}", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Change", value=f"`{'+' if change > 0 else ''}{change}`", inline=True)
        embed.add_field(name="New Total", value=f"`{new_total}`", inline=True)
        embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Ban Events
    # =========================================================================

    async def log_user_banned(
        self,
        user: discord.User,
        banned_by: discord.User,
        scope: str,
        thread_id: Optional[int] = None
    ) -> None:
        """Log when a user is banned from debates."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🚫 User Banned from Debates",
            color=COLOR_BAN,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Banned User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Banned By", value=f"{banned_by.mention}", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Scope", value=f"`{scope}`", inline=True)

        if thread_id:
            embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)

        await self._send_log(embed)

    async def log_user_unbanned(
        self,
        user_id: int,
        unbanned_by: discord.User,
        scope: str,
        display_name: str
    ) -> None:
        """Log when a user is unbanned from debates."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="✅ User Unbanned from Debates",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="Unbanned User", value=f"`{display_name}` `[{user_id}]`", inline=True)
        embed.add_field(name="Unbanned By", value=f"{unbanned_by.mention}", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Scope", value=f"`{scope}`", inline=True)

        await self._send_log(embed)

    async def log_ban_expired(
        self,
        user_id: int,
        scope: str,
        display_name: str
    ) -> None:
        """Log when a user's ban expires automatically."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="⏰ Ban Expired (Auto-Unban)",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="User", value=f"`{display_name}` `[{user_id}]`", inline=True)
        embed.add_field(name="Scope", value=f"`{scope}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # News/Content Events
    # =========================================================================

    async def log_news_posted(
        self,
        content_type: str,
        title: str,
        channel_name: str,
        source: Optional[str] = None,
        thread_link: Optional[str] = None
    ) -> None:
        """Log when news/content is posted."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        emoji_map = {
            "news": "📰",
            "soccer": "⚽",
            "gaming": "🎮",
        }
        emoji = emoji_map.get(content_type, "📄")

        embed = discord.Embed(
            title=f"{emoji} {content_type.title()} Posted",
            color=COLOR_NEWS,
        )
        embed.add_field(name="Title", value=f"`{title[:50]}{'...' if len(title) > 50 else ''}`", inline=False)
        embed.add_field(name="Channel", value=f"`{channel_name}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        if source:
            embed.add_field(name="Source", value=f"`{source[:30]}`", inline=True)

        if thread_link:
            embed.add_field(name="Link", value=f"[View Post]({thread_link})", inline=True)

        await self._send_log(embed)

    async def log_hot_debate_posted(
        self,
        debate_title: str,
        hotness_score: float,
        channel_name: str,
        thread_link: Optional[str] = None
    ) -> None:
        """Log when a hot debate is posted to general."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🔥 Hot Debate Posted",
            color=COLOR_HOT,
        )
        embed.add_field(name="Debate", value=f"`{debate_title[:50]}{'...' if len(debate_title) > 50 else ''}`", inline=False)
        embed.add_field(name="Hotness", value=f"`{hotness_score:.1f}`", inline=True)
        embed.add_field(name="Channel", value=f"`{channel_name}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        if thread_link:
            embed.add_field(name="Link", value=f"[View Post]({thread_link})", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Reaction Events
    # =========================================================================

    async def log_vote_reactions_added(
        self,
        user: discord.User,
        thread_name: str,
        message_id: int,
        content_length: int
    ) -> None:
        """Log when vote reactions are added to a message."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🗳️ Vote Reactions Added",
            color=COLOR_REACTION,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Author", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Length", value=f"`{content_length}` chars", inline=True)
        embed.add_field(name="Message ID", value=f"`{message_id}`", inline=True)

        await self._send_log(embed)

    async def log_self_vote_blocked(
        self,
        user: discord.User,
        thread_name: str,
        vote_type: str
    ) -> None:
        """Log when a self-vote is blocked."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🚫 Self-Vote Blocked",
            color=COLOR_ERROR,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Type", value=f"`{vote_type}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Access Control Events
    # =========================================================================

    async def log_access_blocked(
        self,
        user: discord.User,
        thread_name: str,
        reason: str
    ) -> None:
        """Log when a user is blocked from posting (no participation react)."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🔐 Access Blocked",
            color=COLOR_ACCESS,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        await self._send_log(embed)

    async def log_banned_user_message_deleted(
        self,
        user: discord.User,
        thread_name: str,
        content_preview: str
    ) -> None:
        """Log when a banned user's message is deleted."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🚫 Banned User Message Deleted",
            color=COLOR_BAN,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)
        embed.add_field(name="Preview", value=f"```{content_preview[:100]}```", inline=False)

        await self._send_log(embed)

    # =========================================================================
    # Member Events
    # =========================================================================

    async def log_member_leave_cleanup(
        self,
        user_name: str,
        user_id: int,
        threads_deleted: int,
        messages_deleted: int,
        reactions_removed: int,
        karma_reset: int
    ) -> None:
        """Log when a member leaves and their data is cleaned up."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="👋 Member Left - Cleanup Complete",
            color=COLOR_CLEANUP,
        )
        embed.add_field(name="User", value=f"`{user_name}` `[{user_id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Threads Deleted", value=f"`{threads_deleted}`", inline=True)
        embed.add_field(name="Messages Deleted", value=f"`{messages_deleted}`", inline=True)
        embed.add_field(name="Reactions Removed", value=f"`{reactions_removed}`", inline=True)
        embed.add_field(name="Karma Reset", value=f"`{karma_reset}`", inline=True)

        await self._send_log(embed)

    async def log_member_rejoin(
        self,
        member: discord.Member
    ) -> None:
        """Log when a member rejoins the server."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🔄 Member Rejoined",
            color=COLOR_SUCCESS,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member.mention} `[{member.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Hot Tag Events
    # =========================================================================

    async def log_hot_tag_added(
        self,
        thread_name: str,
        thread_id: int,
        reason: str
    ) -> None:
        """Log when Hot tag is added to a debate."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🔥 Hot Tag Added",
            color=COLOR_HOT,
        )
        embed.add_field(name="Thread", value=f"`{thread_name[:40]}{'...' if len(thread_name) > 40 else ''}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        await self._send_log(embed)

    async def log_hot_tag_removed(
        self,
        thread_name: str,
        thread_id: int,
        reason: str
    ) -> None:
        """Log when Hot tag is removed from a debate."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="❄️ Hot Tag Removed",
            color=COLOR_CLEANUP,
        )
        embed.add_field(name="Thread", value=f"`{thread_name[:40]}{'...' if len(thread_name) > 40 else ''}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        await self._send_log(embed)

    # =========================================================================
    # Leaderboard Events
    # =========================================================================

    async def log_leaderboard_updated(
        self,
        top_monthly: list,
        top_alltime: list
    ) -> None:
        """Log when the leaderboard is updated."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="📊 Leaderboard Updated",
            color=COLOR_LEADERBOARD,
        )
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Format top monthly
        if top_monthly:
            monthly_str = "\n".join([f"{i+1}. {name}" for i, (name, _) in enumerate(top_monthly[:3])])
            embed.add_field(name="Top Monthly", value=f"```{monthly_str}```", inline=False)

        # Format top all-time
        if top_alltime:
            alltime_str = "\n".join([f"{i+1}. {name}" for i, (name, _) in enumerate(top_alltime[:3])])
            embed.add_field(name="Top All-Time", value=f"```{alltime_str}```", inline=False)

        await self._send_log(embed)

    # =========================================================================
    # Non-English Title Events
    # =========================================================================

    async def log_non_english_title_blocked(
        self,
        creator: discord.User,
        original_title: str,
        suggested_title: str,
        thread_id: int
    ) -> None:
        """Log when a non-English title debate is blocked."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title="🌐 Non-English Title Blocked",
            color=COLOR_ERROR,
        )
        embed.set_thumbnail(url=creator.display_avatar.url)
        embed.add_field(name="Creator", value=f"{creator.mention} `[{creator.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Original", value=f"`{original_title[:40]}{'...' if len(original_title) > 40 else ''}`", inline=False)
        embed.add_field(name="Suggested", value=f"`{suggested_title[:40]}{'...' if len(suggested_title) > 40 else ''}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Generic Events
    # =========================================================================

    async def log_event(
        self,
        title: str,
        description: Optional[str] = None,
        user: Optional[discord.User] = None,
        color: int = COLOR_INFO,
        success: bool = True,
        **fields
    ) -> None:
        """Log a generic event."""
        # Add status emoji to title
        status = "✅" if success else "❌"

        # Get NY_TZ time
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p NY_TZ")

        embed = discord.Embed(
            title=f"{title} {status}",
            description=description,
            color=color if success else COLOR_ERROR,
        )

        if user:
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)

        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        for name, value in fields.items():
            embed.add_field(name=name, value=value, inline=True)

        await self._send_log(embed)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["InteractionLogger"]
