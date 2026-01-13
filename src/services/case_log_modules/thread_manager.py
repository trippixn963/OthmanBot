"""
OthmanBot - Case Thread Manager
===============================

Manages case log forum threads (create, get, archive).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import CASE_LOG_FORUM_ID, NY_TZ
from src.services.case_log_modules.embed_builder import CaseEmbedBuilder

if TYPE_CHECKING:
    from src.bot import OthmanBot


# Rules thread content
RULES_CONTENT = """
══════════════════════════════════════
             CASE LOG GUIDELINES
══════════════════════════════════════


**What is this forum?**
This forum tracks all moderation actions (bans/unbans) for debate threads. Each user gets a unique case thread where all their moderation history is logged.



══════════════════════════════════════
      BANNABLE OFFENSES (/disallow)
══════════════════════════════════════

Users should be banned from debates for:

**Severe Violations (Permanent Ban)**
• Hate speech, slurs, or discriminatory language
• Doxxing or sharing personal information
• Threats of violence or harassment
• Spam or advertising
• Evading previous bans with alt accounts

**Moderate Violations (1 Week - 1 Month)**
• Repeated personal attacks or insults
• Trolling or derailing debates intentionally
• Posting NSFW or inappropriate content
• Impersonating other users or staff

**Minor Violations (1 Day - 1 Week)**
• Excessive off-topic posting
• Ignoring moderator warnings
• Minor toxicity or hostility
• Repeatedly posting low-effort content



══════════════════════════════════════
         MODERATOR GUIDELINES
══════════════════════════════════════

**Before Banning:**
• Warn the user first when possible (for minor offenses)
• Check if the user has prior cases using `/cases`
• Consider the context and severity of the violation
• Document the reason clearly

**When Using /disallow:**
• Always provide a reason (you'll be pinged if you don't)
• Choose appropriate duration based on severity
• For repeat offenders, escalate the duration
• Use "all debates" for severe/repeated violations
• Use specific thread bans for isolated incidents

**Duration Guidelines:**
```
First offense (minor)     →  1 Day
First offense (moderate)  →  1 Week
Repeat offense            →  2 Weeks - 1 Month
Severe/Habitual          →  Permanent
```

**After Banning:**
• Add context in the case thread if needed
• Monitor for ban evasion
• Document any appeals or follow-up

**Unbanning (/allow):**
• Always provide a reason for unbans
• Check the case history before unbanning
• Consider if the user has shown improvement



══════════════════════════════════════
           CASE THREAD USAGE
══════════════════════════════════════

• Use case threads to discuss specific users
• Add notes about warnings given
• Document appeal decisions
• Coordinate with other mods on repeat offenders
• Threads auto-archive after 7 days of inactivity



