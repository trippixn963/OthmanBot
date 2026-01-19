"""
OthmanBot - Presence Handler
===========================

Manages rotating Discord presence with all-time stats and hourly promo.
Modeled after SyriaBot's presence system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import PRESENCE_UPDATE_INTERVAL, NY_TZ

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
# Presence Handler Class
# =============================================================================

class PresenceHandler:
    """Handles rotating presence and hourly promo messages."""

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the presence handler.

        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
        self._rotation_task: Optional[asyncio.Task] = None
        self._promo_task: Optional[asyncio.Task] = None
        self._current_index = 0
        self._is_promo_active = False
        self._running = False

    # -------------------------------------------------------------------------
    # Number Formatting
    # -------------------------------------------------------------------------

    @staticmethod
    def _format_number(n: int) -> str:
        """
        Format a number with K/M abbreviations.

        Args:
            n: The number to format

        Returns:
            Formatted string (e.g., "1.5M", "12.3K", "500")
        """
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    # -------------------------------------------------------------------------
    # Status Messages
    # -------------------------------------------------------------------------

    async def _get_status_messages(self) -> List[str]:
        """
        Get list of status messages with all-time stats.

        Returns:
            List of formatted status messages.
        """
        messages = []

        try:
            # Get all-time stats from database
            if self.bot.debates_service and self.bot.debates_service.db:
                stats = await asyncio.to_thread(self.bot.debates_service.db.get_all_time_stats)

                total_debates = stats.get("total_debates", 0)
                total_votes = stats.get("total_votes", 0)
                total_karma = stats.get("total_karma", 0)
                total_participants = stats.get("total_participants", 0)
                total_messages = stats.get("total_messages", 0)

                # Build status messages with all-time stats only
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

    # -------------------------------------------------------------------------
    # Rotation Loop
    # -------------------------------------------------------------------------

    async def _rotation_loop(self) -> None:
        """Background task that rotates presence every interval."""
        await self.bot.wait_until_ready()

        logger.info("🔄 Presence Rotation Started", [
            ("Interval", f"{PRESENCE_UPDATE_INTERVAL}s"),
        ])

        while self._running:
            try:
                # Wait first, then check promo status
                await asyncio.sleep(PRESENCE_UPDATE_INTERVAL)

                # Skip if promo is active
                if self._is_promo_active:
                    continue

                # Get status messages and rotate
                messages = await self._get_status_messages()
                if messages:
                    self._current_index = self._current_index % len(messages)
                    status_text = messages[self._current_index]

                    # Double-check promo isn't active right before changing
                    if self._is_promo_active:
                        continue

                    await self.bot.change_presence(
                        activity=discord.Activity(
                            type=discord.ActivityType.watching,
                            name=status_text,
                        )
                    )

                    self._current_index += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Ignore connection errors during shutdown/reconnection
                error_msg = str(e).lower()
                if "transport" in error_msg or "not connected" in error_msg or "closed" in error_msg:
                    logger.debug("Presence Update Skipped (Connection Issue)", [
                        ("Error", str(e)[:50]),
                    ])
                else:
                    logger.warning("Presence Rotation Error", [
                        ("Error", str(e)[:50]),
                    ])
                await asyncio.sleep(PRESENCE_UPDATE_INTERVAL)

    # -------------------------------------------------------------------------
    # Promo Loop
    # -------------------------------------------------------------------------

    async def _promo_loop(self) -> None:
        """Background task that shows promo at the top of each hour."""
        await self.bot.wait_until_ready()

        logger.info("📢 Promo Loop Started", [
            ("Duration", f"{PROMO_DURATION_MINUTES} min/hour"),
            ("Text", PROMO_TEXT),
        ])

        while self._running:
            try:
                # Calculate time until next hour
                now = datetime.now(NY_TZ)
                minutes_until_hour = 60 - now.minute
                seconds_until_hour = (minutes_until_hour * 60) - now.second

                if seconds_until_hour > 0:
                    logger.debug("Promo Waiting", [
                        ("Next Promo", f"{minutes_until_hour} min"),
                    ])
                    await asyncio.sleep(seconds_until_hour)

                # Show promo
                self._is_promo_active = True

                await self.bot.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,
                        name=PROMO_TEXT,
                    )
                )

                logger.info("📢 Promo Active", [
                    ("Text", PROMO_TEXT),
                    ("Duration", f"{PROMO_DURATION_MINUTES} min"),
                ])

                # Wait for promo duration
                await asyncio.sleep(PROMO_DURATION_MINUTES * 60)

                # End promo
                self._is_promo_active = False

                logger.info("📢 Promo Ended", [
                    ("Action", "Resuming normal rotation"),
                ])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._is_promo_active = False
                # Ignore connection errors during shutdown/reconnection
                error_msg = str(e).lower()
                if "transport" in error_msg or "not connected" in error_msg or "closed" in error_msg:
                    logger.debug("Promo Update Skipped (Connection Issue)", [
                        ("Error", str(e)[:50]),
                    ])
                else:
                    logger.warning("Promo Loop Error", [
                        ("Error", str(e)[:50]),
                    ])
                await asyncio.sleep(60)

    # -------------------------------------------------------------------------
    # Task Exception Handler
    # -------------------------------------------------------------------------

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle exceptions from presence tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.tree("Presence Task Exception", [
                ("Task", task.get_name()),
                ("Error Type", type(exc).__name__),
                ("Error", str(exc)[:100]),
            ], emoji="❌")

    # -------------------------------------------------------------------------
    # Setup / Stop
    # -------------------------------------------------------------------------

    async def setup(self) -> None:
        """Initialize and start the presence handler tasks."""
        if self._running:
            logger.warning("Presence Handler Already Running", [
                ("Action", "Skipping setup"),
            ])
            return

        self._running = True

        # Start rotation task
        self._rotation_task = asyncio.create_task(
            self._rotation_loop(),
            name="presence_rotation"
        )
        self._rotation_task.add_done_callback(self._handle_task_exception)

        # Start promo task
        self._promo_task = asyncio.create_task(
            self._promo_loop(),
            name="presence_promo"
        )
        self._promo_task.add_done_callback(self._handle_task_exception)

        logger.success("✅ Presence Handler Ready", [
            ("Rotation", f"Every {PRESENCE_UPDATE_INTERVAL}s"),
            ("Promo", f"{PROMO_DURATION_MINUTES} min/hour"),
        ])

    async def stop(self) -> None:
        """Stop the presence handler tasks."""
        self._running = False

        if self._rotation_task:
            self._rotation_task.cancel()
            try:
                await self._rotation_task
            except asyncio.CancelledError:
                pass
            self._rotation_task = None

        if self._promo_task:
            self._promo_task.cancel()
            try:
                await self._promo_task
            except asyncio.CancelledError:
                pass
            self._promo_task = None

        logger.info("🛑 Presence Handler Stopped", [
            ("Status", "Tasks cancelled"),
        ])


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
