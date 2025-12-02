"""
Othman Discord Bot - Shutdown Handler
======================================

Graceful shutdown and cleanup logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Shutdown Handler
# =============================================================================

async def shutdown_handler(bot: "OthmanBot") -> None:
    """
    Cleanup when bot is shutting down.

    Args:
        bot: The OthmanBot instance

    DESIGN: Properly close all services and sessions
    Prevents resource leaks and ensures state is saved
    """
    logger.info("Shutting down Othman Bot...")

    # Stop presence update loop
    if bot.presence_task and not bot.presence_task.done():
        bot.presence_task.cancel()
        try:
            await bot.presence_task
        except asyncio.CancelledError:
            pass

    # Stop content rotation scheduler
    if bot.content_rotation_scheduler and bot.content_rotation_scheduler.is_running:
        await bot.content_rotation_scheduler.stop()

    # Close news scraper session
    if bot.news_scraper:
        await bot.news_scraper.__aexit__(None, None, None)

    # Close soccer scraper session
    if bot.soccer_scraper:
        await bot.soccer_scraper.__aexit__(None, None, None)

    # Close gaming scraper session
    if bot.gaming_scraper:
        await bot.gaming_scraper.__aexit__(None, None, None)

    # Stop debates scheduler
    if hasattr(bot, 'debates_scheduler') and bot.debates_scheduler:
        if bot.debates_scheduler.is_running:
            await bot.debates_scheduler.stop()

    # Stop hot tag manager
    if hasattr(bot, 'hot_tag_manager') and bot.hot_tag_manager:
        await bot.hot_tag_manager.stop()

    logger.success("Bot shutdown complete")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["shutdown_handler"]
