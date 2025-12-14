"""
Othman Discord Bot - Leaderboard Manager
=========================================

Manages the leaderboard forum post with monthly tracking.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, SECONDS_PER_HOUR, SCHEDULER_ERROR_RETRY
from src.utils import send_message_with_retry, edit_message_with_retry, edit_thread_with_retry
from src.services.debates.database import DebatesDatabase, UserKarma

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Month Names
# =============================================================================

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


# =============================================================================
# Leaderboard Manager Class
# =============================================================================

class LeaderboardManager:
    """Manages the leaderboard forum post."""

    def __init__(self, bot: "OthmanBot", db: DebatesDatabase) -> None:
        """
        Initialize leaderboard manager.

        Args:
            bot: The OthmanBot instance
            db: The debates database
        """
        self.bot = bot
        self.db = db
        self._task: Optional[asyncio.Task] = None
        self._thread: Optional[discord.Thread] = None
        self._refresh_lock = asyncio.Lock()  # Prevent concurrent refreshes

    @property
    def is_running(self) -> bool:
        """Check if the leaderboard manager is running."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Initialize leaderboard post and start hourly updates."""
        await self._ensure_leaderboard_post()
        self._task = asyncio.create_task(self._update_loop())
        logger.success("📊 Leaderboard Manager Started", [
            ("Interval", "hourly"),
        ])

    async def stop(self) -> None:
        """Stop the update loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # -------------------------------------------------------------------------
    # Post Management
    # -------------------------------------------------------------------------

    async def _ensure_thread_healthy(self) -> None:
        """Ensure the leaderboard thread is pinned and not archived."""
        if not self._thread:
            return
        try:
            # Check if thread needs fixing
            needs_edit = False
            if hasattr(self._thread, 'archived') and self._thread.archived:
                needs_edit = True
            if hasattr(self._thread, 'pinned') and not self._thread.pinned:
                needs_edit = True

            if needs_edit:
                await edit_thread_with_retry(self._thread, archived=False, pinned=True)
                logger.info("📊 Fixed Leaderboard Thread State", [
                    ("Action", "Unarchived/Pinned"),
                ])
        except Exception as e:
            logger.warning("📊 Could Not Ensure Thread Health", [
                ("Error", str(e)),
            ])

    async def _ensure_leaderboard_post(self) -> None:
        """Create or find the leaderboard post in debates forum."""
        # Check if we have a saved thread
        saved_thread_id = self.db.get_leaderboard_thread()

        if saved_thread_id:
            # Try to get the existing thread (may be None if archived)
            self._thread = self.bot.get_channel(saved_thread_id)

            # If not in cache, try to fetch it (handles archived threads)
            if not self._thread:
                try:
                    self._thread = await self.bot.fetch_channel(saved_thread_id)
                except discord.NotFound:
                    logger.warning("📊 Saved Leaderboard Thread Not Found - Creating New One", [
                        ("Thread ID", str(saved_thread_id)),
                    ])
                    self.db.clear_leaderboard_thread()
                    self._thread = None
                except Exception as e:
                    logger.error("📊 Error Fetching Leaderboard Thread", [
                        ("Error", str(e)),
                    ])
                    self._thread = None

            if self._thread:
                # Unarchive if needed
                if hasattr(self._thread, 'archived') and self._thread.archived:
                    try:
                        await edit_thread_with_retry(self._thread, archived=False)
                        logger.info("📊 Unarchived Leaderboard Thread", [
                            ("Thread ID", str(saved_thread_id)),
                        ])
                    except Exception as e:
                        logger.error("📊 Failed To Unarchive Leaderboard Thread", [
                            ("Error", str(e)),
                        ])
                        # Clear and recreate
                        self.db.clear_leaderboard_thread()
                        self._thread = None

                if self._thread:
                    logger.info("📊 Found Existing Leaderboard Thread", [
                        ("Thread ID", str(saved_thread_id)),
                    ])
                    await self._update_current_month()
                    return

        # Create new thread in debates forum
        await self._create_leaderboard_thread()

    async def _create_leaderboard_thread(self) -> None:
        """Create a new leaderboard thread in the debates forum."""
        forum = self.bot.get_channel(DEBATES_FORUM_ID)
        if not forum or not isinstance(forum, discord.ForumChannel):
            logger.error("📊 Debates Forum Not Found Or Invalid", [
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])
            return

        # Create initial content for current month
        now = datetime.now()
        content = self._generate_month_content(now.year, now.month)

        try:
            # Create thread with plain text content
            thread, message = await forum.create_thread(
                name="Leaderboard",
                content=content,
            )

            # Lock and pin the thread so it stays at the top and can't be replied to
            await edit_thread_with_retry(thread, locked=True, pinned=True, archived=False)

            # Save thread ID
            self.db.set_leaderboard_thread(thread.id)

            # Save current month embed
            self.db.set_month_embed(now.year, now.month, message.id)

            self._thread = thread
            logger.success("📊 Created New Leaderboard Thread", [
                ("Thread ID", str(thread.id)),
            ])
        except discord.Forbidden:
            logger.error("📊 No Permission to Create Leaderboard Thread", [
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])
        except discord.HTTPException as e:
            logger.error("📊 Failed to Create Leaderboard Thread", [
                ("Forum ID", str(DEBATES_FORUM_ID)),
                ("Error", str(e)),
            ])

    # -------------------------------------------------------------------------
    # Update Loop
    # -------------------------------------------------------------------------

    async def _update_loop(self) -> None:
        """Update leaderboard every hour."""
        while True:
            try:
                # Wait 1 hour
                await asyncio.sleep(SECONDS_PER_HOUR)

                # Ensure thread is healthy (pinned, not archived)
                await self._ensure_thread_healthy()

                # Update current month
                await self._update_current_month()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("📊 Leaderboard Update Error", [
                    ("Error", str(e)),
                ])
                # Wait before retrying
                await asyncio.sleep(SCHEDULER_ERROR_RETRY)

    async def _update_current_month(self) -> None:
        """Update the current month's content (or create new one if month changed)."""
        if not self._thread:
            logger.warning("📊 Leaderboard Thread Not Found - Cannot Update")
            return

        now = datetime.now()
        year, month = now.year, now.month

        # Check if we have a message for this month
        message_id = self.db.get_month_embed(year, month)

        if message_id:
            # Update existing message
            try:
                message = await self._thread.fetch_message(message_id)
                content = self._generate_month_content(year, month)
                # Set embed=None to remove any existing embed
                await edit_message_with_retry(message, content=content, embed=None)
                logger.debug("📊 Updated Leaderboard", [
                    ("Month", MONTH_NAMES[month]),
                    ("Year", str(year)),
                ])
            except discord.NotFound:
                # Message was deleted, create new one
                await self._post_new_month_message(year, month)
            except discord.HTTPException as e:
                if e.code == 50083:  # Thread is archived
                    logger.warning("📊 Leaderboard Thread Is Archived - Attempting To Unarchive")
                    try:
                        await edit_thread_with_retry(self._thread, archived=False)
                        # Retry after unarchiving
                        message = await self._thread.fetch_message(message_id)
                        content = self._generate_month_content(year, month)
                        await edit_message_with_retry(message, content=content, embed=None)
                        logger.info("📊 Successfully Unarchived And Updated Leaderboard")
                    except Exception as unarchive_error:
                        logger.error("📊 Failed To Recover Archived Thread", [
                            ("Error", str(unarchive_error)),
                        ])
                        # Clear and let it recreate on next cycle
                        self.db.clear_leaderboard_thread()
                        self._thread = None
                else:
                    raise
        else:
            # New month, post new message
            await self._post_new_month_message(year, month)

    async def _post_new_month_message(self, year: int, month: int) -> None:
        """Post a new message for a month."""
        if not self._thread:
            return

        content = self._generate_month_content(year, month)
        message = await send_message_with_retry(self._thread, content=content)
        if not message:
            logger.warning("📊 Failed to post new month leaderboard", [
                ("Month", MONTH_NAMES[month]),
                ("Year", str(year)),
            ])
            return
        self.db.set_month_embed(year, month, message.id)
        logger.info("📊 Posted New Leaderboard", [
            ("Month", MONTH_NAMES[month]),
            ("Year", str(year)),
        ])

    # -------------------------------------------------------------------------
    # Content Generation
    # -------------------------------------------------------------------------

    def _generate_month_content(self, year: int, month: int) -> str:
        """
        Generate the leaderboard content for a specific month.

        Args:
            year: Year
            month: Month (1-12)

        Returns:
            Plain text content with leaderboard data
        """
        # Get monthly leaderboard (top 10)
        monthly = self.db.get_monthly_leaderboard(year, month, limit=10)

        # Get all-time leaderboard (top 10)
        all_time = self.db.get_leaderboard(limit=10)

        # Get most active debates (top 3)
        active_debates = self.db.get_most_active_debates(limit=3)

        # Get most active participants (top 3)
        active_participants = self.db.get_most_active_participants(limit=3)

        # Get debate starters (top 3)
        debate_starters = self.db.get_top_debate_starters(limit=3)

        # Get monthly stats
        monthly_stats = self.db.get_monthly_stats(year, month)

        # Build content
        lines = []
        separator = "══════════════════════"

        # Current Month section
        month_name = MONTH_NAMES[month]
        lines.append(f"### 📅 {month_name} {year}")
        lines.append(self._format_top_users(monthly))
        lines.append("")
        lines.append(separator)
        lines.append("")

        # All-Time section
        lines.append("### 🏆 All-Time Champions")
        lines.append(self._format_top_users(all_time))
        lines.append("")
        lines.append(separator)
        lines.append("")

        # Most Active Debates section
        lines.append("### 🔥 Most Active Debates")
        lines.append(self._format_active_debates(active_debates))
        lines.append("")
        lines.append(separator)
        lines.append("")

        # Most Active Participants section
        lines.append("### 💬 Most Active Participants")
        lines.append(self._format_active_participants(active_participants))
        lines.append("")
        lines.append(separator)
        lines.append("")

        # Debate Starters section
        lines.append("### 🎯 Debate Starters")
        lines.append(self._format_debate_starters(debate_starters))
        lines.append("")
        lines.append(separator)
        lines.append("")

        # Community Stats section
        lines.append("### 📊 Community Stats")
        lines.append(self._format_community_stats(monthly_stats, month_name))
        lines.append("")

        # Footer with timestamp
        now = datetime.now()
        lines.append(f"-# 🔄 Updates hourly • Last: {now.strftime('%I:%M %p')}")

        return "\n".join(lines)

    def _format_top_users(self, users: list[UserKarma]) -> str:
        """
        Format top users with medals/numbers, mentions, and vote breakdown.

        Args:
            users: List of UserKarma (up to 10)

        Returns:
            Formatted string with medal emojis for top 3, numbers for 4-10
        """
        if not users:
            return "*No data yet*"

        medals = ["🥇", "🥈", "🥉"]
        lines = []

        for i, user in enumerate(users[:10]):
            karma_sign = "+" if user.total_karma >= 0 else ""
            # Use medals for top 3, numbers for 4-10
            if i < 3:
                prefix = medals[i]
            else:
                prefix = f"`{i + 1}.`"
            # Use Discord mention format <@user_id> with vote breakdown
            lines.append(
                f"{prefix} <@{user.user_id}> — **{karma_sign}{user.total_karma}** "
                f"(↑{user.upvotes_received} ↓{user.downvotes_received})"
            )

        return "\n".join(lines)

    def _format_active_debates(self, debates: list[dict]) -> str:
        """
        Format top active debates with thread links.

        Args:
            debates: List of dicts with thread_id, message_count

        Returns:
            Formatted string with numbered debate links
        """
        if not debates:
            return "*No active debates*"

        fire_medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, debate in enumerate(debates[:3]):
            thread_id = debate["thread_id"]
            msg_count = debate["message_count"]
            # Use Discord thread link format with fire medals
            lines.append(f"{fire_medals[i]} <#{thread_id}> — 💬 {msg_count}")

        return "\n".join(lines)

    def _format_active_participants(self, participants: list[dict]) -> str:
        """
        Format top active participants with message counts.

        Args:
            participants: List of dicts with user_id, message_count

        Returns:
            Formatted string with medal emojis
        """
        if not participants:
            return "*No data yet*"

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, p in enumerate(participants[:3]):
            user_id = p["user_id"]
            msg_count = p["message_count"]
            lines.append(f"{medals[i]} <@{user_id}> — **{msg_count}** messages")

        return "\n".join(lines)

    def _format_debate_starters(self, starters: list[dict]) -> str:
        """
        Format top debate starters.

        Args:
            starters: List of dicts with user_id, debate_count

        Returns:
            Formatted string with medal emojis
        """
        if not starters:
            return "*No data yet*"

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, s in enumerate(starters[:3]):
            user_id = s["user_id"]
            debate_count = s["debate_count"]
            lines.append(f"{medals[i]} <@{user_id}> — **{debate_count}** debates started")

        return "\n".join(lines)

    def _format_community_stats(self, stats: dict, month_name: str) -> str:
        """
        Format community stats for the month.

        Args:
            stats: Dict with total_debates, total_votes, most_active_day
            month_name: Name of the month

        Returns:
            Formatted string with stats
        """
        lines = []
        lines.append(f"📝 **{stats['total_debates']}** debates this month")
        lines.append(f"🗳️ **{stats['total_votes']}** votes cast")
        if stats['most_active_day']:
            lines.append(f"📈 Most active: **{month_name} {stats['most_active_day']}**")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Member Events
    # -------------------------------------------------------------------------

    async def on_member_leave(self, user_id: int) -> None:
        """
        Handle member leaving - mark as left and update embeds.

        Args:
            user_id: Discord user ID
        """
        # Mark user as left in cache
        self.db.mark_user_left(user_id)

        # Update all messages
        await self._refresh_all_messages()

    async def on_member_join(self, user_id: int, username: str, display_name: str) -> None:
        """
        Handle member rejoining - update cache and embeds.

        Args:
            user_id: Discord user ID
            username: Discord username
            display_name: Display name
        """
        # Check if user was previously cached
        cached = self.db.get_cached_user(user_id)
        if cached:
            # Mark as rejoined
            self.db.mark_user_rejoined(user_id)
            # Update their name
            self.db.cache_user(user_id, username, display_name)
            # Update all messages
            await self._refresh_all_messages()

    async def _refresh_all_messages(self) -> None:
        """Refresh all month messages to update user names."""
        if not self._thread:
            return

        # Prevent concurrent refreshes from multiple member events
        async with self._refresh_lock:
            embeds = self.db.get_all_month_embeds()
            for embed_data in embeds:
                try:
                    message = await self._thread.fetch_message(embed_data["message_id"])
                    content = self._generate_month_content(embed_data["year"], embed_data["month"])
                    await edit_message_with_retry(message, content=content, embed=None)
                    await asyncio.sleep(0.5)  # Rate limit delay between edits
                except discord.NotFound:
                    # Message deleted, remove from db
                    self.db.delete_month_embed(embed_data["year"], embed_data["month"])
                except discord.HTTPException as e:
                    if e.code == 50083:  # Thread is archived
                        try:
                            await edit_thread_with_retry(self._thread, archived=False)
                            message = await self._thread.fetch_message(embed_data["message_id"])
                            content = self._generate_month_content(embed_data["year"], embed_data["month"])
                            await edit_message_with_retry(message, content=content, embed=None)
                        except Exception:
                            logger.error("📊 Failed To Refresh Message (Archived Thread)", [
                                ("Data", str(embed_data)),
                            ])
                    else:
                        logger.error("📊 Failed To Refresh Message", [
                            ("Data", str(embed_data)),
                            ("Error", str(e)),
                        ])
                except Exception as e:
                    logger.error("📊 Failed To Refresh Message", [
                        ("Data", str(embed_data)),
                        ("Error", str(e)),
                    ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["LeaderboardManager"]
