"""
OthmanBot - Karma Reconciliation
==========================================

Reconciles karma based on actual Discord reactions.
Runs on startup and nightly to catch any missed votes.
Also ensures starter messages have vote reactions.
Cleans up orphaned votes from deleted messages.

Features rate limit awareness with automatic backoff.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, DISCORD_ARCHIVED_THREADS_LIMIT, DISCORD_API_DELAY, REACTION_DELAY, LOG_TITLE_PREVIEW_LENGTH
from src.core.emojis import UPVOTE_EMOJI, DOWNVOTE_EMOJI

# Constants for orphan cleanup
ORPHAN_CLEANUP_BATCH_SIZE = 50  # Process orphans in batches to avoid memory issues
ORPHAN_CLEANUP_API_DELAY = 0.1  # Small delay between message existence checks

# Rate limit backoff settings
RATE_LIMIT_BASE_DELAY = 5.0  # Base delay when rate limited (seconds)
RATE_LIMIT_MAX_DELAY = 60.0  # Maximum backoff delay (seconds)

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Karma Reconciliation
# =============================================================================

async def reconcile_karma(bot: "OthmanBot", days_back: int | None = 7) -> dict:
    """
    Reconcile karma by scanning debate threads and comparing actual reactions
    with stored votes in the database.

    This catches any votes that were missed while the bot was offline.

    Args:
        bot: The OthmanBot instance
        days_back: How many days back to scan threads (default 7), or None for ALL threads

    Returns:
        Dict with reconciliation stats
    """
    stats = {
        "threads_scanned": 0,
        "messages_scanned": 0,
        "votes_added": 0,
        "votes_removed": 0,
        "reactions_fixed": 0,
        "self_reactions_removed": 0,
        "errors": 0,
    }

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            logger.warning("⚠️ Debates Forum Not Found", [
                ("Context", "Karma reconciliation"),
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])
            return stats

        # Get cutoff time for thread scanning (None = no cutoff, scan all)
        cutoff_time = None
        if days_back is not None:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_back)

        # Collect all active threads
        threads_to_scan = []

        # Get Open Discussion thread ID to skip it (no karma tracking)
        open_discussion_thread_id = None
        if hasattr(bot, 'open_discussion') and bot.open_discussion:
            open_discussion_thread_id = bot.open_discussion.get_thread_id()

        # Active threads (skip deprecated and open discussion)
        for thread in debates_forum.threads:
            if thread.name.startswith("[DEPRECATED]"):
                continue
            # Skip Open Discussion thread (no karma tracking)
            if open_discussion_thread_id and thread.id == open_discussion_thread_id:
                continue
            # If no cutoff, include all; otherwise check date
            if cutoff_time is None or (thread.created_at and thread.created_at > cutoff_time):
                threads_to_scan.append(thread)

        # Recently archived threads (skip deprecated and open discussion)
        async for thread in debates_forum.archived_threads(limit=DISCORD_ARCHIVED_THREADS_LIMIT):
            if thread.name.startswith("[DEPRECATED]"):
                continue
            # Skip Open Discussion thread (no karma tracking)
            if open_discussion_thread_id and thread.id == open_discussion_thread_id:
                continue
            # If no cutoff, include all; otherwise check date
            if cutoff_time is None or (thread.created_at and thread.created_at > cutoff_time):
                threads_to_scan.append(thread)

        logger.info("🔄 Reconciling Karma", [
            ("Threads", str(len(threads_to_scan))),
        ])

        # Track consecutive rate limits for adaptive backoff
        consecutive_rate_limits = 0
        adaptive_delay = DISCORD_API_DELAY

        for thread in threads_to_scan:
            try:
                # Ensure starter message has vote reactions (in correct order)
                rate_limit_delay = await _ensure_starter_reactions(thread, stats, bot)

                # If rate limited, back off before continuing
                if rate_limit_delay > 0:
                    consecutive_rate_limits += 1
                    # Exponential backoff: increase base delay
                    adaptive_delay = min(
                        adaptive_delay * (1.5 ** consecutive_rate_limits),
                        RATE_LIMIT_MAX_DELAY
                    )
                    logger.info("Rate Limit Backoff", [
                        ("Waiting", f"{rate_limit_delay:.1f}s"),
                        ("Adaptive Delay", f"{adaptive_delay:.1f}s"),
                        ("Consecutive Limits", str(consecutive_rate_limits)),
                    ])
                    await asyncio.sleep(rate_limit_delay + 1.0)  # Add buffer
                else:
                    # Reset consecutive count on success
                    consecutive_rate_limits = max(0, consecutive_rate_limits - 1)
                    # Gradually reduce adaptive delay back to normal
                    adaptive_delay = max(DISCORD_API_DELAY, adaptive_delay * 0.9)

                # Reconcile karma votes
                await _reconcile_thread(bot, thread, stats)
                stats["threads_scanned"] += 1

                # Use adaptive delay between threads
                await asyncio.sleep(adaptive_delay)

            except discord.HTTPException as e:
                if e.status == 429:
                    # Rate limited at thread level - back off significantly
                    retry_after = getattr(e, 'retry_after', RATE_LIMIT_BASE_DELAY)
                    consecutive_rate_limits += 1
                    adaptive_delay = min(
                        adaptive_delay * 2,
                        RATE_LIMIT_MAX_DELAY
                    )
                    logger.warning("Thread Reconciliation Rate Limited", [
                        ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                        ("Retry After", f"{retry_after:.1f}s"),
                        ("Consecutive Limits", str(consecutive_rate_limits)),
                    ])
                    await asyncio.sleep(retry_after + 2.0)
                    stats["errors"] += 1
                else:
                    logger.error("Error Reconciling Thread", [
                        ("Thread ID", str(thread.id)),
                        ("Error", str(e)),
                    ])
                    stats["errors"] += 1
            except Exception as e:
                logger.error("Error Reconciling Thread", [
                    ("Thread ID", str(thread.id)),
                    ("Error", str(e)),
                ])
                stats["errors"] += 1

        logger.success("✅ Karma Reconciliation Complete", [
            ("Threads", str(stats['threads_scanned'])),
            ("Messages", str(stats['messages_scanned'])),
            ("Added", f"+{stats['votes_added']}"),
            ("Removed", f"-{stats['votes_removed']}"),
            ("Reactions Fixed", str(stats['reactions_fixed'])),
            ("Self-Reactions Removed", str(stats['self_reactions_removed'])),
        ])

    except Exception as e:
        logger.error("Failed To Reconcile Karma", [
            ("Error", str(e)),
        ])
        stats["errors"] += 1

    return stats


async def _ensure_starter_reactions(thread: discord.Thread, stats: dict, bot: "OthmanBot" = None) -> float:
    """
    Ensure the starter message has upvote and downvote reactions in correct order.

    Checks for:
    1. Missing reactions - adds them
    2. Wrong order (downvote before upvote) - removes and re-adds in correct order

    Args:
        thread: Discord thread to check
        stats: Stats dict to update
        bot: Bot instance (needed to remove bot's own reactions)

    Returns:
        Additional delay needed if rate limited (0.0 if not)
    """
    rate_limit_delay = 0.0

    # Skip archived threads - can't add reactions
    if thread.archived:
        logger.debug("Skipping Archived Thread (Reactions)", [
            ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
        ])
        return rate_limit_delay

    try:
        # Fetch starter message (same ID as thread)
        starter_message = await thread.fetch_message(thread.id)

        # Check if upvote reaction exists (only upvote on original posts)
        has_upvote = any(
            str(reaction.emoji) == UPVOTE_EMOJI
            for reaction in starter_message.reactions
        )

        # Add missing upvote reaction
        if not has_upvote:
            try:
                await starter_message.add_reaction(UPVOTE_EMOJI)
                stats["reactions_fixed"] += 1
                logger.info("Added Missing Upvote Reaction", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ])
                await asyncio.sleep(REACTION_DELAY)
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = getattr(e, 'retry_after', RATE_LIMIT_BASE_DELAY)
                    rate_limit_delay = max(rate_limit_delay, retry_after)
                    logger.warning("Rate Limited Adding Upvote Reaction", [
                        ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                        ("Retry After", f"{retry_after:.1f}s"),
                    ])
                else:
                    raise

    except discord.NotFound:
        logger.debug("Starter Message Not Found", [
            ("Thread ID", str(thread.id)),
        ])
    except discord.HTTPException as e:
        if e.status == 429:
            retry_after = getattr(e, 'retry_after', RATE_LIMIT_BASE_DELAY)
            rate_limit_delay = retry_after
            logger.warning("Rate Limited Fetching Starter Message", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Retry After", f"{retry_after:.1f}s"),
            ])
        else:
            logger.warning("Failed To Fix Starter Reactions", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Error", str(e)),
            ])

    return rate_limit_delay


async def _reconcile_thread(bot: "OthmanBot", thread: discord.Thread, stats: dict) -> None:
    """
    Reconcile karma for a single thread.

    Also removes self-reactions (users who reacted to their own message).

    Args:
        bot: The OthmanBot instance
        thread: Discord thread to reconcile
        stats: Stats dict to update
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        logger.warning("Skipping Thread Reconciliation - Debates Service Not Available", [
            ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
        ])
        return

    db = bot.debates_service.db

    async for message in thread.history(limit=1000):
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
            # Skip reactions with 0 count (shouldn't happen but safety check)
            if reaction.count == 0:
                continue
            if emoji_str == UPVOTE_EMOJI:
                async for user in reaction.users():
                    if user.bot:
                        continue
                    # Check for self-reaction and remove it
                    if user.id == author_id:
                        try:
                            await reaction.remove(user)
                            stats["self_reactions_removed"] += 1
                            logger.info("Removed Self-Reaction (Reconciliation)", [
                                ("User", f"{user.name} ({user.display_name})"),
                                ("ID", str(user.id)),
                                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                                ("Message ID", str(message.id)),
                                ("Emoji", "⬆️"),
                            ])
                            await asyncio.sleep(REACTION_DELAY)
                        except discord.HTTPException as e:
                            logger.warning("Failed To Remove Self-Reaction", [
                                ("Error", str(e)),
                            ])
                    else:
                        actual_upvoters.add(user.id)
            elif emoji_str == DOWNVOTE_EMOJI:
                async for user in reaction.users():
                    if user.bot:
                        continue
                    # Check for self-reaction and remove it
                    if user.id == author_id:
                        try:
                            await reaction.remove(user)
                            stats["self_reactions_removed"] += 1
                            logger.info("Removed Self-Reaction (Reconciliation)", [
                                ("User", f"{user.name} ({user.display_name})"),
                                ("ID", str(user.id)),
                                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                                ("Message ID", str(message.id)),
                                ("Emoji", "⬇️"),
                            ])
                            await asyncio.sleep(REACTION_DELAY)
                        except discord.HTTPException as e:
                            logger.warning("Failed To Remove Self-Reaction", [
                                ("Error", str(e)),
                            ])
                    else:
                        actual_downvoters.add(user.id)

        # Get stored votes from database
        stored_votes = db.get_message_votes(message.id)

        # Find missing upvotes (in Discord but not in DB)
        for voter_id in actual_upvoters:
            if voter_id not in stored_votes or stored_votes[voter_id] != 1:
                # Add missing upvote
                if db.add_vote(voter_id, message.id, author_id, 1):
                    stats["votes_added"] += 1
                    logger.debug("Added Missing Upvote", [
                        ("ID", str(voter_id)),
                        ("Message", str(message.id)),
                    ])

        # Find missing downvotes (in Discord but not in DB)
        for voter_id in actual_downvoters:
            if voter_id not in stored_votes or stored_votes[voter_id] != -1:
                # Add missing downvote
                if db.add_vote(voter_id, message.id, author_id, -1):
                    stats["votes_added"] += 1
                    logger.debug("Added Missing Downvote", [
                        ("ID", str(voter_id)),
                        ("Message", str(message.id)),
                    ])

        # Find stale votes (in DB but not in Discord)
        all_actual_voters = actual_upvoters | actual_downvoters
        for voter_id, vote_type in stored_votes.items():
            if voter_id not in all_actual_voters:
                # Remove stale vote
                if db.remove_vote(voter_id, message.id):
                    stats["votes_removed"] += 1
                    logger.debug("Removed Stale Vote", [
                        ("ID", str(voter_id)),
                        ("Message", str(message.id)),
                    ])


# =============================================================================
# Orphan Vote Cleanup
# =============================================================================

async def cleanup_orphan_votes(bot: "OthmanBot") -> dict:
    """
    Find and clean up votes for messages that no longer exist.

    This function:
    1. Gets all message IDs with votes from the database
    2. Checks if each message still exists in Discord
    3. Removes votes for non-existent messages and reverses karma

    Args:
        bot: The OthmanBot instance

    Returns:
        Dict with cleanup stats
    """
    stats = {
        "messages_checked": 0,
        "orphans_found": 0,
        "votes_cleaned": 0,
        "karma_reversed": 0,
        "errors": 0,
    }

    try:
        db = bot.debates_service.db
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)

        if not debates_forum:
            logger.warning("⚠️ Debates Forum Not Found", [
                ("Context", "Orphan cleanup"),
                ("Forum ID", str(DEBATES_FORUM_ID)),
            ])
            return stats

        # Get all message IDs that have votes
        voted_message_ids = db.get_all_voted_message_ids()
        total_messages = len(voted_message_ids)

        if total_messages == 0:
            logger.info("🧹 No Votes To Check For Orphans", [
                ("Action", "Skipping orphan cleanup"),
            ])
            return stats

        logger.info("🧹 Checking For Orphan Votes", [
            ("Messages With Votes", str(total_messages)),
        ])

        # Build a set of all valid message IDs from debate threads
        valid_message_ids: set[int] = set()
        orphan_message_ids: set[int] = set()

        # Collect all threads (active and archived)
        all_threads = list(debates_forum.threads)
        async for thread in debates_forum.archived_threads(limit=DISCORD_ARCHIVED_THREADS_LIMIT):
            all_threads.append(thread)

        logger.info("📂 Scanning Threads For Valid Messages", [
            ("Thread Count", str(len(all_threads))),
        ])

        # Scan each thread to collect valid message IDs (with rate limit awareness)
        adaptive_delay = DISCORD_API_DELAY
        consecutive_rate_limits = 0

        for thread in all_threads:
            if thread.name.startswith("[DEPRECATED]"):
                continue

            try:
                async for message in thread.history(limit=1000):
                    if not message.author.bot:
                        valid_message_ids.add(message.id)
                        stats["messages_checked"] += 1

                # Success - gradually reduce delay
                consecutive_rate_limits = max(0, consecutive_rate_limits - 1)
                adaptive_delay = max(DISCORD_API_DELAY, adaptive_delay * 0.9)
                await asyncio.sleep(adaptive_delay)

            except discord.NotFound:
                # Thread deleted during scan - log and track
                stats["threads_deleted_during_scan"] = stats.get("threads_deleted_during_scan", 0) + 1
                logger.debug("Thread Deleted During Orphan Scan", [
                    ("Thread ID", str(thread.id)),
                ])
                continue
            except discord.HTTPException as e:
                if e.status == 429:
                    # Rate limited - back off
                    retry_after = getattr(e, 'retry_after', RATE_LIMIT_BASE_DELAY)
                    consecutive_rate_limits += 1
                    adaptive_delay = min(adaptive_delay * 2, RATE_LIMIT_MAX_DELAY)
                    logger.warning("Orphan Scan Rate Limited", [
                        ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                        ("Retry After", f"{retry_after:.1f}s"),
                        ("Adaptive Delay", f"{adaptive_delay:.1f}s"),
                    ])
                    await asyncio.sleep(retry_after + 1.0)
                else:
                    logger.warning("Error Scanning Thread For Messages", [
                        ("Thread ID", str(thread.id)),
                        ("Error", str(e)),
                    ])
                stats["errors"] += 1

        # Find orphaned message IDs (votes exist but message doesn't)
        orphan_message_ids = voted_message_ids - valid_message_ids
        stats["orphans_found"] = len(orphan_message_ids)

        if not orphan_message_ids:
            logger.success("✅ Orphan Vote Check Complete - No Orphans Found", [
                ("Messages Checked", str(stats["messages_checked"])),
                ("Votes Checked", str(total_messages)),
            ])
            return stats

        logger.info("🗑️ Found Orphan Votes To Clean", [
            ("Orphan Messages", str(len(orphan_message_ids))),
            ("Valid Messages", str(len(valid_message_ids))),
        ])

        # Clean up orphaned votes (database method handles karma reversal)
        cleanup_result = db.cleanup_orphaned_votes(orphan_message_ids)
        stats["votes_cleaned"] = cleanup_result.get("votes_deleted", 0)
        stats["karma_reversed"] = cleanup_result.get("karma_reversed", 0)
        stats["errors"] += cleanup_result.get("errors", 0)

        logger.success("🧹 Orphan Vote Cleanup Complete", [
            ("Messages Checked", str(stats["messages_checked"])),
            ("Orphans Found", str(stats["orphans_found"])),
            ("Votes Cleaned", str(stats["votes_cleaned"])),
            ("Karma Reversed", str(stats["karma_reversed"])),
            ("Errors", str(stats["errors"])),
        ])

    except Exception as e:
        logger.error("Failed To Cleanup Orphan Votes", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
        ])
        stats["errors"] += 1

    return stats


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["reconcile_karma", "cleanup_orphan_votes"]
