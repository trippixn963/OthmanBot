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

# Webhook request timeout (seconds)
WEBHOOK_TIMEOUT = aiohttp.ClientTimeout(total=10)

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
        """Get or create aiohttp session with timeout."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=WEBHOOK_TIMEOUT)
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
        message_id: Optional[int] = None,
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
        time_str = now_est.strftime("%I:%M %p EST")

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

        # Add channel/message link if available
        if interaction.channel and interaction.guild:
            channel_name = getattr(interaction.channel, 'name', 'Unknown')
            if message_id:
                # Link directly to the message
                message_link = f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{message_id}"
                embed.add_field(name="Channel", value=f"[#{channel_name}]({message_link})", inline=True)
            else:
                # Link to channel only
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
        time_str = now_est.strftime("%I:%M %p EST")

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
        time_str = now_est.strftime("%I:%M %p EST")

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
        thread_name: str,
        guild_id: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> None:
        """Log when karma is given/removed."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

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

        # Thread link if available
        if guild_id and thread_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[{thread_name[:25]}{'...' if len(thread_name) > 25 else ''}]({thread_link})", inline=True)
        else:
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
        thread_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        message_id: Optional[int] = None,
        duration: Optional[str] = None,
        reason: Optional[str] = None
    ) -> None:
        """Log when a user is banned from debates."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🚫 User Banned from Debates",
            color=COLOR_BAN,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Banned User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Banned By", value=f"{banned_by.mention}", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Scope", value=f"`{scope}`", inline=True)

        if duration:
            embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        if thread_id:
            embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)

        # Add message link if available
        if guild_id and channel_id and message_id:
            message_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            embed.add_field(name="Message", value=f"[Jump to Message]({message_link})", inline=True)

        if reason:
            reason_display = reason[:500] + "..." if len(reason) > 500 else reason
            embed.add_field(name="Reason", value=reason_display, inline=False)

        await self._send_log(embed)

    async def log_user_unbanned(
        self,
        user_id: int,
        unbanned_by: discord.User,
        scope: str,
        display_name: str,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        message_id: Optional[int] = None
    ) -> None:
        """Log when a user is unbanned from debates."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="✅ User Unbanned from Debates",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="Unbanned User", value=f"`{display_name}` `[{user_id}]`", inline=True)
        embed.add_field(name="Unbanned By", value=f"{unbanned_by.mention}", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Scope", value=f"`{scope}`", inline=True)

        # Add message link if available
        if guild_id and channel_id and message_id:
            message_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            embed.add_field(name="Message", value=f"[Jump to Message]({message_link})", inline=True)

        await self._send_log(embed)

    async def log_ban_expired(
        self,
        user_id: int,
        scope: str,
        display_name: str,
        guild_id: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> None:
        """Log when a user's ban expires automatically."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="⏰ Ban Expired (Auto-Unban)",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="User", value=f"`{display_name}` `[{user_id}]`", inline=True)
        embed.add_field(name="Scope", value=f"`{scope}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Add thread link if this was a thread-specific ban
        if guild_id and thread_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

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
        time_str = now_est.strftime("%I:%M %p EST")

        emoji_map = {
            "news": "📰",
            "soccer": "⚽",
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
        time_str = now_est.strftime("%I:%M %p EST")

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
        content_length: int,
        guild_id: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> None:
        """Log when vote reactions are added to a message."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🗳️ Vote Reactions Added",
            color=COLOR_REACTION,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Author", value=f"{user.mention} `[{user.id}]`", inline=True)

        # Thread link if available
        if guild_id and thread_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[{thread_name[:25]}{'...' if len(thread_name) > 25 else ''}]({thread_link})", inline=True)
        else:
            embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)

        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Length", value=f"`{content_length}` chars", inline=True)

        # Message link if available
        if guild_id and thread_id:
            msg_link = f"https://discord.com/channels/{guild_id}/{thread_id}/{message_id}"
            embed.add_field(name="Message", value=f"[Jump]({msg_link})", inline=True)
        else:
            embed.add_field(name="Message ID", value=f"`{message_id}`", inline=True)

        await self._send_log(embed)

    async def log_self_vote_blocked(
        self,
        user: discord.User,
        thread_name: str,
        vote_type: str,
        guild_id: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> None:
        """Log when a self-vote is blocked."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🚫 Self-Vote Blocked",
            color=COLOR_ERROR,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Type", value=f"`{vote_type}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Thread link if available
        if guild_id and thread_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[{thread_name[:25]}{'...' if len(thread_name) > 25 else ''}]({thread_link})", inline=True)
        else:
            embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Access Control Events
    # =========================================================================

    async def log_access_blocked(
        self,
        user: discord.User,
        thread_name: str,
        reason: str,
        guild_id: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> None:
        """Log when a user is blocked from posting (no participation react)."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🔐 Access Blocked",
            color=COLOR_ACCESS,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Thread link if available
        if guild_id and thread_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[{thread_name[:25]}{'...' if len(thread_name) > 25 else ''}]({thread_link})", inline=True)
        else:
            embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)

        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        await self._send_log(embed)

    async def log_banned_user_message_deleted(
        self,
        user: discord.User,
        thread_name: str,
        content_preview: str,
        guild_id: Optional[int] = None,
        thread_id: Optional[int] = None
    ) -> None:
        """Log when a banned user's message is deleted."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🚫 Banned User Message Deleted",
            color=COLOR_BAN,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Thread link if available
        if guild_id and thread_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[{thread_name[:25]}{'...' if len(thread_name) > 25 else ''}]({thread_link})", inline=True)
        else:
            embed.add_field(name="Thread", value=f"`{thread_name[:30]}{'...' if len(thread_name) > 30 else ''}`", inline=True)

        embed.add_field(name="Preview", value=f"```{content_preview[:100]}```", inline=False)

        await self._send_log(embed)

    # =========================================================================
    # Member Events
    # =========================================================================

    async def log_debate_participant_left(
        self,
        user_name: str,
        user_id: int,
        user_avatar_url: Optional[str],
        karma: int,
        debates_participated: int,
        debates_created: int,
        votes_removed: int = 0,
        case_id: Optional[int] = None
    ) -> None:
        """Log when a debate participant leaves the server."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="👋 Debate Participant Left",
            color=COLOR_CLEANUP,
            description=f"**{user_name}** has left the server"
        )

        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)

        embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Karma", value=f"`{karma}` (preserved)", inline=True)

        # Participation stats
        embed.add_field(name="Debates Participated", value=f"`{debates_participated}`", inline=True)
        embed.add_field(name="Debates Created", value=f"`{debates_created}`", inline=True)

        # Votes removed (their votes on others no longer count)
        if votes_removed > 0:
            embed.add_field(name="Votes Removed", value=f"`{votes_removed}` (reversed)", inline=True)

        # Case ID if they have one
        if case_id:
            embed.add_field(name="Case ID", value=f"`[{case_id:04d}]`", inline=True)

        await self._send_log(embed)

    async def log_debate_participant_rejoined(
        self,
        member: discord.Member,
        debates_participated: int,
        debates_created: int,
        case_id: Optional[int] = None
    ) -> None:
        """Log when a debate participant rejoins the server."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🔄 Debate Participant Rejoined",
            color=COLOR_SUCCESS,
            description=f"**{member.name}** has rejoined the server"
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="User", value=f"{member.mention}", inline=True)
        embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Previous participation stats (from before they left)
        embed.add_field(name="Previous Debates", value=f"`{debates_participated}`", inline=True)
        embed.add_field(name="Previous Created", value=f"`{debates_created}`", inline=True)

        # Case ID if they have one
        if case_id:
            embed.add_field(name="Case ID", value=f"`[{case_id:04d}]`", inline=True)
            embed.add_field(name="⚠️ Note", value="User has moderation history", inline=False)

        await self._send_log(embed)

    async def log_potential_ban_evasion(
        self,
        member: discord.Member,
        account_age_days: int,
        thread_name: str,
        developer_id: int
    ) -> None:
        """
        Alert about potential ban evasion - new account posting in debates.

        Args:
            member: The suspicious member
            account_age_days: How old their account is in days
            thread_name: The debate thread they posted in
            developer_id: Developer ID to ping
        """
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🚨 Potential Ban Evasion Detected",
            color=0xFF0000,  # Red - high priority
            description=f"**New account** posting in debates"
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="User", value=f"{member.mention}", inline=True)
        embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Account Age", value=f"`{account_age_days} days`", inline=True)

        # Account creation date
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(member.created_at.timestamp())}:F>",
            inline=True
        )

        # Server join date
        if member.joined_at:
            embed.add_field(
                name="Server Joined",
                value=f"<t:{int(member.joined_at.timestamp())}:R>",
                inline=True
            )

        embed.add_field(name="Thread", value=f"`{thread_name[:40]}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Warning message
        embed.add_field(
            name="⚠️ Action Required",
            value="Review this user's activity. New accounts immediately participating in debates may be evading a previous ban.",
            inline=False
        )

        # Send with developer ping
        await self._send_log_with_content(embed, f"<@{developer_id}>")

    async def _send_log_with_content(self, embed: discord.Embed, content: str = "") -> None:
        """Send a log embed via webhook with optional text content (for pings)."""
        if not LOG_WEBHOOK_URL:
            return

        try:
            session = await self._get_session()

            embed_dict = embed.to_dict()

            payload = {
                "content": content,
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

    # =========================================================================
    # Hot Tag Events
    # =========================================================================

    async def log_hot_tag_added(
        self,
        thread_name: str,
        thread_id: int,
        reason: str,
        guild_id: Optional[int] = None
    ) -> None:
        """Log when Hot tag is added to a debate."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🔥 Hot Tag Added",
            color=COLOR_HOT,
        )

        # Thread link if available
        if guild_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[{thread_name[:35]}{'...' if len(thread_name) > 35 else ''}]({thread_link})", inline=False)
        else:
            embed.add_field(name="Thread", value=f"`{thread_name[:40]}{'...' if len(thread_name) > 40 else ''}`", inline=False)

        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        await self._send_log(embed)

    async def log_hot_tag_removed(
        self,
        thread_name: str,
        thread_id: int,
        reason: str,
        guild_id: Optional[int] = None
    ) -> None:
        """Log when Hot tag is removed from a debate."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="❄️ Hot Tag Removed",
            color=COLOR_CLEANUP,
        )

        # Thread link if available
        if guild_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[{thread_name[:35]}{'...' if len(thread_name) > 35 else ''}]({thread_link})", inline=False)
        else:
            embed.add_field(name="Thread", value=f"`{thread_name[:40]}{'...' if len(thread_name) > 40 else ''}`", inline=False)

        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        await self._send_log(embed)

    async def log_hot_tag_evaluation_summary(
        self,
        stats: dict,
        duration: float,
        added_threads: list,
        removed_threads: list
    ) -> None:
        """Log the daily hot tag evaluation summary."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")
        date_str = now_est.strftime("%Y-%m-%d")

        embed = discord.Embed(
            title="🔥 Daily Hot Tag Evaluation Complete",
            color=COLOR_HOT,
            description=f"**Date:** {date_str}\n**Duration:** {duration:.1f}s"
        )

        # Statistics
        total_checked = stats.get("active_checked", 0) + stats.get("archived_checked", 0)
        embed.add_field(
            name="📊 Statistics",
            value=(
                f"**Threads Checked:** {total_checked}\n"
                f"• Active: {stats.get('active_checked', 0)}\n"
                f"• Archived: {stats.get('archived_checked', 0)}"
            ),
            inline=True
        )

        embed.add_field(
            name="🏷️ Tag Changes",
            value=(
                f"**Added:** {stats.get('added', 0)}\n"
                f"**Removed:** {stats.get('removed', 0)}\n"
                f"**Kept:** {stats.get('kept', 0)}"
            ),
            inline=True
        )

        embed.add_field(
            name="⏭️ Skipped",
            value=(
                f"**No Hot Tag:** {stats.get('skipped_no_change', 0)}\n"
                f"**Deprecated:** {stats.get('skipped_deprecated', 0)}\n"
                f"**Errors:** {stats.get('errors', 0)}"
            ),
            inline=True
        )

        # List threads that gained hot tag
        if added_threads:
            added_preview = ", ".join(added_threads[:5])
            if len(added_threads) > 5:
                added_preview += f" (+{len(added_threads) - 5} more)"
            embed.add_field(
                name=f"🔥 Gained Hot Tag ({len(added_threads)})",
                value=f"`{added_preview}`",
                inline=False
            )

        # List threads that lost hot tag
        if removed_threads:
            removed_preview = ", ".join(removed_threads[:5])
            if len(removed_threads) > 5:
                removed_preview += f" (+{len(removed_threads) - 5} more)"
            embed.add_field(
                name=f"❄️ Lost Hot Tag ({len(removed_threads)})",
                value=f"`{removed_preview}`",
                inline=False
            )

        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

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
        time_str = now_est.strftime("%I:%M %p EST")

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
        thread_id: int,
        guild_id: Optional[int] = None
    ) -> None:
        """Log when a non-English title debate is blocked."""
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🌐 Non-English Title Blocked",
            color=COLOR_ERROR,
        )
        embed.set_thumbnail(url=creator.display_avatar.url)
        embed.add_field(name="Creator", value=f"{creator.mention} `[{creator.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Original", value=f"`{original_title[:40]}{'...' if len(original_title) > 40 else ''}`", inline=False)
        embed.add_field(name="Suggested", value=f"`{suggested_title[:40]}{'...' if len(suggested_title) > 40 else ''}`", inline=False)

        # Thread link if available
        if guild_id:
            thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
            embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)
        else:
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
        time_str = now_est.strftime("%I:%M %p EST")

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

    async def log_startup_reconciliation(
        self,
        karma_stats: Optional[dict] = None,
        numbering_stats: Optional[dict] = None,
        karma_success: bool = True,
        numbering_success: bool = True
    ) -> None:
        """
        Log combined startup reconciliation results (karma + numbering).

        Args:
            karma_stats: Karma reconciliation stats dict
            numbering_stats: Numbering reconciliation stats dict
            karma_success: Whether karma reconciliation succeeded
            numbering_success: Whether numbering reconciliation succeeded
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        # Determine overall status
        all_success = karma_success and numbering_success
        any_changes = False

        if karma_stats:
            any_changes = any_changes or karma_stats.get('votes_added', 0) > 0 or karma_stats.get('votes_removed', 0) > 0
        if numbering_stats:
            any_changes = any_changes or numbering_stats.get('threads_renumbered', 0) > 0

        if all_success:
            if any_changes:
                title = "🔄 Startup Reconciliation Complete (Changes Made)"
                color = COLOR_KARMA
            else:
                title = "✅ Startup Reconciliation Complete"
                color = COLOR_SUCCESS
        else:
            title = "⚠️ Startup Reconciliation (Partial Failure)"
            color = COLOR_ERROR

        embed = discord.Embed(
            title=title,
            color=color,
        )

        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Karma section
        if karma_stats:
            karma_status = "✅" if karma_success else "❌"
            threads = karma_stats.get('threads_scanned', 0)
            messages = karma_stats.get('messages_scanned', 0)
            votes_added = karma_stats.get('votes_added', 0)
            votes_removed = karma_stats.get('votes_removed', 0)

            karma_value = f"{karma_status} `{threads}` threads, `{messages}` msgs"
            if votes_added > 0 or votes_removed > 0:
                karma_value += f"\n+{votes_added}/-{votes_removed} votes"

            embed.add_field(name="🗳️ Karma", value=karma_value, inline=True)

        # Numbering section
        if numbering_stats:
            numbering_status = "✅" if numbering_success else "❌"
            threads = numbering_stats.get('threads_scanned', 0)
            gaps = numbering_stats.get('gaps_found', 0)
            renumbered = numbering_stats.get('threads_renumbered', 0)

            if gaps > 0:
                numbering_value = f"{numbering_status} `{threads}` threads\n`{gaps}` gaps fixed"
            else:
                numbering_value = f"{numbering_status} `{threads}` threads\nNo gaps"

            embed.add_field(name="🔢 Numbering", value=numbering_value, inline=True)

        await self._send_log(embed)

    async def log_karma_reconciliation(
        self,
        trigger: str,
        stats: dict,
        success: bool = True
    ) -> None:
        """
        Log karma reconciliation results.

        Args:
            trigger: What triggered the reconciliation ("Startup", "Nightly", etc.)
            stats: Reconciliation stats dict
            success: Whether reconciliation succeeded
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        threads_scanned = stats.get('threads_scanned', 0)
        messages_scanned = stats.get('messages_scanned', 0)
        votes_added = stats.get('votes_added', 0)
        votes_removed = stats.get('votes_removed', 0)
        reactions_fixed = stats.get('reactions_fixed', 0)
        errors = stats.get('errors', 0)

        # Determine if any changes were made
        changes_made = votes_added > 0 or votes_removed > 0 or reactions_fixed > 0

        if success:
            if changes_made:
                title = "🔄 Karma Reconciliation Complete (Changes Made)"
                color = COLOR_KARMA
            else:
                title = "✅ Karma Reconciliation Complete (No Changes)"
                color = COLOR_SUCCESS
        else:
            title = "❌ Karma Reconciliation Failed"
            color = COLOR_ERROR

        embed = discord.Embed(
            title=title,
            color=color,
        )

        embed.add_field(name="Trigger", value=f"`{trigger}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Threads Scanned", value=f"`{threads_scanned}`", inline=True)
        embed.add_field(name="Messages Scanned", value=f"`{messages_scanned}`", inline=True)
        embed.add_field(name="Votes Added", value=f"`+{votes_added}`", inline=True)
        embed.add_field(name="Votes Removed", value=f"`-{votes_removed}`", inline=True)

        if reactions_fixed > 0:
            embed.add_field(name="Reactions Fixed", value=f"`{reactions_fixed}`", inline=True)

        if errors > 0:
            embed.add_field(name="Errors", value=f"`{errors}`", inline=True)

        await self._send_log(embed)

    async def log_numbering_reconciliation(
        self,
        trigger: str,
        stats: dict,
        success: bool = True
    ) -> None:
        """
        Log numbering reconciliation results.

        Args:
            trigger: What triggered the reconciliation ("Startup", "Nightly", etc.)
            stats: Reconciliation stats dict
            success: Whether reconciliation succeeded
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        threads_scanned = stats.get('threads_scanned', 0)
        gaps_found = stats.get('gaps_found', 0)
        threads_renumbered = stats.get('threads_renumbered', 0)
        errors = stats.get('errors', 0)

        # Determine if any changes were made
        changes_made = threads_renumbered > 0

        if success:
            if changes_made:
                title = "🔢 Numbering Reconciliation Complete (Gaps Fixed)"
                color = COLOR_DEBATE
            else:
                title = "✅ Numbering Reconciliation Complete (No Gaps)"
                color = COLOR_SUCCESS
        else:
            title = "❌ Numbering Reconciliation Failed"
            color = COLOR_ERROR

        embed = discord.Embed(
            title=title,
            color=color,
        )

        embed.add_field(name="Trigger", value=f"`{trigger}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Threads Scanned", value=f"`{threads_scanned}`", inline=True)

        if gaps_found > 0:
            embed.add_field(name="Gaps Found", value=f"`{gaps_found}`", inline=True)
            embed.add_field(name="Threads Renumbered", value=f"`{threads_renumbered}`", inline=True)

        if errors > 0:
            embed.add_field(name="Errors", value=f"`{errors}`", inline=True)

        await self._send_log(embed)

    async def log_orphan_vote_cleanup(
        self,
        stats: dict
    ) -> None:
        """
        Log orphan vote cleanup results.

        Args:
            stats: Cleanup stats dict with orphans_found, votes_cleaned, karma_reversed, errors
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        orphans_found = stats.get('orphans_found', 0)
        votes_cleaned = stats.get('votes_cleaned', 0)
        karma_reversed = stats.get('karma_reversed', 0)
        errors = stats.get('errors', 0)

        # Only log if orphans were found or there were errors
        if orphans_found == 0 and errors == 0:
            return

        if orphans_found > 0:
            title = "🧹 Orphan Vote Cleanup Complete"
            color = COLOR_DEBATE
        elif errors > 0:
            title = "⚠️ Orphan Vote Cleanup Had Errors"
            color = COLOR_ERROR
        else:
            title = "✅ Orphan Vote Cleanup Complete (No Orphans)"
            color = COLOR_SUCCESS

        embed = discord.Embed(
            title=title,
            color=color,
        )

        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        if orphans_found > 0:
            embed.add_field(name="Orphan Messages", value=f"`{orphans_found}`", inline=True)
            embed.add_field(name="Votes Cleaned", value=f"`{votes_cleaned}`", inline=True)
            embed.add_field(name="Karma Reversed", value=f"`{karma_reversed}`", inline=True)

        if errors > 0:
            embed.add_field(name="Errors", value=f"`{errors}`", inline=True)

        await self._send_log(embed)

    async def log_debate_closed(
        self,
        thread: discord.Thread,
        closed_by: discord.Member,
        owner: Optional[discord.Member],
        original_name: str,
        reason: str
    ) -> None:
        """
        Log when a debate is closed by a moderator.

        Args:
            thread: The debate thread that was closed
            closed_by: The moderator who closed the debate
            owner: The owner of the debate (may be None if not found)
            original_name: Original thread name before [CLOSED] prefix
            reason: Reason for closing the debate
        """
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🔒 Debate Closed",
            color=COLOR_BAN,
        )
        embed.set_thumbnail(url=closed_by.display_avatar.url)
        embed.add_field(name="Closed By", value=f"{closed_by.mention} `[{closed_by.id}]`", inline=True)

        if owner:
            embed.add_field(name="Owner", value=f"{owner.mention} `[{owner.id}]`", inline=True)
        else:
            embed.add_field(name="Owner", value="`Unknown`", inline=True)

        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Debate", value=f"`{original_name[:50]}{'...' if len(original_name) > 50 else ''}`", inline=False)
        embed.add_field(name="Reason", value=reason[:200] if len(reason) > 200 else reason, inline=False)

        # Thread link
        if thread.guild:
            thread_link = f"https://discord.com/channels/{thread.guild.id}/{thread.id}"
            embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

        embed.add_field(name="Thread ID", value=f"`{thread.id}`", inline=True)

        await self._send_log(embed)

    async def log_debate_reopened(
        self,
        thread: discord.Thread,
        reopened_by: discord.Member,
        owner: Optional[discord.Member],
        original_name: str,
        new_name: str,
        reason: str
    ) -> None:
        """
        Log when a debate is reopened by a moderator.

        Args:
            thread: The debate thread that was reopened
            reopened_by: The moderator who reopened the debate
            owner: The owner of the debate (may be None if not found)
            original_name: Thread name before reopening (with [CLOSED])
            new_name: Thread name after reopening
            reason: Reason for reopening the debate
        """
        now_est = datetime.now(NY_TZ)
        time_str = now_est.strftime("%I:%M %p EST")

        embed = discord.Embed(
            title="🔓 Debate Reopened",
            color=COLOR_SUCCESS,
        )
        embed.set_thumbnail(url=reopened_by.display_avatar.url)
        embed.add_field(name="Reopened By", value=f"{reopened_by.mention} `[{reopened_by.id}]`", inline=True)

        if owner:
            embed.add_field(name="Owner", value=f"{owner.mention} `[{owner.id}]`", inline=True)
        else:
            embed.add_field(name="Owner", value="`Unknown`", inline=True)

        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Debate", value=f"`{new_name[:50]}{'...' if len(new_name) > 50 else ''}`", inline=False)
        embed.add_field(name="Reason", value=reason[:200] if len(reason) > 200 else reason, inline=False)

        # Thread link
        if thread.guild:
            thread_link = f"https://discord.com/channels/{thread.guild.id}/{thread.id}"
            embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

        embed.add_field(name="Thread ID", value=f"`{thread.id}`", inline=True)

        await self._send_log(embed)

    async def log_ban_notification_dm(
        self,
        action: str,
        scope: str,
        success: bool,
        user: Optional[discord.User] = None,
        user_id: Optional[int] = None,
        moderator: Optional[discord.User] = None,
        duration: Optional[str] = None,
        thread_id: Optional[int] = None,
        reason: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Log ban notification DM attempt to webhook.

        Args:
            action: Type of notification ("ban", "unban", "expired")
            scope: Ban scope
            success: Whether DM was sent successfully
            user: The user object (if available)
            user_id: The user ID (fallback)
            moderator: The moderator who took the action
            duration: Ban duration (for ban)
            thread_id: Specific thread ID if applicable
            reason: Reason for the action
            error: Error message if failed
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        # Determine title and color based on action and success
        action_titles = {
            "ban": ("Ban", "🚫"),
            "unban": ("Unban", "✅"),
            "expired": ("Ban Expiry", "⏰")
        }
        action_name, action_emoji = action_titles.get(action, ("Action", "📬"))

        if success:
            title = f"{action_emoji} {action_name} DM Sent"
            color = COLOR_SUCCESS
        else:
            title = f"⚠️ {action_name} DM Failed"
            color = COLOR_ERROR

        embed = discord.Embed(
            title=title,
            color=color,
        )

        # User info
        if user:
            embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
            embed.set_thumbnail(url=user.display_avatar.url)
        elif user_id:
            embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)

        # Moderator (for ban/unban)
        if moderator:
            embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)

        # Action type
        embed.add_field(name="Action", value=f"`{action.upper()}`", inline=True)

        # Scope
        if thread_id:
            embed.add_field(name="Scope", value=f"`Thread`\n<#{thread_id}>", inline=True)
        else:
            embed.add_field(name="Scope", value=f"`{scope}`", inline=True)

        # Duration (for bans)
        if duration:
            embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        # Time
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        # Status
        embed.add_field(name="DM Status", value="`Sent`" if success else "`Failed`", inline=True)

        # Error (if failed)
        if error:
            embed.add_field(name="Error", value=f"`{error[:100]}`", inline=False)

        # Reason (if provided)
        if reason:
            embed.add_field(name="Reason", value=reason[:200], inline=False)

        await self._send_log(embed)

    async def log_appeal_button_clicked(
        self,
        user: discord.User,
        action_type: str,
        action_id: int,
        source: str,
        is_dm: bool,
    ) -> None:
        """
        Log when a user clicks the appeal button.

        Args:
            user: The user who clicked the button
            action_type: Type of action being appealed ('disallow' or 'close')
            action_id: ID of the action being appealed
            source: Where the button was clicked from (DM or channel name)
            is_dm: Whether clicked from DM
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        action_labels = {
            "disallow": "Ban Appeal",
            "close": "Thread Close Appeal",
        }
        action_label = action_labels.get(action_type, action_type.title())

        embed = discord.Embed(
            title=f"📝 Appeal Button Clicked",
            description=f"User started the appeal process for a **{action_label}**",
            color=COLOR_INFO,
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="Action Type", value=f"`{action_type}`", inline=True)
        embed.add_field(name="Action ID", value=f"`{action_id}`", inline=True)
        embed.add_field(name="Source", value=f"`{source}`", inline=True)
        embed.add_field(name="From DM", value="`Yes`" if is_dm else "`No`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        await self._send_log(embed)

    async def log_appeal_rejected_wrong_user(
        self,
        user: discord.User,
        expected_user_id: int,
        action_type: str,
        action_id: int,
        source: str,
        is_dm: bool,
    ) -> None:
        """
        Log when a user clicks an appeal button that's not theirs.

        Args:
            user: The user who clicked the button
            expected_user_id: The user ID who should have clicked
            action_type: Type of action being appealed ('disallow' or 'close')
            action_id: ID of the action being appealed
            source: Where the button was clicked from (DM or channel name)
            is_dm: Whether clicked from DM
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        action_labels = {
            "disallow": "Ban Appeal",
            "close": "Thread Close Appeal",
        }
        action_label = action_labels.get(action_type, action_type.title())

        embed = discord.Embed(
            title=f"🚫 Appeal Button Rejected",
            description=f"User tried to appeal a **{action_label}** that wasn't theirs",
            color=COLOR_ERROR,
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="Clicked By", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="Intended For", value=f"<@{expected_user_id}>\n`{expected_user_id}`", inline=True)
        embed.add_field(name="Action Type", value=f"`{action_type}`", inline=True)
        embed.add_field(name="Action ID", value=f"`{action_id}`", inline=True)
        embed.add_field(name="Source", value=f"`{source}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        await self._send_log(embed)

    async def log_appeal_submitted(
        self,
        user: discord.User,
        action_type: str,
        action_id: int,
        reason: str,
        appeal_id: int,
    ) -> None:
        """
        Log when an appeal is successfully submitted.

        Args:
            user: The user who submitted the appeal
            action_type: Type of action being appealed
            action_id: ID of the action being appealed
            reason: User's reason for appeal
            appeal_id: The created appeal ID
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        action_labels = {
            "disallow": "Ban Appeal",
            "close": "Thread Close Appeal",
        }
        action_label = action_labels.get(action_type, action_type.title())

        embed = discord.Embed(
            title=f"📨 Appeal Submitted",
            description=f"New **{action_label}** submitted for review",
            color=COLOR_KARMA,
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="Appeal ID", value=f"`#{appeal_id}`", inline=True)
        embed.add_field(name="Action Type", value=f"`{action_type}`", inline=True)
        embed.add_field(name="Action ID", value=f"`{action_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Reason", value=reason[:500] if len(reason) > 500 else reason, inline=False)

        await self._send_log(embed)

    async def log_appeal_reviewed(
        self,
        appeal_id: int,
        user_id: int,
        action_type: str,
        decision: str,
        reviewed_by: discord.User,
    ) -> None:
        """
        Log when an appeal is approved or denied.

        Args:
            appeal_id: The appeal ID
            user_id: The user who submitted the appeal
            action_type: Type of action that was appealed
            decision: 'approved' or 'denied'
            reviewed_by: The moderator who reviewed
        """
        now = datetime.now(NY_TZ)
        time_str = now.strftime("%I:%M %p EST")

        if decision == "approved":
            title = "✅ Appeal Approved"
            color = COLOR_SUCCESS
        else:
            title = "❌ Appeal Denied"
            color = COLOR_ERROR

        embed = discord.Embed(
            title=title,
            color=color,
        )

        embed.set_thumbnail(url=reviewed_by.display_avatar.url)

        embed.add_field(name="Appeal ID", value=f"`#{appeal_id}`", inline=True)
        embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
        embed.add_field(name="Action Type", value=f"`{action_type}`", inline=True)
        embed.add_field(name="Decision", value=f"`{decision.upper()}`", inline=True)
        embed.add_field(name="Reviewed By", value=f"{reviewed_by.mention}", inline=True)
        embed.add_field(name="Time", value=f"`{time_str}`", inline=True)

        await self._send_log(embed)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["InteractionLogger"]
