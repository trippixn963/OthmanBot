"""
OthmanBot - Ban Notification Service
=====================================

Sends DM notifications to users when they are banned, unbanned,
or when their ban expires from debate threads.

Includes comprehensive logging to console and Discord webhook.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.core.config import NY_TZ, EmbedColors, EmbedIcons, EMBED_FOOTER_TEXT, EMBED_NO_VALUE
from src.views.appeals import AppealButtonView
from src.utils import get_ordinal, get_developer_avatar

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

# Embed colors - using centralized config
COLOR_BAN = EmbedColors.BAN
COLOR_UNBAN = EmbedColors.UNBAN
COLOR_EXPIRED = EmbedColors.EXPIRED
COLOR_DM_SUCCESS = discord.Color.teal()
COLOR_DM_FAILED = discord.Color.orange()


# =============================================================================
# Ban Notification Service
# =============================================================================

class BanNotifier:
    """
    Service for sending DM notifications about debate bans.

    Sends comprehensive embeds with:
    - Action taken (banned/unbanned/expired)
    - Moderator who took the action
    - Scope (all debates or specific thread)
    - Duration and expiry time
    - Reason (if provided)

    All DM attempts are logged to:
    - Console (via logger)
    - Discord webhook (via interaction_logger)
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the ban notifier.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot

    async def notify_ban(
        self,
        user: Union[discord.User, discord.Member],
        banned_by: Union[discord.User, discord.Member],
        scope: str,
        duration: str,
        expires_at: Optional[datetime] = None,
        thread_id: Optional[int] = None,
        reason: Optional[str] = None,
        past_ban_count: int = 0
    ) -> bool:
        """
        Send a DM notification when a user is banned.

        Args:
            user: The user being banned
            banned_by: The moderator who issued the ban
            scope: Human-readable scope (e.g., "all debates" or "thread `123456`")
            duration: Human-readable duration (e.g., "1 Week", "Permanent")
            expires_at: When the ban expires (None for permanent)
            thread_id: The specific thread ID if not global
            reason: Optional reason for the ban
            past_ban_count: Number of previous bans this user has had

        Returns:
            True if DM was sent successfully, False otherwise
        """
        logger.info("Attempting Ban Notification DM", [
            ("User", f"{user.name} ({user.id})"),
            ("Banned By", f"{banned_by.name} ({banned_by.id})"),
            ("Scope", scope),
            ("Duration", duration),
            ("Thread ID", str(thread_id) if thread_id else "Global"),
            ("Reason", reason[:50] if reason else "None"),
        ])

        try:
            # Get developer avatar for footer
            developer_avatar_url = await get_developer_avatar(self.bot)

            embed = discord.Embed(
                title=f"{EmbedIcons.BAN} You Have Been Banned from Debates",
                description=(
                    "You have been banned from participating in debate threads.\n"
                    "Please review the details below."
                ),
                color=COLOR_BAN,
                timestamp=datetime.now(NY_TZ)
            )

            # Set moderator's avatar as thumbnail
            embed.set_thumbnail(url=banned_by.display_avatar.url)

            # Core fields
            embed.add_field(
                name="Banned By",
                value=f"{banned_by.display_name}",
                inline=True
            )
            embed.add_field(
                name="Scope",
                value=self._format_scope(scope, thread_id),
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

            # Past ban history (only show if this isn't their first ban)
            if past_ban_count > 0:
                # This is a repeat offender
                ordinal = get_ordinal(past_ban_count + 1)
                embed.add_field(
                    name=f"{EmbedIcons.WARNING} Ban History",
                    value=f"This is your **{ordinal}** ban from debates.",
                    inline=True
                )

                # Add consequence warning for repeat offenders
                if past_ban_count == 1:
                    # 2nd ban
                    consequence_warning = (
                        "This is your second ban. Further violations may result in "
                        "longer ban durations or permanent removal from debates."
                    )
                elif past_ban_count == 2:
                    # 3rd ban
                    consequence_warning = (
                        "This is your third ban. Continued violations will likely "
                        "result in permanent removal from debates."
                    )
                else:
                    # 4th+ ban
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

            # Footer with developer info
            embed.set_footer(
                text=EMBED_FOOTER_TEXT,
                icon_url=developer_avatar_url
            )

            # Create appeal button view
            # Use user_id as action_id - when appeal is approved, all bans for this user are removed
            appeal_view = AppealButtonView(
                action_type="disallow",
                action_id=user.id,
                user_id=user.id,
            )

            # Send DM with appeal button
            await user.send(embed=embed, view=appeal_view)

            logger.success("Ban Notification DM Sent Successfully", [
                ("User", f"{user.name} ({user.id})"),
                ("Scope", scope),
                ("Duration", duration),
            ])

            # Log to webhook
            await self._log_dm_to_webhook(
                action="ban",
                user=user,
                moderator=banned_by,
                scope=scope,
                duration=duration,
                thread_id=thread_id,
                reason=reason,
                success=True
            )

            return True

        except discord.Forbidden:
            logger.warning("Ban Notification DM Failed - DMs Disabled", [
                ("User", f"{user.name} ({user.id})"),
                ("Scope", scope),
                ("Duration", duration),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="ban",
                user=user,
                moderator=banned_by,
                scope=scope,
                duration=duration,
                thread_id=thread_id,
                reason=reason,
                success=False,
                error="DMs Disabled"
            )

            return False

        except discord.HTTPException as e:
            logger.error("Ban Notification DM Failed - HTTP Error", [
                ("User", f"{user.name} ({user.id})"),
                ("Scope", scope),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="ban",
                user=user,
                moderator=banned_by,
                scope=scope,
                duration=duration,
                thread_id=thread_id,
                reason=reason,
                success=False,
                error=str(e)
            )

            return False

        except Exception as e:
            logger.error("Ban Notification DM Failed - Unexpected Error", [
                ("User", f"{user.name} ({user.id})"),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="ban",
                user=user,
                moderator=banned_by,
                scope=scope,
                duration=duration,
                thread_id=thread_id,
                reason=reason,
                success=False,
                error=str(e)
            )

            return False

    async def notify_unban(
        self,
        user: Union[discord.User, discord.Member],
        unbanned_by: Union[discord.User, discord.Member],
        scope: str,
        thread_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> bool:
        """
        Send a DM notification when a user is unbanned.

        Args:
            user: The user being unbanned
            unbanned_by: The moderator who lifted the ban
            scope: Human-readable scope
            thread_id: The specific thread ID if not global
            reason: Optional reason for the unban

        Returns:
            True if DM was sent successfully, False otherwise
        """
        logger.info("Attempting Unban Notification DM", [
            ("User", f"{user.name} ({user.id})"),
            ("Unbanned By", f"{unbanned_by.name} ({unbanned_by.id})"),
            ("Scope", scope),
            ("Thread ID", str(thread_id) if thread_id else "Global"),
        ])

        try:
            # Get developer avatar for footer
            developer_avatar_url = await get_developer_avatar(self.bot)

            embed = discord.Embed(
                title=f"{EmbedIcons.UNBAN} You Have Been Unbanned from Debates",
                description=(
                    "Your debate ban has been lifted!\n"
                    "You can now participate in debate threads again."
                ),
                color=COLOR_UNBAN,
                timestamp=datetime.now(NY_TZ)
            )

            # Set moderator's avatar as thumbnail
            embed.set_thumbnail(url=unbanned_by.display_avatar.url)

            # Core fields
            embed.add_field(
                name="Unbanned By",
                value=f"{unbanned_by.display_name}",
                inline=True
            )
            embed.add_field(
                name="Scope",
                value=self._format_scope(scope, thread_id),
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

            # Footer with developer info
            embed.set_footer(
                text=EMBED_FOOTER_TEXT,
                icon_url=developer_avatar_url
            )

            # Send DM
            await user.send(embed=embed)

            logger.success("Unban Notification DM Sent Successfully", [
                ("User", f"{user.name} ({user.id})"),
                ("Scope", scope),
            ])

            # Log to webhook
            await self._log_dm_to_webhook(
                action="unban",
                user=user,
                moderator=unbanned_by,
                scope=scope,
                thread_id=thread_id,
                reason=reason,
                success=True
            )

            return True

        except discord.Forbidden:
            logger.warning("Unban Notification DM Failed - DMs Disabled", [
                ("User", f"{user.name} ({user.id})"),
                ("Scope", scope),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="unban",
                user=user,
                moderator=unbanned_by,
                scope=scope,
                thread_id=thread_id,
                reason=reason,
                success=False,
                error="DMs Disabled"
            )

            return False

        except discord.HTTPException as e:
            logger.error("Unban Notification DM Failed - HTTP Error", [
                ("User", f"{user.name} ({user.id})"),
                ("Scope", scope),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="unban",
                user=user,
                moderator=unbanned_by,
                scope=scope,
                thread_id=thread_id,
                reason=reason,
                success=False,
                error=str(e)
            )

            return False

        except Exception as e:
            logger.error("Unban Notification DM Failed - Unexpected Error", [
                ("User", f"{user.name} ({user.id})"),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="unban",
                user=user,
                moderator=unbanned_by,
                scope=scope,
                thread_id=thread_id,
                reason=reason,
                success=False,
                error=str(e)
            )

            return False

    async def notify_ban_expired(
        self,
        user_id: int,
        scope: str,
        thread_id: Optional[int] = None,
        reason: Optional[str] = None,
        banned_by_id: Optional[int] = None,
        created_at: Optional[str] = None,
    ) -> bool:
        """
        Send a DM notification when a user's ban expires automatically.

        Args:
            user_id: The user ID whose ban expired
            scope: Human-readable scope
            thread_id: The specific thread ID if not global
            reason: Original ban reason
            banned_by_id: ID of moderator who issued the ban
            created_at: When the ban was created

        Returns:
            True if DM was sent successfully, False otherwise
        """
        logger.info("Attempting Ban Expiry Notification DM", [
            ("User ID", str(user_id)),
            ("Scope", scope),
            ("Thread ID", str(thread_id) if thread_id else "Global"),
        ])

        user: Optional[discord.User] = None

        try:
            # Fetch the user
            try:
                user = await self.bot.fetch_user(user_id)
            except discord.NotFound:
                logger.warning("Ban Expiry Notification Failed - User Not Found", [
                    ("User ID", str(user_id)),
                ])

                # Log failure to webhook
                await self._log_dm_to_webhook(
                    action="expired",
                    user_id=user_id,
                    scope=scope,
                    thread_id=thread_id,
                    success=False,
                    error="User Not Found"
                )

                return False

            # Get developer avatar for footer
            developer_avatar_url = await get_developer_avatar(self.bot)

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
            if self.bot.user:
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            # Core fields
            embed.add_field(
                name="Action",
                value="`Automatic Unban`",
                inline=True
            )
            embed.add_field(
                name="Scope",
                value=self._format_scope(scope, thread_id),
                inline=True
            )

            # Thread link if specific thread
            if thread_id:
                embed.add_field(
                    name="Thread ID",
                    value=f"`{thread_id}`",
                    inline=True
                )

            # Original ban details section
            # Add banned by (fetch moderator name if possible)
            if banned_by_id:
                try:
                    banned_by_user = await self.bot.fetch_user(banned_by_id)
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
                    # Parse the timestamp string from SQLite
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

            # Footer with developer info
            embed.set_footer(
                text=EMBED_FOOTER_TEXT,
                icon_url=developer_avatar_url
            )

            # Send DM
            await user.send(embed=embed)

            logger.success("Ban Expiry Notification DM Sent Successfully", [
                ("User", f"{user.name} ({user.id})"),
                ("Scope", scope),
            ])

            # Log to webhook
            await self._log_dm_to_webhook(
                action="expired",
                user=user,
                scope=scope,
                thread_id=thread_id,
                success=True
            )

            return True

        except discord.Forbidden:
            logger.warning("Ban Expiry Notification DM Failed - DMs Disabled", [
                ("User ID", str(user_id)),
                ("Scope", scope),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="expired",
                user=user,
                user_id=user_id,
                scope=scope,
                thread_id=thread_id,
                success=False,
                error="DMs Disabled"
            )

            return False

        except discord.HTTPException as e:
            logger.error("Ban Expiry Notification DM Failed - HTTP Error", [
                ("User ID", str(user_id)),
                ("Scope", scope),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="expired",
                user=user,
                user_id=user_id,
                scope=scope,
                thread_id=thread_id,
                success=False,
                error=str(e)
            )

            return False

        except Exception as e:
            logger.error("Ban Expiry Notification DM Failed - Unexpected Error", [
                ("User ID", str(user_id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

            # Log failure to webhook
            await self._log_dm_to_webhook(
                action="expired",
                user=user,
                user_id=user_id,
                scope=scope,
                thread_id=thread_id,
                success=False,
                error=str(e)
            )

            return False

    async def _log_dm_to_webhook(
        self,
        action: str,
        scope: str,
        success: bool,
        user: Optional[Union[discord.User, discord.Member]] = None,
        user_id: Optional[int] = None,
        moderator: Optional[Union[discord.User, discord.Member]] = None,
        duration: Optional[str] = None,
        thread_id: Optional[int] = None,
        reason: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Log DM notification attempt to webhook.

        Args:
            action: Type of notification ("ban", "unban", "expired")
            scope: Ban scope
            success: Whether DM was sent successfully
            user: The user object (if available)
            user_id: The user ID (fallback if user object not available)
            moderator: The moderator who took the action (for ban/unban)
            duration: Ban duration (for ban)
            thread_id: Specific thread ID if applicable
            reason: Reason for the action
            error: Error message if failed
        """
        try:
            if not hasattr(self.bot, 'interaction_logger') or not self.bot.interaction_logger:
                return

            await self.bot.interaction_logger.log_ban_notification_dm(
                action=action,
                scope=scope,
                success=success,
                user=user,
                user_id=user_id,
                moderator=moderator,
                duration=duration,
                thread_id=thread_id,
                reason=reason,
                error=error
            )

        except Exception as e:
            logger.debug("Failed to log DM notification to webhook", [
                ("Error", str(e)),
            ])

    def _format_scope(self, scope: str, thread_id: Optional[int] = None) -> str:
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


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["BanNotifier"]
