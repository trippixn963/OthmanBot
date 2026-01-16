"""
OthmanBot - Maintenance Scheduler Service
==========================================

Handles periodic maintenance tasks:
- Engagement metrics checking
- Cache and metrics cleanup
- Database maintenance

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.services.database import get_db
from src.core.emojis import UPVOTE_EMOJI, DOWNVOTE_EMOJI

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Maintenance Scheduler
# =============================================================================

class MaintenanceScheduler:
    """
    Handles periodic maintenance tasks.

    - Engagement checking: Every 2 hours
    - Cleanup: Every 6 hours
    """

    def __init__(self, bot: "OthmanBot") -> None:
        """Initialize the maintenance scheduler."""
        self.bot = bot
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._db = get_db()

        # Intervals in seconds
        self.engagement_interval: int = 7200  # 2 hours
        self.cleanup_interval: int = 21600  # 6 hours

        # Track last run times
        self._last_engagement_check: float = 0
        self._last_cleanup: float = 0

    # -------------------------------------------------------------------------
    # Start/Stop
    # -------------------------------------------------------------------------

    def _handle_task_exception(self, task: asyncio.Task) -> None:
        """Handle exceptions from the scheduler task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.tree("Maintenance Scheduler Task Exception", [
                ("Error Type", type(exc).__name__),
                ("Error", str(exc)[:100]),
            ], emoji="❌")

    def start(self) -> None:
        """Start the maintenance scheduler."""
        if self.is_running:
            logger.tree("Maintenance Scheduler Already Running", [
                ("Status", "Skipped"),
            ], emoji="⚠️")
            return

        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())
        self._task.add_done_callback(self._handle_task_exception)
        logger.tree("Maintenance Scheduler Started", [
            ("Engagement Interval", f"{self.engagement_interval // 3600}h"),
            ("Cleanup Interval", f"{self.cleanup_interval // 3600}h"),
        ], emoji="🔧")

    def stop(self) -> None:
        """Stop the maintenance scheduler."""
        if not self.is_running:
            return

        self.is_running = False
        if self._task:
            self._task.cancel()
            self._task = None

        logger.tree("Maintenance Scheduler Stopped", [
            ("Status", "Stopped"),
        ], emoji="🛑")

    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        import time

        # Initial delay to let bot fully start
        await asyncio.sleep(30)

        while self.is_running:
            try:
                now = time.time()

                # Check engagement
                if now - self._last_engagement_check >= self.engagement_interval:
                    await self._check_engagement()
                    self._last_engagement_check = now

                # Run cleanup
                if now - self._last_cleanup >= self.cleanup_interval:
                    await self._run_cleanup()
                    self._last_cleanup = now

                # Sleep for 5 minutes before next check
                await asyncio.sleep(300)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.tree("Maintenance Scheduler Error", [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)[:80]),
                ], emoji="❌")
                await asyncio.sleep(60)

    # -------------------------------------------------------------------------
    # Engagement Checking
    # -------------------------------------------------------------------------

    async def _check_engagement(self) -> None:
        """Check engagement metrics for recent articles."""
        logger.tree("Engagement Check Starting", [
            ("Content Types", "news, soccer"),
        ], emoji="📊")

        total_checked = 0
        total_updated = 0

        for content_type in ["news", "soccer"]:
            articles = self._db.get_articles_to_check(content_type, hours_since_post=72)

            for article in articles:
                try:
                    thread_id = article["thread_id"]
                    thread = self.bot.get_channel(thread_id)

                    if not thread or not isinstance(thread, discord.Thread):
                        continue

                    # Get starter message for reactions
                    starter_message = thread.starter_message
                    if not starter_message:
                        try:
                            starter_message = await thread.fetch_message(thread_id)
                        except discord.NotFound:
                            continue

                    # Count reactions
                    upvotes = 0
                    downvotes = 0
                    for reaction in starter_message.reactions:
                        emoji_str = str(reaction.emoji)
                        if UPVOTE_EMOJI in emoji_str or "upvote" in emoji_str.lower():
                            upvotes = reaction.count - 1  # Subtract bot's reaction
                        elif DOWNVOTE_EMOJI in emoji_str or "downvote" in emoji_str.lower():
                            downvotes = reaction.count

                    # Count replies (message count - 1 for starter)
                    replies = thread.message_count - 1 if thread.message_count > 0 else 0

                    # Update database
                    self._db.update_article_engagement(
                        thread_id=thread_id,
                        upvotes=max(0, upvotes),
                        downvotes=max(0, downvotes),
                        replies=max(0, replies),
                    )

                    total_checked += 1
                    if upvotes > 0 or replies > 0:
                        total_updated += 1

                except Exception as e:
                    logger.tree("Engagement Check Error", [
                        ("Thread ID", str(article.get("thread_id", "unknown"))),
                        ("Error", str(e)[:50]),
                    ], emoji="⚠️")
                    continue

        logger.tree("Engagement Check Complete", [
            ("Threads Checked", str(total_checked)),
            ("With Engagement", str(total_updated)),
        ], emoji="✅")

    # -------------------------------------------------------------------------
    # Cleanup Tasks
    # -------------------------------------------------------------------------

    async def _run_cleanup(self) -> None:
        """Run all cleanup tasks."""
        logger.tree("Cleanup Tasks Starting", [
            ("Tasks", "metrics, content_hashes, temp_files"),
        ], emoji="🧹")

        # Cleanup metrics (older than 7 days)
        metrics_removed = self._db.cleanup_metrics(days_to_keep=7)

        # Cleanup content hashes
        hashes_removed = self._db.cleanup_content_hashes()

        # Cleanup temp files
        temp_removed = await self._cleanup_temp_files()

        logger.tree("Cleanup Tasks Complete", [
            ("Metrics Removed", str(metrics_removed)),
            ("Hashes Removed", str(hashes_removed)),
            ("Temp Files Removed", str(temp_removed)),
        ], emoji="✅")

    async def _cleanup_temp_files(self) -> int:
        """Remove old temporary media files."""
        import os
        import time
        from pathlib import Path

        temp_dir = Path("data/temp_media")
        if not temp_dir.exists():
            return 0

        removed = 0
        cutoff = time.time() - 86400  # 24 hours

        for file_path in temp_dir.iterdir():
            if file_path.is_file():
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                        removed += 1
                except Exception as e:
                    logger.debug("Temp File Cleanup Skipped", [
                        ("File", str(file_path.name)),
                        ("Error", str(e)[:50]),
                    ])

        return removed

    # -------------------------------------------------------------------------
    # Cache Warming
    # -------------------------------------------------------------------------

    async def warm_cache(self) -> None:
        """
        Warm the cache on startup.

        Pre-loads recent article IDs and content hashes into memory.
        """
        logger.tree("Cache Warming Starting", [
            ("Content Types", "news, soccer"),
        ], emoji="🔥")

        # The scrapers already load posted URLs on init
        # This method ensures content hashes are also available

        for content_type in ["news", "soccer"]:
            # Get recent content for similarity checking
            recent = self._db.get_recent_content(content_type, limit=50)
            count = len(recent)

            logger.tree("Cache Warmed", [
                ("Content Type", content_type),
                ("Articles Loaded", str(count)),
            ], emoji="✅")

        logger.tree("Cache Warming Complete", [
            ("Status", "Ready"),
        ], emoji="🔥")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MaintenanceScheduler"]
