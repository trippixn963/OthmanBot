"""
OthmanBot - Ban Notifier Service
================================

Main service for sending DM notifications about debate bans.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.utils.discord_rate_limit import log_http_error
from src.views.appeals import AppealButtonView
from src.services.notifications.embeds import (
    build_ban_embed,
    build_unban_embed,
    build_expiry_embed,
)

if TYPE_CHECKING:
    from src.bot import OthmanBot


class BanNotifier:
    """
    Service for sending DM notifications about debate bans.

    Sends comprehensive embeds with:
    - Action taken (banned/unbanned/expired)
    - Moderator who took the action
    - Scope (all debates or specific thread)
    - Duration and expiry time
    - Reason (if provided)

    All DM attempts are logged via the tree logger.
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
            scope: Human-readable scope (e.g., "all debates")
            duration: Human-readable duration (e.g., "1 Week")
            expires_at: When the ban expires (None for permanent)
            thread_id: The specific thread ID if not global
            reason: Optional reason for the ban
            past_ban_count: Number of previous bans

        Returns:
            True if DM was sent successfully, False otherwise
        """
        logger.info("Attempting Ban Notification DM", [
            ("User", f"{user.name} ({user.display_name})"),
            ("ID", str(user.id)),
            ("Banned By", f"{banned_by.name} ({banned_by.display_name})"),
            ("ID", str(banned_by.id)),
            ("Scope", scope),
            ("Duration", duration),
            ("Thread ID", str(thread_id) if thread_id else "Global"),
            ("Reason", reason[:50] if reason else "None"),
        ])

        try:
            embed = build_ban_embed(
                user=user,
                banned_by=banned_by,
                scope=scope,
                duration=duration,
                expires_at=expires_at,
                thread_id=thread_id,
                reason=reason,
                past_ban_count=past_ban_count
            )

            # Create appeal button view
            appeal_view = AppealButtonView(
                action_type="disallow",
                action_id=user.id,
                user_id=user.id,
            )

            await user.send(embed=embed, view=appeal_view)

            logger.success("Ban Notification DM Sent Successfully", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Scope", scope),
                ("Duration", duration),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Ban Notification DM Failed - DMs Disabled", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Scope", scope),
                ("Duration", duration),
            ])
            return False

        except discord.HTTPException as e:
            log_http_error(e, "Ban Notification DM", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Scope", scope),
            ])
            return False

        except Exception as e:
            logger.error("Ban Notification DM Failed - Unexpected Error", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])
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
            ("User", f"{user.name} ({user.display_name})"),
            ("ID", str(user.id)),
            ("Unbanned By", f"{unbanned_by.name} ({unbanned_by.display_name})"),
            ("ID", str(unbanned_by.id)),
            ("Scope", scope),
            ("Thread ID", str(thread_id) if thread_id else "Global"),
        ])

        try:
            embed = build_unban_embed(
                unbanned_by=unbanned_by,
                scope=scope,
                thread_id=thread_id,
                reason=reason
            )

            await user.send(embed=embed)

            logger.success("Unban Notification DM Sent Successfully", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Scope", scope),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Unban Notification DM Failed - DMs Disabled", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Scope", scope),
            ])
            return False

        except discord.HTTPException as e:
            log_http_error(e, "Unban Notification DM", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Scope", scope),
            ])
            return False

        except Exception as e:
            logger.error("Unban Notification DM Failed - Unexpected Error", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])
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
            ("ID", str(user_id)),
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
                    ("ID", str(user_id)),
                ])
                return False

            embed = await build_expiry_embed(
                bot=self.bot,
                scope=scope,
                thread_id=thread_id,
                reason=reason,
                banned_by_id=banned_by_id,
                created_at=created_at,
            )

            await user.send(embed=embed)

            logger.success("Ban Expiry Notification DM Sent Successfully", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Scope", scope),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Ban Expiry Notification DM Failed - DMs Disabled", [
                ("ID", str(user_id)),
                ("Scope", scope),
            ])
            return False

        except discord.HTTPException as e:
            log_http_error(e, "Ban Expiry Notification DM", [
                ("ID", str(user_id)),
                ("Scope", scope),
            ])
            return False

        except Exception as e:
            logger.error("Ban Expiry Notification DM Failed - Unexpected Error", [
                ("ID", str(user_id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])
            return False


__all__ = ["BanNotifier"]
