"""
OthmanBot - Case Log Service
======================================

Service for logging ban/unban actions to forum threads in the mods server.

Features:
- Unique case ID and thread per user
- Thread title format: [XXXX] | Username
- Ban/unban events logged to same thread
- Auto-unbans (expired bans) logged
- Ban count tracked in embed titles

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import CASE_LOG_FORUM_ID, EmbedColors
from src.services.case_log_modules.embed_builder import CaseEmbedBuilder
from src.services.case_log_modules.thread_manager import CaseThreadManager

# Auto-archive after 7 days of inactivity
ARCHIVE_DURATION = discord.utils.MISSING

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Case Log Service
# =============================================================================

class CaseLogService:
    """
    Service for logging moderation actions to forum threads.

    Each user gets a unique case thread where all ban/unban events are logged.
    Thread persists across all moderation actions for that user.
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the case log service.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot
        self.thread_manager = CaseThreadManager(bot)

    @property
    def db(self):
        """Get database from debates_service."""
        return self.bot.debates_service.db if self.bot.debates_service else None

    @property
    def enabled(self) -> bool:
        """Check if case logging is enabled."""
        return CASE_LOG_FORUM_ID is not None and self.db is not None

    async def create_rules_thread(self) -> Optional[discord.Thread]:
        """
        Create a pinned rules thread in the case log forum.

        Returns:
            The created thread, or None on failure
        """
        return await self.thread_manager.create_rules_thread()

    async def log_ban(
        self,
        user: discord.Member,
        banned_by: discord.Member,
        scope: str,
        duration: str,
        thread_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> None:
        """
        Log a ban action to the user's case thread.

        Args:
            user: The user being banned
            banned_by: The moderator who issued the ban
            scope: Scope of the ban (e.g., "all debates", "thread 123456")
            duration: Duration display string (e.g., "1 Week", "Permanent")
            thread_id: Optional specific thread ID if banning from one thread
            reason: Optional reason for the ban
        """
        if not self.enabled:
            return

        try:
            # Build scope with clickable thread link if applicable
            display_scope = await self.thread_manager.build_scope_with_link(scope, thread_id)

            case = await self.thread_manager.get_or_create_case(
                user, banned_by, display_scope, duration, thread_id, reason
            )

            # If case was just created, ban embed was already included in thread creation
            if case.get('just_created'):
                logger.tree("Case Log: New Case Created With Ban", [
                    ("User", f"{user.display_name} ({user.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Thread ID", str(case['thread_id'])),
                    ("Banned By", f"{banned_by.display_name}"),
                    ("Scope", scope),
                    ("Duration", duration),
                    ("Ban #", "1"),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="📋")

                # If no reason provided, ping moderator in the thread
                if not reason:
                    case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
                    if case_thread:
                        await case_thread.send(
                            f"{banned_by.mention} Please provide a reason for this ban."
                        )
                return

            # Existing case - increment ban count and send ban embed
            ban_count = self.db.increment_ban_count(user.id)

            case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
            if case_thread:
                embed = CaseEmbedBuilder.build_ban_embed(
                    user, banned_by, display_scope, duration, thread_id, reason, ban_count
                )
                await case_thread.send(embed=embed)

                # If no reason provided, ping moderator
                if not reason:
                    await case_thread.send(
                        f"{banned_by.mention} Please provide a reason for this disallow."
                    )

                # REPEAT OFFENDER ESCALATION: 3+ disallows and not already permanent
                is_permanent = duration.lower() in ("permanent", "perm", "forever", "indefinite")
                if ban_count >= 3 and not is_permanent:
                    escalation_embed = CaseEmbedBuilder.build_repeat_offender_embed(user, ban_count)
                    await case_thread.send(embed=escalation_embed)

                    logger.info("Case Log: Repeat Offender Alert Sent", [
                        ("User", f"{user.display_name} ({user.id})"),
                        ("Disallow Count", str(ban_count)),
                    ])

                logger.tree("Case Log: Ban Logged", [
                    ("User", f"{user.display_name} ({user.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Banned By", f"{banned_by.display_name}"),
                    ("Scope", scope),
                    ("Duration", duration),
                    ("Ban #", str(ban_count)),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="🚫")

        except Exception as e:
            logger.error("Case Log: Failed To Log Ban", [
                ("User ID", str(user.id)),
                ("Error", str(e)),
            ])

    async def log_unban(
        self,
        user_id: int,
        unbanned_by: discord.Member,
        scope: str,
        display_name: str,
        reason: Optional[str] = None,
        thread_id: Optional[int] = None
    ) -> None:
        """
        Log an unban action to the user's case thread.

        Args:
            user_id: The user being unbanned
            unbanned_by: The moderator who issued the unban
            scope: Scope of the unban (e.g., "all debates", "thread 123456")
            display_name: Display name of the user
            reason: Optional reason for the unban
            thread_id: Optional specific thread ID if unbanning from one thread
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                # No case exists, nothing to log
                return

            # Update last unban timestamp
            self.db.update_last_unban(user_id)

            # Build scope with clickable thread link if applicable
            display_scope = await self.thread_manager.build_scope_with_link(scope, thread_id)

            # Try to get user avatar
            user_avatar_url = None
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    user_avatar_url = user.display_avatar.url
            except Exception:
                pass  # User may have left, avatar not available

            case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
            if case_thread:
                embed = CaseEmbedBuilder.build_unban_embed(
                    unbanned_by, display_scope, reason, user_avatar_url
                )
                await case_thread.send(embed=embed)

                # If no reason provided, ping moderator
                if not reason:
                    await case_thread.send(
                        f"{unbanned_by.mention} Please provide a reason for this unban."
                    )

                logger.tree("Case Log: Unban Logged", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Unbanned By", f"{unbanned_by.display_name}"),
                    ("Scope", scope),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="✅")

        except Exception as e:
            logger.error("Case Log: Failed To Log Unban", [
                ("User ID", str(user_id)),
                ("Error", str(e)),
            ])

    async def log_ban_expired(
        self,
        user_id: int,
        scope: str,
        display_name: str,
        thread_id: Optional[int] = None
    ) -> None:
        """
        Log an auto-unban (expired) to the user's case thread.

        Args:
            user_id: The user whose ban expired
            scope: Scope of the expired ban
            display_name: Display name of the user
            thread_id: Optional specific thread ID if ban was for one thread
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                # No case exists, nothing to log
                return

            # Update last unban timestamp
            self.db.update_last_unban(user_id)

            # Build scope with clickable thread link if applicable
            display_scope = await self.thread_manager.build_scope_with_link(scope, thread_id)

            # Try to get user avatar
            user_avatar_url = None
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    user_avatar_url = user.display_avatar.url
            except Exception:
                pass  # User may have left, avatar not available

            case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
            if case_thread:
                embed = CaseEmbedBuilder.build_expired_embed(display_scope, user_avatar_url)
                await case_thread.send(embed=embed)

                logger.tree("Case Log: Ban Expiry Logged", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Scope", scope),
                ], emoji="⏰")

        except Exception as e:
            logger.error("Case Log: Failed To Log Ban Expiry", [
                ("User ID", str(user_id)),
                ("Error", str(e)),
            ])

    async def log_member_left(
        self,
        user_id: int,
        user_name: str,
        user_avatar_url: Optional[str] = None
    ) -> None:
        """
        Log when a user with a case thread leaves the server.

        Args:
            user_id: The user's ID
            user_name: The user's display name
            user_avatar_url: The user's avatar URL
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return  # No case thread for this user

            case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
            if case_thread:
                embed = CaseEmbedBuilder.build_member_left_embed(
                    user_name, user_id, user_avatar_url
                )
                await case_thread.send(embed=embed)

                logger.info("Case Log: User Left Server Logged", [
                    ("User", f"{user_name} ({user_id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                ])

        except Exception as e:
            logger.warning("Case Log: Failed To Log Member Left", [
                ("User ID", str(user_id)),
                ("Error", str(e)),
            ])

    async def log_member_rejoined(
        self,
        member: discord.Member
    ) -> None:
        """
        Log when a user with a case thread rejoins the server.

        If the user is still disallowed, ping the moderator who disallowed them
        to alert them that the user tried to rejoin thinking it would remove their restriction.

        Args:
            member: The member who rejoined
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(member.id)
            if not case:
                return  # No case thread for this user

            case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
            if case_thread:
                # Check if user is still disallowed
                active_restrictions = self.db.get_user_bans(member.id)
                is_still_disallowed = len(active_restrictions) > 0

                # Get the moderator(s) who disallowed them
                disallowed_by_ids = set()
                restriction_scopes = []
                for restriction in active_restrictions:
                    if restriction.get('banned_by'):
                        disallowed_by_ids.add(restriction['banned_by'])
                    if restriction.get('thread_id'):
                        restriction_scopes.append(f"Thread `{restriction['thread_id']}`")
                    else:
                        restriction_scopes.append("All Debates")

                disallow_count = case.get('ban_count', 0)

                embed = CaseEmbedBuilder.build_member_rejoined_embed(
                    member, is_still_disallowed, disallow_count, restriction_scopes
                )
                await case_thread.send(embed=embed)

                # If still disallowed, ping the moderator(s) who disallowed them
                if is_still_disallowed and disallowed_by_ids:
                    mod_pings = " ".join(f"<@{mod_id}>" for mod_id in disallowed_by_ids)
                    await case_thread.send(
                        f"{mod_pings} This user you disallowed has rejoined the server. "
                        f"Their restriction is still active - they may have thought leaving would remove it."
                    )

                logger.info("Case Log: User Rejoined Server Logged", [
                    ("User", f"{member.display_name} ({member.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Previous Disallows", str(disallow_count)),
                    ("Still Disallowed", "Yes" if is_still_disallowed else "No"),
                    ("Mods Pinged", str(len(disallowed_by_ids)) if is_still_disallowed else "0"),
                ])

        except Exception as e:
            logger.warning("Case Log: Failed To Log Member Rejoined", [
                ("User ID", str(member.id)),
                ("Error", str(e)),
            ])

    async def log_debate_closed(
        self,
        thread: discord.Thread,
        closed_by: discord.Member,
        owner: Optional[discord.Member],
        original_name: str,
        reason: str
    ) -> None:
        """
        Log a debate closure to the owner's case thread.

        Creates a case if the owner doesn't have one yet, since closing
        a debate reflects on the owner's moderation history.

        Args:
            thread: The debate thread being closed
            closed_by: The moderator who closed the debate
            owner: The owner of the debate (creator)
            original_name: Original thread name before [CLOSED] prefix
            reason: Reason for closing the debate
        """
        if not self.enabled or not owner:
            return

        try:
            case = self.db.get_case_log(owner.id)

            # If no case exists, create one with this close action
            if not case:
                case_id = self.db.get_next_case_id()
                case_thread = await self.thread_manager.create_debate_close_case_thread(
                    owner, case_id, closed_by, thread, original_name, reason
                )

                if case_thread:
                    self.db.create_case_log(owner.id, case_id, case_thread.id)
                    logger.tree("Case Log: New Case Created With Debate Close", [
                        ("User", f"{owner.display_name} ({owner.id})"),
                        ("Case ID", f"{case_id:04d}"),
                        ("Thread ID", str(case_thread.id)),
                        ("Closed By", f"{closed_by.display_name}"),
                        ("Debate", original_name[:30]),
                        ("Reason", reason[:50] if len(reason) > 50 else reason),
                    ], emoji="🔒")
                return

            # Existing case - send close embed to their case thread
            case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
            if case_thread:
                embed = CaseEmbedBuilder.build_debate_close_embed(
                    owner, closed_by, thread, original_name, reason
                )
                await case_thread.send(embed=embed)

                logger.tree("Case Log: Debate Close Logged", [
                    ("User", f"{owner.display_name} ({owner.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Closed By", f"{closed_by.display_name}"),
                    ("Debate", original_name[:30]),
                    ("Reason", reason[:50] if len(reason) > 50 else reason),
                ], emoji="🔒")

        except Exception as e:
            logger.error("Case Log: Failed To Log Debate Close", [
                ("User ID", str(owner.id) if owner else "Unknown"),
                ("Error", str(e)),
            ])

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
        Log a debate reopening to the owner's case thread (if exists).

        Unlike closing, reopening doesn't create a new case - it only
        logs to an existing case thread if one exists.

        Args:
            thread: The debate thread being reopened
            reopened_by: The moderator who reopened the debate
            owner: The owner of the debate (creator)
            original_name: Thread name before reopening (with [CLOSED])
            new_name: Thread name after reopening
            reason: Reason for reopening the debate
        """
        if not self.enabled or not owner:
            return

        try:
            case = self.db.get_case_log(owner.id)
            if not case:
                # No case exists, nothing to log
                return

            case_thread = await self.thread_manager.get_case_thread(case['thread_id'])
            if case_thread:
                embed = CaseEmbedBuilder.build_debate_reopen_embed(
                    owner, reopened_by, thread, new_name, reason
                )
                await case_thread.send(embed=embed)

                logger.tree("Case Log: Debate Reopen Logged", [
                    ("User", f"{owner.display_name} ({owner.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Reopened By", f"{reopened_by.display_name}"),
                    ("Debate", new_name[:30]),
                    ("Reason", reason[:50] if len(reason) > 50 else reason),
                ], emoji="🔓")

        except Exception as e:
            logger.error("Case Log: Failed To Log Debate Reopen", [
                ("User ID", str(owner.id) if owner else "Unknown"),
                ("Error", str(e)),
            ])

    async def archive_inactive_cases(self, days_inactive: int = 7) -> int:
        """
        Archive case threads that have been inactive for specified days.

        Args:
            days_inactive: Number of days of inactivity before archiving

        Returns:
            Number of threads archived
        """
        return await self.thread_manager.archive_inactive_cases(days_inactive)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseLogService"]