══════════════════════════════════════
"""


class CaseThreadManager:
    """Manages case log forum threads."""

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the case thread manager.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot
        self._forum: Optional[discord.ForumChannel] = None

    @property
    def db(self):
        """Get database from debates_service."""
        return self.bot.debates_service.db if self.bot.debates_service else None

    async def get_forum(self) -> Optional[discord.ForumChannel]:
        """Get the case log forum channel."""
        if not CASE_LOG_FORUM_ID:
            return None

        if self._forum is None:
            try:
                channel = self.bot.get_channel(CASE_LOG_FORUM_ID)
                if channel is None:
                    channel = await self.bot.fetch_channel(CASE_LOG_FORUM_ID)
                if isinstance(channel, discord.ForumChannel):
                    self._forum = channel
            except Exception as e:
                logger.warning("Failed To Get Case Log Forum", [
                    ("Forum ID", str(CASE_LOG_FORUM_ID)),
                    ("Error", str(e)),
                ])
                return None

        return self._forum

    async def get_case_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """
        Get a case thread by ID.

        Args:
            thread_id: The thread ID

        Returns:
            The thread, or None if not found
        """
        try:
            thread = self.bot.get_channel(thread_id)
            if thread is None:
                thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                return thread
        except discord.NotFound:
            logger.warning("Case Thread Not Found", [
                ("Thread ID", str(thread_id)),
            ])
        except Exception as e:
            logger.warning("Failed To Get Case Thread", [
                ("Thread ID", str(thread_id)),
                ("Error", str(e)),
            ])
        return None

    async def create_rules_thread(self) -> Optional[discord.Thread]:
        """
        Create a pinned rules thread in the case log forum.

        Returns:
            The created thread, or None on failure
        """
        forum = await self.get_forum()
        if not forum:
            return None

        try:
            thread_with_msg = await forum.create_thread(
                name="📋 Case Log Rules & Guidelines",
                content=RULES_CONTENT
            )

            # Pin the thread
            await thread_with_msg.thread.edit(pinned=True)

            logger.tree("Case Log Rules Thread Created", [
                ("Thread ID", str(thread_with_msg.thread.id)),
                ("Pinned", "Yes"),
            ], emoji="📋")

            return thread_with_msg.thread

        except Exception as e:
            logger.error("Failed To Create Rules Thread", [
                ("Error", str(e)),
            ])
            return None

    async def create_case_thread(
        self,
        user: discord.Member,
        case_id: int,
        banned_by: discord.Member,
        scope: str,
        duration: str,
        target_thread_id: Optional[int],
        reason: Optional[str] = None
    ) -> Optional[discord.Thread]:
        """
        Create a new forum thread for this case with detailed user info.

        Args:
            user: The user being banned
            case_id: The case number
            banned_by: The moderator issuing the ban
            scope: Scope of the ban
            duration: Duration display string
            target_thread_id: Optional specific debate thread ID
            reason: Optional reason for the ban

        Returns:
            The created thread, or None on failure
        """
        forum = await self.get_forum()
        if not forum:
            return None

        # Build user profile embed
        user_embed = CaseEmbedBuilder.build_user_profile_embed(user)

        # Build initial ban action embed (ban #1 for new case)
        ban_embed = CaseEmbedBuilder.build_ban_embed(
            user, banned_by, scope, duration, target_thread_id, reason, ban_count=1
        )

        # Create thread with both embeds
        thread_name = f"[{case_id:04d}] | {user.display_name}"

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],  # Discord limit
                embeds=[user_embed, ban_embed]
            )

            # Pin the first message (user profile) for easy reference
            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
                    logger.info("Pinned User Profile In Case Thread", [
                        ("Case ID", str(case_id)),
                        ("User", f"{user.display_name} ({user.id})"),
                    ])
            except Exception as pin_error:
                logger.warning("Failed To Pin User Profile", [
                    ("Case ID", str(case_id)),
                    ("Error", str(pin_error)),
                ])

            return thread_with_msg.thread
        except Exception as e:
            logger.error("Failed To Create Case Thread", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", str(case_id)),
                ("Error", str(e)),
            ])
            return None

    async def create_debate_close_case_thread(
        self,
        owner: discord.Member,
        case_id: int,
        closed_by: discord.Member,
        thread: discord.Thread,
        original_name: str,
        reason: str
    ) -> Optional[discord.Thread]:
        """
        Create a new case thread starting with a debate close action.

        Args:
            owner: The debate owner
            case_id: The case number
            closed_by: The moderator who closed the debate
            thread: The debate thread
            original_name: Original thread name
            reason: Reason for closing

        Returns:
            The created thread, or None on failure
        """
        forum = await self.get_forum()
        if not forum:
            return None

        # Build user info embed
        user_embed = CaseEmbedBuilder.build_user_profile_embed(owner)

        # Build debate close embed
        close_embed = CaseEmbedBuilder.build_debate_close_embed(
            owner, closed_by, thread, original_name, reason
        )

        # Create thread with both embeds
        thread_name = f"[{case_id:04d}] | {owner.display_name}"

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],
                embeds=[user_embed, close_embed]
            )
            return thread_with_msg.thread
        except Exception as e:
            logger.error("Failed To Create Case Thread For Debate Close", [
                ("User", f"{owner.display_name} ({owner.id})"),
                ("Case ID", str(case_id)),
                ("Error", str(e)),
            ])
            return None

    async def get_or_create_case(
        self,
        user: discord.Member,
        banned_by: discord.Member,
        scope: str,
        duration: str,
        target_thread_id: Optional[int],
        reason: Optional[str] = None
    ) -> dict:
        """
        Get existing case or create new one with forum thread.

        Args:
            user: The user being banned
            banned_by: The moderator issuing the ban
            scope: Scope of the ban
            duration: Duration display string
            target_thread_id: Optional specific debate thread ID
            reason: Optional reason for the ban

        Returns:
            Dict with case info, includes 'just_created' flag if new
        """
        if not self.db:
            raise RuntimeError("Database not available")

        case = self.db.get_case_log(user.id)
        if case:
            return case  # Existing case, ban embed will be sent separately

        # Create new case with both user info and initial ban embed
        case_id = self.db.get_next_case_id()
        thread = await self.create_case_thread(
            user, case_id, banned_by, scope, duration, target_thread_id, reason
        )

        if thread:
            self.db.create_case_log(user.id, case_id, thread.id)
            return {
                'user_id': user.id,
                'case_id': case_id,
                'thread_id': thread.id,
                'just_created': True
            }

        # Failed to create thread
        raise RuntimeError("Failed to create case thread")

    async def build_scope_with_link(
        self,
        scope: str,
        thread_id: Optional[int]
    ) -> str:
        """
        Build scope string with clickable thread link if applicable.

        Args:
            scope: Original scope string
            thread_id: Optional thread ID to create link for

        Returns:
            Scope string, possibly with clickable link
        """
        if not thread_id:
            return scope

        # Try to get thread name for better link text
        try:
            thread = self.bot.get_channel(thread_id)
            if thread is None:
                thread = await self.bot.fetch_channel(thread_id)

            if isinstance(thread, discord.Thread):
                # Use thread name (truncated if too long)
                thread_name = thread.name[:30] + "..." if len(thread.name) > 30 else thread.name
                # Create clickable link using Discord channel mention format
                link = f"[{thread_name}](https://discord.com/channels/{thread.guild.id}/{thread_id})"
                logger.info("Case Log: Built Scope Link", [
                    ("Thread ID", str(thread_id)),
                    ("Thread Name", thread_name),
                ])
                return link
        except Exception as e:
            logger.warning("Case Log: Failed To Build Scope Link", [
                ("Thread ID", str(thread_id)),
                ("Error", str(e)),
            ])

        # Fallback: just show thread ID with link
        return f"[Thread {thread_id}](https://discord.com/channels/@me/{thread_id})"

    async def archive_inactive_cases(self, days_inactive: int = 7) -> int:
        """
        Archive case threads that have been inactive for specified days.

        Args:
            days_inactive: Number of days of inactivity before archiving

        Returns:
            Number of threads archived
        """
        if not self.db:
            return 0

        archived_count = 0
        cutoff_time = datetime.now(NY_TZ) - timedelta(days=days_inactive)

        try:
            forum = await self.get_forum()
            if not forum:
                return 0

            # Get all case logs
            all_cases = self.db.get_all_case_logs()

            for case in all_cases:
                try:
                    thread = await self.get_case_thread(case['thread_id'])
                    if not thread or thread.archived:
                        continue

                    # Check last message time
                    if thread.last_message_id:
                        try:
                            last_msg = await thread.fetch_message(thread.last_message_id)
                            if last_msg.created_at.replace(tzinfo=NY_TZ) > cutoff_time:
                                continue  # Thread is still active
                        except Exception:
                            pass  # Couldn't fetch message, check archive time instead

                    # Archive the thread
                    await thread.edit(archived=True)
                    archived_count += 1

                    logger.info("Case Thread Archived", [
                        ("Case ID", f"{case['case_id']:04d}"),
                        ("Thread ID", str(case['thread_id'])),
                    ])

                except Exception as e:
                    logger.warning("Failed To Archive Case Thread", [
                        ("Case ID", str(case['case_id'])),
                        ("Error", str(e)),
                    ])

        except Exception as e:
            logger.error("Error In Archive Inactive Cases", [
                ("Error", str(e)),
            ])

        if archived_count > 0:
            logger.tree("Case Thread Archiving Complete", [
                ("Threads Archived", str(archived_count)),
                ("Inactivity Threshold", f"{days_inactive} days"),
            ], emoji="📦")

        return archived_count


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseThreadManager"]
