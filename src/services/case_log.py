"""
Othman Discord Bot - Case Log Service
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

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Union

import discord

from src.core.logger import logger
from src.core.config import CASE_LOG_FORUM_ID, NY_TZ, EmbedColors

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
        self._forum: Optional[discord.ForumChannel] = None

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
        forum = await self._get_forum()
        if not forum:
            return None

        rules_content = """
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

        try:
            thread_with_msg = await forum.create_thread(
                name="📋 Case Log Rules & Guidelines",
                content=rules_content
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

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
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
            display_scope = await self._build_scope_with_link(scope, thread_id)

            case = await self._get_or_create_case(user, banned_by, display_scope, duration, thread_id, reason)

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
                    case_thread = await self._get_case_thread(case['thread_id'])
                    if case_thread:
                        await case_thread.send(
                            f"{banned_by.mention} Please provide a reason for this ban."
                        )
                return

            # Existing case - increment ban count and send ban embed
            ban_count = self.db.increment_ban_count(user.id)

            case_thread = await self._get_case_thread(case['thread_id'])
            if case_thread:
                embed = self._build_ban_embed(user, banned_by, display_scope, duration, thread_id, reason, ban_count)
                await case_thread.send(embed=embed)

                # If no reason provided, ping moderator
                if not reason:
                    await case_thread.send(
                        f"{banned_by.mention} Please provide a reason for this disallow."
                    )

                # REPEAT OFFENDER ESCALATION: 3+ disallows and not already permanent
                is_permanent = duration.lower() in ("permanent", "perm", "forever", "indefinite")
                if ban_count >= 3 and not is_permanent:
                    escalation_embed = discord.Embed(
                        title="⚠️ Repeat Offender Alert",
                        color=EmbedColors.CLOSE,
                        description=f"**{user.display_name}** has been disallowed **{ban_count} times**."
                    )
                    escalation_embed.add_field(
                        name="Recommendation",
                        value="Consider a **permanent disallow** for this user.\n"
                              f"Use: `/disallow user:{user.id} duration:permanent`",
                        inline=False
                    )
                    escalation_embed.set_footer(text="This alert triggers at 3+ disallows when not permanent")
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
            display_scope = await self._build_scope_with_link(scope, thread_id)

            # Try to get user avatar
            user_avatar_url = None
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    user_avatar_url = user.display_avatar.url
            except Exception:
                pass  # User may have left, avatar not available

            case_thread = await self._get_case_thread(case['thread_id'])
            if case_thread:
                embed = self._build_unban_embed(unbanned_by, display_scope, reason, user_avatar_url)
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
            display_scope = await self._build_scope_with_link(scope, thread_id)

            # Try to get user avatar
            user_avatar_url = None
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    user_avatar_url = user.display_avatar.url
            except Exception:
                pass  # User may have left, avatar not available

            case_thread = await self._get_case_thread(case['thread_id'])
            if case_thread:
                embed = self._build_expired_embed(display_scope, user_avatar_url)
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

    async def _get_or_create_case(
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
        case = self.db.get_case_log(user.id)
        if case:
            return case  # Existing case, ban embed will be sent separately

        # Create new case with both user info and initial ban embed
        case_id = self.db.get_next_case_id()
        thread = await self._create_case_thread(
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

    async def _create_case_thread(
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
        forum = await self._get_forum()
        if not forum:
            return None

        # Build detailed user info embed
        user_embed = discord.Embed(
            title="📋 User Profile",
            color=EmbedColors.INFO
        )
        user_embed.set_thumbnail(url=user.display_avatar.url)
        user_embed.add_field(name="Username", value=f"{user.name}", inline=True)
        user_embed.add_field(name="Display Name", value=f"{user.display_name}", inline=True)
        user_embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)

        # Discord account creation date
        user_embed.add_field(
            name="Discord Joined",
            value=f"<t:{int(user.created_at.timestamp())}:F>",
            inline=True
        )

        # Server join date (if available)
        if hasattr(user, 'joined_at') and user.joined_at:
            user_embed.add_field(
                name="Server Joined",
                value=f"<t:{int(user.joined_at.timestamp())}:F>",
                inline=True
            )

        # Account age (formatted as years, months, days)
        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        account_age = self._format_age(created_at, now)
        user_embed.add_field(name="Account Age", value=account_age, inline=True)

        # Build initial ban action embed (ban #1 for new case)
        ban_embed = self._build_ban_embed(user, banned_by, scope, duration, target_thread_id, reason, ban_count=1)

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

    async def _get_case_thread(self, thread_id: int) -> Optional[discord.Thread]:
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

    def _build_ban_embed(
        self,
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

    def _build_unban_embed(
        self,
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

    def _build_expired_embed(
        self,
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

    async def _build_scope_with_link(
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

    def _format_age(self, start: datetime, end: datetime) -> str:
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

            case_thread = await self._get_case_thread(case['thread_id'])
            if case_thread:
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

            case_thread = await self._get_case_thread(case['thread_id'])
            if case_thread:
                # Check if user is still disallowed
                active_restrictions = self.db.get_user_bans(member.id)
                is_still_disallowed = len(active_restrictions) > 0

                # Get the moderator(s) who disallowed them
                disallowed_by_ids = set()
                for restriction in active_restrictions:
                    if restriction.get('banned_by'):
                        disallowed_by_ids.add(restriction['banned_by'])

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
                disallow_count = case.get('ban_count', 0)
                if disallow_count > 0:
                    embed.add_field(
                        name="⚠️ Warning",
                        value=f"User has **{disallow_count}** previous disallow(s) on record",
                        inline=False
                    )

                # If still disallowed, add prominent warning
                if is_still_disallowed:
                    restriction_scopes = []
                    for restriction in active_restrictions:
                        if restriction.get('thread_id'):
                            restriction_scopes.append(f"Thread `{restriction['thread_id']}`")
                        else:
                            restriction_scopes.append("All Debates")

                    embed.add_field(
                        name="🚫 STILL DISALLOWED",
                        value=f"User rejoined while disallowed from: {', '.join(restriction_scopes)}\n"
                              f"Restriction is **still active** - leaving does not remove it!",
                        inline=False
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
                case_thread = await self._create_debate_close_case_thread(
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
            case_thread = await self._get_case_thread(case['thread_id'])
            if case_thread:
                embed = self._build_debate_close_embed(
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

    async def _create_debate_close_case_thread(
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
        forum = await self._get_forum()
        if not forum:
            return None

        # Build user info embed
        user_embed = discord.Embed(
            title="📋 User Profile",
            color=EmbedColors.INFO
        )
        user_embed.set_thumbnail(url=owner.display_avatar.url)
        user_embed.add_field(name="Username", value=f"{owner.name}", inline=True)
        user_embed.add_field(name="Display Name", value=f"{owner.display_name}", inline=True)
        user_embed.add_field(name="User ID", value=f"`{owner.id}`", inline=True)

        # Discord account creation date
        user_embed.add_field(
            name="Discord Joined",
            value=f"<t:{int(owner.created_at.timestamp())}:F>",
            inline=True
        )

        # Server join date (if available)
        if hasattr(owner, 'joined_at') and owner.joined_at:
            user_embed.add_field(
                name="Server Joined",
                value=f"<t:{int(owner.joined_at.timestamp())}:F>",
                inline=True
            )

        # Account age
        now = datetime.now(NY_TZ)
        created_at = owner.created_at.replace(tzinfo=NY_TZ) if owner.created_at.tzinfo is None else owner.created_at
        account_age = self._format_age(created_at, now)
        user_embed.add_field(name="Account Age", value=account_age, inline=True)

        # Build debate close embed
        close_embed = self._build_debate_close_embed(
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

    def _build_debate_close_embed(
        self,
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

            case_thread = await self._get_case_thread(case['thread_id'])
            if case_thread:
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
        if not self.enabled:
            return 0

        archived_count = 0
        cutoff_time = datetime.now(NY_TZ) - timedelta(days=days_inactive)

        try:
            forum = await self._get_forum()
            if not forum:
                return 0

            # Get all case logs
            all_cases = self.db.get_all_case_logs()

            for case in all_cases:
                try:
                    thread = await self._get_case_thread(case['thread_id'])
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

__all__ = ["CaseLogService"]
