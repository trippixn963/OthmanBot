"""
Othman Discord Bot - Case Log Service
======================================

Service for logging ban/unban actions to forum threads in the mods server.
Each user gets a unique case ID and thread that persists across all their moderation actions.

DESIGN:
- Thread title format: [XXXX] | Discord Username
- First message: User profile info + initial ban embed
- All subsequent ban/unban events logged to the same thread
- Auto-unbans (expired bans) also logged
- Ban count tracked and displayed in embed titles
- Clickable thread links in scope field
- User roles displayed in profile embed

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Union

import discord

from src.core.logger import logger
from src.core.config import CASE_LOG_FORUM_ID, NY_TZ

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
                        f"{banned_by.mention} Please provide a reason for this ban."
                    )

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
            color=discord.Color.blue()
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

        # User roles (excluding @everyone)
        roles = self._format_user_roles(user)
        if roles:
            user_embed.add_field(name="Roles", value=roles, inline=False)

        # Build initial ban action embed (ban #1 for new case)
        ban_embed = self._build_ban_embed(user, banned_by, scope, duration, target_thread_id, reason, ban_count=1)

        # Create thread with both embeds
        thread_name = f"[{case_id:04d}] | {user.display_name}"

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],  # Discord limit
                embeds=[user_embed, ban_embed]
            )
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
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Banned By", value=f"{banned_by.mention}", inline=True)
        embed.add_field(name="Scope", value=scope, inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:t> EST",
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
            color=discord.Color.green()
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)
        embed.add_field(name="Unbanned By", value=f"{unbanned_by.mention}", inline=True)
        embed.add_field(name="Scope", value=scope, inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:t> EST",
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
            color=discord.Color.blue()
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)
        embed.add_field(name="Scope", value=scope, inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:t> EST",
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

    def _format_user_roles(self, user: discord.Member) -> str:
        """
        Format user roles for display in embed.

        Args:
            user: The member to get roles from

        Returns:
            Formatted string of role mentions, or empty string if no roles
        """
        # Get roles excluding @everyone, sorted by position (highest first)
        roles = [role for role in user.roles if role.name != "@everyone"]
        roles.sort(key=lambda r: r.position, reverse=True)

        if not roles:
            return ""

        # Limit to top 10 roles to avoid embed field limits
        if len(roles) > 10:
            role_mentions = [role.mention for role in roles[:10]]
            role_mentions.append(f"+{len(roles) - 10} more")
            return " ".join(role_mentions)

        return " ".join(role.mention for role in roles)

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
                    color=discord.Color.orange(),
                    description=f"**{user_name}** has left the server"
                )
                if user_avatar_url:
                    embed.set_thumbnail(url=user_avatar_url)

                embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)

                now = datetime.now(NY_TZ)
                embed.add_field(
                    name="Time",
                    value=f"<t:{int(now.timestamp())}:t> EST",
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

        If the user is still banned (disallowed), ping the moderator who banned them
        to alert them that the user tried to rejoin thinking it would remove their ban.

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
                # Check if user is still banned
                active_bans = self.db.get_user_bans(member.id)
                is_still_banned = len(active_bans) > 0

                # Get the moderator(s) who banned them
                banned_by_ids = set()
                for ban in active_bans:
                    if ban.get('banned_by'):
                        banned_by_ids.add(ban['banned_by'])

                # Choose embed color based on ban status
                if is_still_banned:
                    embed_color = discord.Color.red()  # Red - still banned
                    title = "🚨 Banned User Rejoined Server"
                else:
                    embed_color = discord.Color.gold()  # Gold - normal rejoin
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
                    value=f"<t:{int(now.timestamp())}:t> EST",
                    inline=True
                )

                # Add warning about previous moderation history
                ban_count = case.get('ban_count', 0)
                if ban_count > 0:
                    embed.add_field(
                        name="⚠️ Warning",
                        value=f"User has **{ban_count}** previous ban(s) on record",
                        inline=False
                    )

                # If still banned, add prominent warning
                if is_still_banned:
                    ban_scopes = []
                    for ban in active_bans:
                        if ban.get('thread_id'):
                            ban_scopes.append(f"Thread `{ban['thread_id']}`")
                        else:
                            ban_scopes.append("All Debates")

                    embed.add_field(
                        name="🚫 STILL BANNED",
                        value=f"User rejoined while banned from: {', '.join(ban_scopes)}\n"
                              f"Ban is **still active** - leaving does not remove bans!",
                        inline=False
                    )

                await case_thread.send(embed=embed)

                # If still banned, ping the moderator(s) who banned them
                if is_still_banned and banned_by_ids:
                    mod_pings = " ".join(f"<@{mod_id}>" for mod_id in banned_by_ids)
                    await case_thread.send(
                        f"{mod_pings} This user you banned has rejoined the server. "
                        f"Their ban is still active - they may have thought leaving would remove it."
                    )

                logger.info("Case Log: User Rejoined Server Logged", [
                    ("User", f"{member.display_name} ({member.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Previous Bans", str(ban_count)),
                    ("Still Banned", "Yes" if is_still_banned else "No"),
                    ("Mods Pinged", str(len(banned_by_ids)) if is_still_banned else "0"),
                ])

        except Exception as e:
            logger.warning("Case Log: Failed To Log Member Rejoined", [
                ("User ID", str(member.id)),
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
