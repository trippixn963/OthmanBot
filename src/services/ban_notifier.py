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
from src.core.config import NY_TZ

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

# Embed colors
COLOR_BAN = discord.Color.red()
COLOR_UNBAN = discord.Color.green()
COLOR_EXPIRED = discord.Color.blue()
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
        reason: Optional[str] = None
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
            embed = discord.Embed(
                title="You Have Been Banned from Debates",
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
            if reason:
                embed.add_field(
                    name="Reason",
                    value=reason[:1024],  # Discord field limit
                    inline=False
                )
            else:
                embed.add_field(
                    name="Reason",
                    value="_No reason provided_",
                    inline=False
                )

            # Footer with server info
            embed.set_footer(
                text="Syria Discord Server | Debates System",
                icon_url=self.bot.user.display_avatar.url if self.bot.user else None
            )

            # Send DM
            await user.send(embed=embed)

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
            embed = discord.Embed(
                title="You Have Been Unbanned from Debates",
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

            # Reason
            if reason:
                embed.add_field(
                    name="Note",
                    value=reason[:1024],
                    inline=False
                )

            # Reminder about rules
            embed.add_field(
                name="Reminder",
                value=(
                    "Please make sure to follow the debate rules to avoid future bans.\n"
                    "React with :white_check_mark: to the rules message to participate."
                ),
                inline=False
            )

            # Footer with server info
            embed.set_footer(
                text="Syria Discord Server | Debates System",
                icon_url=self.bot.user.display_avatar.url if self.bot.user else None
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
        thread_id: Optional[int] = None
    ) -> bool:
        """
        Send a DM notification when a user's ban expires automatically.

        Args:
            user_id: The user ID whose ban expired
            scope: Human-readable scope
            thread_id: The specific thread ID if not global

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

            embed = discord.Embed(
                title="Your Debate Ban Has Expired",
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

            # Reminder about rules
            embed.add_field(
                name="Reminder",
                value=(
                    "Please make sure to follow the debate rules to avoid future bans.\n"
                    "React with :white_check_mark: to the rules message to participate."
                ),
                inline=False
            )

            # Footer with server info
            embed.set_footer(
                text="Syria Discord Server | Debates System",
                icon_url=self.bot.user.display_avatar.url if self.bot.user else None
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
