"""
Othman Discord Bot - Shutdown Handler
======================================

Graceful shutdown and cleanup logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, List, Tuple, Any

from src.core.logger import logger
from src.core.presence import stop_promo_scheduler
from src.services.webhook_alerts import get_alert_service

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

SHUTDOWN_TIMEOUT = 10.0  # Maximum seconds to wait for cleanup tasks


# =============================================================================
# Shutdown Handler
# =============================================================================

async def _safe_cleanup(name: str, cleanup_coro: Any) -> bool:
    """
    Execute a cleanup coroutine with error handling.

    Args:
        name: Name of the cleanup task for logging
        cleanup_coro: Coroutine to execute

    Returns:
        True if cleanup succeeded, False otherwise
    """
    try:
        await cleanup_coro
        logger.debug("Cleanup Complete", [
            ("Task", name),
        ])
        return True
    except asyncio.CancelledError:
        logger.debug("Cleanup Cancelled", [
            ("Task", name),
        ])
        return True
    except asyncio.TimeoutError:
        logger.warning("Cleanup Timed Out", [
            ("Task", name),
        ])
        return False
    except Exception as e:
        # Catch remaining exceptions but exclude system exit signals
        logger.warning("Cleanup Failed", [
            ("Task", name),
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
        ])
        return False


async def shutdown_handler(bot: "OthmanBot") -> None:
    """
    Cleanup when bot is shutting down.

    Args:
        bot: The OthmanBot instance

    DESIGN: Properly close all services and sessions
    Prevents resource leaks and ensures state is saved
    Each cleanup is wrapped in error handling so one failure
    doesn't prevent other cleanups from running.
    """
    logger.info("Shutting Down Othman Bot", [
        ("Timeout", f"{SHUTDOWN_TIMEOUT}s"),
    ])

    # Update status channel to show offline
    try:
        await bot.update_status_channel(online=False)
    except Exception as e:
        logger.debug("Status Channel Update Failed", [
            ("Error", str(e)),
        ])

    # Stop hourly alerts (shutdown alert not needed - crash alerts are sufficient)
    try:
        alert_service = get_alert_service()
        alert_service.stop_hourly_alerts()
    except Exception as e:
        logger.debug("Failed To Stop Hourly Alerts", [
            ("Error", str(e)),
        ])

    cleanup_tasks: List[Tuple[str, Any]] = []

    # 1. Cancel all tracked background tasks
    if hasattr(bot, '_background_tasks'):
        for task in bot._background_tasks:
            if not task.done():
                task.cancel()
                cleanup_tasks.append((f"Background Task ({task.get_name()})", _cancel_task(task)))

    # 2. Stop presence update loop and promo scheduler
    if bot.presence_task and not bot.presence_task.done():
        bot.presence_task.cancel()
        cleanup_tasks.append(("Presence Task", _cancel_task(bot.presence_task)))
    cleanup_tasks.append(("Promo Scheduler", stop_promo_scheduler()))

    # 3. Stop content rotation scheduler
    if bot.content_rotation_scheduler:
        if hasattr(bot.content_rotation_scheduler, 'is_running') and bot.content_rotation_scheduler.is_running:
            cleanup_tasks.append(("Content Rotation Scheduler", bot.content_rotation_scheduler.stop()))

    # 4. Close news scraper session
    if bot.news_scraper:
        cleanup_tasks.append(("News Scraper", bot.news_scraper.__aexit__(None, None, None)))

    # 5. Close soccer scraper session
    if bot.soccer_scraper:
        cleanup_tasks.append(("Soccer Scraper", bot.soccer_scraper.__aexit__(None, None, None)))

    # 6. Stop debates scheduler
    if hasattr(bot, 'debates_scheduler') and bot.debates_scheduler:
        if hasattr(bot.debates_scheduler, 'is_running') and bot.debates_scheduler.is_running:
            cleanup_tasks.append(("Debates Scheduler", bot.debates_scheduler.stop()))

    # 8. Stop hot tag manager
    if hasattr(bot, 'hot_tag_manager') and bot.hot_tag_manager:
        cleanup_tasks.append(("Hot Tag Manager", bot.hot_tag_manager.stop()))

    # 9. Stop karma reconciliation scheduler
    if hasattr(bot, 'karma_reconciliation_scheduler') and bot.karma_reconciliation_scheduler:
        if hasattr(bot.karma_reconciliation_scheduler, 'is_running') and bot.karma_reconciliation_scheduler.is_running:
            cleanup_tasks.append(("Karma Reconciliation Scheduler", bot.karma_reconciliation_scheduler.stop()))

    # 10. Stop numbering reconciliation scheduler
    if hasattr(bot, 'numbering_reconciliation_scheduler') and bot.numbering_reconciliation_scheduler:
        if hasattr(bot.numbering_reconciliation_scheduler, 'is_running') and bot.numbering_reconciliation_scheduler.is_running:
            cleanup_tasks.append(("Numbering Reconciliation Scheduler", bot.numbering_reconciliation_scheduler.stop()))

    # 11. Stop backup scheduler
    if hasattr(bot, 'backup_scheduler') and bot.backup_scheduler:
        if hasattr(bot.backup_scheduler, 'is_running') and bot.backup_scheduler.is_running:
            cleanup_tasks.append(("Backup Scheduler", bot.backup_scheduler.stop()))

    # 12. Close database connection
    if hasattr(bot, 'debates_service') and bot.debates_service:
        if hasattr(bot.debates_service, 'db') and bot.debates_service.db:
            cleanup_tasks.append(("Debates Database", _close_database(bot.debates_service.db)))

    # 13. Stop health check HTTP server
    if hasattr(bot, 'health_server') and bot.health_server:
        cleanup_tasks.append(("Health Check Server", bot.health_server.stop()))

    # 14. Close interaction logger session
    if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
        cleanup_tasks.append(("Interaction Logger", bot.interaction_logger.close()))

    # Execute all cleanup tasks with timeout
    if cleanup_tasks:
        try:
            async with asyncio.timeout(SHUTDOWN_TIMEOUT):
                results = await asyncio.gather(
                    *[_safe_cleanup(name, coro) for name, coro in cleanup_tasks],
                    return_exceptions=True
                )

                successful = sum(1 for r in results if r is True)
                failed = len(results) - successful

                logger.info("Shutdown Cleanup Complete", [
                    ("Successful", str(successful)),
                    ("Failed", str(failed)),
                ])

        except asyncio.TimeoutError:
            logger.warning("Shutdown Cleanup Timed Out", [
                ("Timeout", f"{SHUTDOWN_TIMEOUT}s"),
                ("Note", "Some tasks may not have completed"),
            ])
    else:
        logger.info("No Cleanup Tasks Required")

    logger.tree("Bot Shutdown Complete", [
        ("Status", "All services stopped"),
    ], emoji="👋")


async def _cancel_task(task: asyncio.Task) -> None:
    """Cancel an asyncio task and wait for it."""
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _close_database(db: Any) -> None:
    """Close database connection."""
    if hasattr(db, 'close'):
        if asyncio.iscoroutinefunction(db.close):
            await db.close()
        else:
            db.close()
    elif hasattr(db, 'connection') and db.connection:
        db.connection.close()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["shutdown_handler"]
