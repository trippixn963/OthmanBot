"""
OthmanBot - Ban Expiry Scheduler
==========================================

Background task that checks for and removes expired debate bans.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from discord.ext import tasks

from src.core.logger import logger
from src.core.config import SYRIA_GUILD_ID

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Ban Expiry Scheduler
# =============================================================================

class BanExpiryScheduler:
    """
    Scheduler that periodically checks for and removes expired debate bans.

    DESIGN:
    - Runs every 1 minute to check for expired bans
    - Automatically removes bans that have passed their expires_at timestamp
    - Logs all automatic unbans for audit trail
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the ban expiry scheduler.

        Args:
            bot: The OthmanBot instance
        """
        self.bot = bot

    async def start(self) -> None:
        """Start the scheduler."""
        if not self._check_expired_bans.is_running():
            self._check_expired_bans.start()
            logger.info("Ban Expiry Scheduler Started", [
                ("Interval", "1 minute"),
            ])

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self._check_expired_bans.is_running():
            self._check_expired_bans.cancel()
            logger.info("Ban Expiry Scheduler Stopped", [
                ("Status", "Task cancelled"),
            ])

    @tasks.loop(minutes=1)
    async def _check_expired_bans(self) -> None:
        """Check for and remove expired bans."""
        try:
            if not hasattr(self.bot, 'debates_service') or not self.bot.debates_service:
                logger.debug("Ban Expiry Check Skipped", [
                    ("Reason", "Debates service not ready"),
                ])
                return

            db = self.bot.debates_service.db

            # Get expired bans before removing them (for logging)
            try:
                expired_bans = db.get_expired_bans()
            except Exception as e:
                logger.error("Failed to Query Expired Bans", [
                    ("Error", str(e)),
                ])
                return

            if not expired_bans:
                return

            # IMPORTANT: Remove bans from database FIRST before sending notifications
            # This ensures users only receive "unbanned" notifications after the ban
            # is actually removed from the database
            try:
                removed_count = db.remove_expired_bans()

                if removed_count > 0:
                    logger.tree("Auto-Unban Complete", [
                        ("Bans Removed", str(removed_count)),
                    ], emoji="✅")
            except Exception as e:
                logger.error("Failed to Remove Expired Bans from Database", [
                    ("Expired Bans Count", str(len(expired_bans))),
                    ("Error", str(e)),
                ])
                # Don't send notifications if database removal failed
                return

            # Now send notifications for each expired ban (after successful DB removal)
            for ban in expired_bans:
                try:
                    user_id = ban['user_id']
                    thread_id = ban['thread_id']
                    scope = f"thread {thread_id}" if thread_id else "all debates"

                    # Fetch user once and cache for this loop iteration
                    user = None
                    try:
                        user = await self.bot.fetch_user(user_id)
                    except Exception:
                        pass

                    logger.success("⏰ Auto-Unban: Ban Expired", [
                        ("User", f"{user.name} ({user.display_name})" if user else f"User {user_id}"),
                        ("ID", str(user_id)),
                        ("Scope", scope),
                        ("Expired At", ban['expires_at']),
                    ])

                    # Log to case system (for mods server forum)
                    try:
                        if hasattr(self.bot, 'case_log_service') and self.bot.case_log_service:
                            await self.bot.case_log_service.log_ban_expired(
                                user_id=user_id,
                                scope=scope,
                                display_name=user.display_name if user else f"User {user_id}"
                            )
                    except Exception as e:
                        logger.warning("Failed to log auto-unban to case system", [
                            ("User", f"{user.name} ({user.display_name})" if user else f"User {user_id}"),
                            ("ID", str(user_id)),
                            ("Error", str(e)),
                        ])

                    # Send DM notification to the user whose ban expired
                    try:
                        if hasattr(self.bot, 'ban_notifier') and self.bot.ban_notifier:
                            await self.bot.ban_notifier.notify_ban_expired(
                                user_id=user_id,
                                scope=scope,
                                thread_id=thread_id,
                                reason=ban.get('reason'),
                                banned_by_id=ban.get('banned_by'),
                                created_at=ban.get('created_at'),
                            )
                    except Exception as e:
                        logger.warning("Failed to send ban expiry notification DM", [
                            ("User", f"{user.name} ({user.display_name})" if user else f"User {user_id}"),
                            ("ID", str(user_id)),
                            ("Error", str(e)),
                        ])

                except Exception as e:
                    # Log error but continue processing other bans
                    logger.error("Failed to process expired ban notification", [
                        ("Ban", str(ban)),
                        ("Error", str(e)),
                    ])

        except Exception as e:
            logger.error("Error In Ban Expiry Check", [
                ("Error", str(e)),
            ])
            # Send to webhook for critical scheduler errors
            try:
                if hasattr(self.bot, 'webhook_alerts') and self.bot.webhook_alerts:
                    await self.bot.webhook_alerts.send_error_alert(
                        "Ban Expiry Scheduler Error",
                        str(e)
                    )
            except Exception:
                pass  # Don't fail on webhook error

    @_check_expired_bans.before_loop
    async def _before_check(self) -> None:
        """Wait until the bot is ready before starting."""
        await self.bot.wait_until_ready()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["BanExpiryScheduler"]
