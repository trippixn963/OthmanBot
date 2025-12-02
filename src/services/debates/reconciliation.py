"""
Othman Discord Bot - Karma Reconciliation
==========================================

Reconciles karma based on actual Discord reactions.
Runs on startup and nightly to catch any missed votes.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Karma Reconciliation
# =============================================================================

async def reconcile_karma(bot: "OthmanBot", days_back: int = 7) -> dict:
    """
    Reconcile karma by scanning debate threads and comparing actual reactions
    with stored votes in the database.

    This catches any votes that were missed while the bot was offline.

    Args:
        bot: The OthmanBot instance
        days_back: How many days back to scan threads (default 7)

    Returns:
        Dict with reconciliation stats
    """
    stats = {
        "threads_scanned": 0,
        "messages_scanned": 0,
        "votes_added": 0,
        "votes_removed": 0,
        "errors": 0,
    }

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            logger.warning("⚠️ Debates forum not found for karma reconciliation")
            return stats

        # Get cutoff time for thread scanning
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_back)

        # Collect all active threads
        threads_to_scan = []

        # Active threads
        for thread in debates_forum.threads:
            if thread.created_at and thread.created_at > cutoff_time:
                threads_to_scan.append(thread)

        # Recently archived threads
        async for thread in debates_forum.archived_threads(limit=50):
            if thread.created_at and thread.created_at > cutoff_time:
                threads_to_scan.append(thread)

        logger.info(f"🔄 Reconciling karma for {len(threads_to_scan)} threads...")

        for thread in threads_to_scan:
            try:
                await _reconcile_thread(bot, thread, stats)
                stats["threads_scanned"] += 1
                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error reconciling thread {thread.id}: {e}")
                stats["errors"] += 1

        logger.success(
            f"✅ Karma reconciliation complete: "
            f"{stats['threads_scanned']} threads, "
            f"{stats['messages_scanned']} messages, "
            f"+{stats['votes_added']} votes added, "
            f"-{stats['votes_removed']} votes removed"
        )

    except Exception as e:
        logger.error(f"Failed to reconcile karma: {e}")
        stats["errors"] += 1

    return stats


async def _reconcile_thread(bot: "OthmanBot", thread: discord.Thread, stats: dict) -> None:
    """
    Reconcile karma for a single thread.

    Args:
        bot: The OthmanBot instance
        thread: Discord thread to reconcile
        stats: Stats dict to update
    """
    db = bot.debates_service.db

    async for message in thread.history(limit=None):
        # Skip bot messages
        if message.author.bot:
            continue

        stats["messages_scanned"] += 1
        author_id = message.author.id

        # Get actual reactions from Discord
        actual_upvoters = set()
        actual_downvoters = set()

        for reaction in message.reactions:
            emoji_str = str(reaction.emoji)
            if emoji_str == "\u2b06\ufe0f":  # ⬆️
                async for user in reaction.users():
                    if not user.bot and user.id != author_id:
                        actual_upvoters.add(user.id)
            elif emoji_str == "\u2b07\ufe0f":  # ⬇️
                async for user in reaction.users():
                    if not user.bot and user.id != author_id:
                        actual_downvoters.add(user.id)

        # Get stored votes from database
        stored_votes = db.get_message_votes(message.id)

        # Find missing upvotes (in Discord but not in DB)
        for voter_id in actual_upvoters:
            if voter_id not in stored_votes or stored_votes[voter_id] != 1:
                # Add missing upvote
                if db.add_vote(voter_id, message.id, author_id, 1):
                    stats["votes_added"] += 1
                    logger.debug(f"Added missing upvote: {voter_id} -> {message.id}")

        # Find missing downvotes (in Discord but not in DB)
        for voter_id in actual_downvoters:
            if voter_id not in stored_votes or stored_votes[voter_id] != -1:
                # Add missing downvote
                if db.add_vote(voter_id, message.id, author_id, -1):
                    stats["votes_added"] += 1
                    logger.debug(f"Added missing downvote: {voter_id} -> {message.id}")

        # Find stale votes (in DB but not in Discord)
        all_actual_voters = actual_upvoters | actual_downvoters
        for voter_id, vote_type in stored_votes.items():
            if voter_id not in all_actual_voters:
                # Remove stale vote
                if db.remove_vote(voter_id, message.id):
                    stats["votes_removed"] += 1
                    logger.debug(f"Removed stale vote: {voter_id} -> {message.id}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["reconcile_karma"]
