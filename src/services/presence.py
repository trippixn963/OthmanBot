"""
OthmanBot - Presence Handler
============================

Wrapper around unified presence system with OthmanBot-specific stats.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import Optional, List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import PRESENCE_UPDATE_INTERVAL, NY_TZ

# Import from shared unified presence system
from shared.services.presence import BasePresenceHandler

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Configuration
# =============================================================================

PROMO_DURATION_MINUTES = 10
"""Duration of promo presence at the top of each hour."""

PROMO_TEXT = "🌐 trippixn.com/othman"
"""Promotional text shown during promo hour."""


# =============================================================================
# OthmanBot Presence Handler
# =============================================================================

class PresenceHandler(BasePresenceHandler):
    """Presence handler configured for OthmanBot with debate stats."""

    def __init__(self, bot: "OthmanBot") -> None:
        super().__init__(
            bot,
            update_interval=PRESENCE_UPDATE_INTERVAL,
            promo_duration_minutes=PROMO_DURATION_MINUTES,
        )

    # -------------------------------------------------------------------------
    # Required Implementations
    # -------------------------------------------------------------------------

    def get_status_messages(self) -> List[str]:
        """Get debate-related stats for presence rotation."""
        messages = []

        try:
            # Get all-time stats from database (sync call wrapped)
            if self.bot.debates_service and self.bot.debates_service.db:
                stats = self.bot.debates_service.db.get_all_time_stats()

                total_debates = stats.get("total_debates", 0)
                total_votes = stats.get("total_votes", 0)
                total_karma = stats.get("total_karma", 0)
                total_participants = stats.get("total_participants", 0)
                total_messages = stats.get("total_messages", 0)

                if total_debates > 0:
                    messages.append(f"⚔️ {self._format_number(total_debates)} debates created")

                if total_participants > 0:
                    messages.append(f"🏆 {self._format_number(total_participants)} debaters ranked")

                if total_votes > 0:
                    messages.append(f"⬆️ {self._format_number(total_votes)} votes cast")

                if total_karma > 0:
                    messages.append(f"⭐ {self._format_number(total_karma)} karma earned")

                if total_messages > 0:
                    messages.append(f"💬 {self._format_number(total_messages)} messages sent")

        except Exception as e:
            logger.warning("Presence Stats Error", [
                ("Error", str(e)[:50]),
            ])

        # Fallback if no stats available
        if not messages:
            messages = ["🇸🇾 discord.gg/syria"]

        return messages

    def get_promo_text(self) -> str:
        """Return OthmanBot promo text."""
        return PROMO_TEXT

    def get_timezone(self):
        """Return NY timezone for promo scheduling."""
        return NY_TZ

    # -------------------------------------------------------------------------
    # Logging Hooks
    # -------------------------------------------------------------------------

    def on_rotation_start(self) -> None:
        logger.info("🔄 Presence Rotation Started", [
            ("Interval", f"{self.update_interval}s"),
        ])

    def on_promo_start(self) -> None:
        logger.info("📢 Promo Loop Started", [
            ("Duration", f"{self.promo_duration_minutes} min/hour"),
            ("Text", PROMO_TEXT),
        ])

    def on_promo_activated(self) -> None:
        logger.info("📢 Promo Active", [
            ("Text", PROMO_TEXT),
            ("Duration", f"{self.promo_duration_minutes} min"),
        ])

    def on_promo_ended(self) -> None:
        logger.info("📢 Promo Ended", [
            ("Action", "Resuming normal rotation"),
        ])

    def on_handler_ready(self) -> None:
        logger.success("✅ Presence Handler Ready", [
            ("Rotation", f"Every {self.update_interval}s"),
            ("Promo", f"{self.promo_duration_minutes} min/hour"),
        ])

    def on_handler_stopped(self) -> None:
        logger.info("🛑 Presence Handler Stopped", [
            ("Status", "Tasks cancelled"),
        ])

    def on_error(self, context: str, error: Exception) -> None:
        error_msg = str(error).lower()
        if "transport" in error_msg or "not connected" in error_msg or "closed" in error_msg:
            logger.debug(f"{context} Skipped (Connection Issue)", [
                ("Error", str(error)[:50]),
            ])
        else:
            logger.warning(f"{context} Error", [
                ("Error", str(error)[:50]),
            ])

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _format_number(n: int) -> str:
        """Format a number with K/M abbreviations."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    # -------------------------------------------------------------------------
    # Setup Alias (for compatibility)
    # -------------------------------------------------------------------------

    async def setup(self) -> None:
        """Alias for start() for backwards compatibility."""
        await self.start()


# =============================================================================
# Module-level instance (for backwards compatibility)
# =============================================================================

_presence_handler: Optional[PresenceHandler] = None


async def setup_presence(bot: "OthmanBot") -> PresenceHandler:
    """
    Setup and return the presence handler.

    Args:
        bot: The OthmanBot instance

    Returns:
        The PresenceHandler instance
    """
    global _presence_handler
    _presence_handler = PresenceHandler(bot)
    await _presence_handler.setup()
    return _presence_handler


async def stop_presence() -> None:
    """Stop the presence handler."""
    global _presence_handler
    if _presence_handler:
        await _presence_handler.stop()
        _presence_handler = None


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "PresenceHandler",
    "setup_presence",
    "stop_presence",
    "PROMO_TEXT",
    "PROMO_DURATION_MINUTES",
]
