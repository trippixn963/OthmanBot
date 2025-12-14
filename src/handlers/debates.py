"""
Othman Discord Bot - Debates Handler
=====================================

Auto-react with upvote/downvote on forum thread replies and track karma.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import fcntl
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING
import discord

from src.core.logger import logger
from src.utils import (
    add_reactions_with_delay,
    send_message_with_retry,
    edit_message_with_retry,
    edit_thread_with_retry,
    delete_message_safe,
    remove_reaction_safe,
    safe_fetch_message,
    is_primarily_arabic,
    get_min_message_length,
    is_english_only,
)

if TYPE_CHECKING:
    from src.bot import OthmanBot
from src.core.config import (
    DEBATES_FORUM_ID,
    MODERATOR_ROLE_ID,
    DEVELOPER_ID,
    MIN_MESSAGE_LENGTH,
    MIN_MESSAGE_LENGTH_ARABIC,
    ANALYTICS_UPDATE_COOLDOWN,
    ANALYTICS_CACHE_MAX_SIZE,
    ANALYTICS_CACHE_CLEANUP_AGE,
    DISCORD_API_DELAY,
    REACTION_DELAY,
)
from src.services.debates.analytics import (
    calculate_debate_analytics,
    generate_analytics_embed,
)
from src.services.debates.tags import detect_debate_tags


# =============================================================================
# Constants
# =============================================================================

UPVOTE_EMOJI = "\u2b06\ufe0f"  # ⬆️
DOWNVOTE_EMOJI = "\u2b07\ufe0f"  # ⬇️
PARTICIPATE_EMOJI = "✅"  # Checkmark for participation access control

DEBATE_COUNTER_FILE = Path("data/debate_counter.json")
DEBATE_MANAGEMENT_ROLE_ID = MODERATOR_ROLE_ID  # Debate Management role - can post without reacting


# =============================================================================
# Analytics Throttle Cache
# =============================================================================

class AnalyticsThrottleCache:
    """
    Thread-safe cache for throttling analytics updates.

    Prevents excessive updates to analytics embeds by tracking the last update
    time for each thread and enforcing a cooldown period.

    DESIGN: Encapsulates global state (_analytics_last_update, _analytics_lock)
    into a proper class with methods for checking/recording updates and cleanup.
    """

    def __init__(
        self,
        cooldown_seconds: int = ANALYTICS_UPDATE_COOLDOWN,
        max_size: int = ANALYTICS_CACHE_MAX_SIZE,
        cleanup_age_seconds: int = ANALYTICS_CACHE_CLEANUP_AGE,
    ) -> None:
        """
        Initialize the throttle cache.

        Args:
            cooldown_seconds: Minimum seconds between updates for same thread
            max_size: Maximum number of entries before cleanup
            cleanup_age_seconds: Remove entries older than this
        """
        self._last_update: Dict[int, datetime] = {}
        self._lock = asyncio.Lock()
        self._cooldown = cooldown_seconds
        self._max_size = max_size
        self._cleanup_age = cleanup_age_seconds

    async def should_update(self, thread_id: int) -> bool:
        """
        Check if enough time has passed since last update for this thread.

        Args:
            thread_id: The thread ID to check

        Returns:
            True if update is allowed, False if still in cooldown
        """
        async with self._lock:
            last_update = self._last_update.get(thread_id)
            if last_update is None:
                return True

            elapsed = (datetime.now() - last_update).total_seconds()
            if elapsed < self._cooldown:
                logger.debug("⏳ Throttled Analytics Update", [
                    ("Thread ID", str(thread_id)),
                    ("Elapsed", f"{elapsed:.0f}s"),
                    ("Cooldown", f"{self._cooldown}s"),
                ])
                return False
            return True

    async def record_update(self, thread_id: int) -> None:
        """
        Record that an analytics update was performed for this thread.

        Args:
            thread_id: The thread ID that was updated
        """
        async with self._lock:
            self._last_update[thread_id] = datetime.now()
            await self._cleanup_unlocked()

    async def _cleanup_unlocked(self) -> None:
        """
        Remove stale entries from cache. Must be called with lock held.
        Uses atomic dict replacement to avoid modification during iteration.
        """
        now = datetime.now()
        stale_threshold = now - timedelta(seconds=self._cleanup_age)

        # Build new dict with only fresh entries (atomic replacement)
        fresh_entries = {
            thread_id: last_update
            for thread_id, last_update in self._last_update.items()
            if last_update >= stale_threshold
        }

        removed_count = len(self._last_update) - len(fresh_entries)

        # If still over max, keep only the newest entries
        if len(fresh_entries) > self._max_size:
            sorted_entries = sorted(fresh_entries.items(), key=lambda x: x[1], reverse=True)
            extra_removed = len(fresh_entries) - self._max_size
            fresh_entries = dict(sorted_entries[:self._max_size])
            removed_count += extra_removed

        # Atomic replacement
        self._last_update = fresh_entries

        if removed_count > 0:
            logger.debug("🧹 Cleaned Analytics Cache", [
                ("Removed", str(removed_count)),
                ("Remaining", str(len(self._last_update))),
            ])

    @property
    def size(self) -> int:
        """Return current cache size (for monitoring)."""
        return len(self._last_update)


# Module-level instance (initialized once, used throughout)
_analytics_cache = AnalyticsThrottleCache()


def _is_bot_ready(bot: "OthmanBot") -> bool:
    """
    Check if the bot is fully ready to handle events.

    This prevents race conditions where events fire before on_ready() completes
    and services are initialized.

    Args:
        bot: The OthmanBot instance

    Returns:
        True if bot is ready and has debates_service initialized
    """
    if not bot.is_ready():
        return False
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return False
    return True


# =============================================================================
# Helper Functions
# =============================================================================

async def update_analytics_embed(bot: "OthmanBot", thread: discord.Thread, force: bool = False) -> None:
    """
    Update the analytics embed for a debate thread.

    Args:
        bot: The OthmanBot instance
        thread: The debate thread
        force: If True, bypass throttle and update immediately

    DESIGN: Updates analytics embed in-place without reposting
    Throttled to 30 seconds per thread to avoid rate limits
    Uses AnalyticsThrottleCache for thread-safe throttling
    """
    # Check if debates service is available
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return

    # Throttle check - skip if updated recently (unless forced)
    if not force and not await _analytics_cache.should_update(thread.id):
        return

    try:
        # Get analytics message ID from database
        analytics_message_id = bot.debates_service.db.get_analytics_message(thread.id)
        if not analytics_message_id:
            logger.debug("📊 No Analytics Message Found", [
                ("Thread ID", str(thread.id)),
            ])
            return

        # Fetch the analytics message using safe helper
        analytics_message = await safe_fetch_message(thread, analytics_message_id)
        if analytics_message is None:
            # Clear stale reference to prevent repeated warnings
            bot.debates_service.db.clear_analytics_message(thread.id)
            logger.info("📊 Cleared Stale Analytics Reference", [
                ("Message ID", str(analytics_message_id)),
                ("Thread ID", str(thread.id)),
            ])
            return

        # Calculate updated analytics
        analytics = await calculate_debate_analytics(thread, bot.debates_service.db)

        # Generate updated embed
        embed = await generate_analytics_embed(bot, analytics)

        # Edit the message with rate limit handling
        await edit_message_with_retry(analytics_message, embed=embed)

        # Record the update (handles cleanup internally)
        await _analytics_cache.record_update(thread.id)

        logger.debug("📊 Updated Analytics Embed", [
            ("Thread", thread.name[:50]),
        ])

    except discord.HTTPException as e:
        logger.warning("📊 Failed To Update Analytics Embed", [
            ("Error", str(e)),
        ])
    except (ValueError, KeyError, TypeError) as e:
        logger.error("📊 Data Error Updating Analytics Embed", [
            ("Error", str(e)),
        ])


def _get_next_debate_number_sync() -> int:
    """
    Synchronous helper for get_next_debate_number.
    Uses file locking to prevent race conditions when multiple threads
    are created simultaneously.
    """
    DEBATE_COUNTER_FILE.parent.mkdir(exist_ok=True)
    lock_file = DEBATE_COUNTER_FILE.with_suffix('.lock')

    try:
        # Use exclusive file lock to prevent race conditions
        with open(lock_file, 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                if DEBATE_COUNTER_FILE.exists():
                    with open(DEBATE_COUNTER_FILE, "r") as f:
                        data = json.load(f)
                        current = data.get("count", 0)
                else:
                    current = 0

                # Increment and save
                next_num = current + 1
                with open(DEBATE_COUNTER_FILE, "w") as f:
                    json.dump({"count": next_num}, f)

                return next_num
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except (json.JSONDecodeError, IOError, OSError) as e:
        logger.error("🔢 Failed To Get Debate Number - Using Fallback", [
            ("Error", str(e)),
            ("Fallback", "Returning timestamp-based number to avoid duplicates"),
        ])
        # Use timestamp-based fallback to avoid duplicate debate numbers
        import time
        return int(time.time()) % 100000  # Unique fallback number


async def get_next_debate_number() -> int:
    """Get and increment the debate counter (non-blocking)."""
    return await asyncio.to_thread(_get_next_debate_number_sync)


def is_debates_forum_message(channel) -> bool:
    """Check if channel is a thread in the debates forum."""
    if not isinstance(channel, discord.Thread):
        return False
    return channel.parent_id == DEBATES_FORUM_ID


def has_debate_management_role(member) -> bool:
    """Check if member has the Debate Management role."""
    if not hasattr(member, 'roles'):
        return False
    return any(role.id == DEBATE_MANAGEMENT_ROLE_ID for role in member.roles)


# =============================================================================
# Message Handler
# =============================================================================

async def on_message_handler(bot: "OthmanBot", message: discord.Message) -> None:
    """
    Event handler for messages in the debates forum.

    Args:
        bot: The OthmanBot instance
        message: The message that was sent

    DESIGN: Auto-react with upvote/downvote on substantive replies in debates forum
    Only reacts on replies that meet minimum character threshold
    Filters out spam and low-effort messages

    ALSO handles thread starter messages (first message in thread) for numbering

    ACCESS CONTROL: Checks if users have reacted with ✅ to the analytics embed before allowing them to post

    NOTE: When bot is disabled, still tracks participation for database accuracy,
    but skips all other actions (reactions, access control enforcement, analytics updates).
    """
    # Null safety checks for Discord API objects
    if message is None or message.author is None or message.channel is None:
        return

    # Wait for bot to be fully ready (prevents init race conditions)
    if not _is_bot_ready(bot):
        return

    # Ignore bot messages
    if message.author.bot:
        return

    # Check if message is in a thread
    if not isinstance(message.channel, discord.Thread):
        return

    # Check if the thread's parent is the debates forum
    if message.channel.parent_id != DEBATES_FORUM_ID:
        return

    # DESIGN: Skip thread starter messages - they are handled by on_thread_create_handler
    # For forum threads, the first message ID equals the thread ID
    is_thread_starter = (message.id == message.channel.id)
    if is_thread_starter:
        return  # Already processed by on_thread_create_handler

    # Check if bot is disabled - still track participation but skip everything else
    bot_disabled = getattr(bot, 'disabled', False)

    # Track participation for leaderboard ALWAYS (even when disabled)
    # This ensures database stays accurate
    if hasattr(bot, 'debates_service') and bot.debates_service is not None:
        try:
            await bot.debates_service.db.increment_participation_async(
                message.channel.id, message.author.id
            )
            # Also update daily streak
            await bot.debates_service.db.update_user_streak_async(message.author.id)
        except sqlite3.Error as e:
            logger.warning("📊 Failed To Track Participation (DB Error)", [
                ("Error", str(e)),
            ])
            # Log to webhook for visibility
            try:
                if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                    await bot.webhook_alerts.send_error_alert(
                        "Database Error - Participation Tracking",
                        f"User: {message.author.id}, Thread: {message.channel.id}, Error: {str(e)}"
                    )
            except Exception as webhook_err:
                logger.debug("Webhook alert failed", [("Error", str(webhook_err))])
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.warning("📊 Failed To Track Participation (Async Error)", [
                ("Error", str(e)),
            ])

    # If bot is disabled, skip all other actions (reactions, access control, analytics)
    if bot_disabled:
        return

    # DEBATE BAN CHECK: Check if user is banned from this thread or all debates
    if hasattr(bot, 'debates_service') and bot.debates_service is not None:
        is_banned = bot.debates_service.db.is_user_banned(message.author.id, message.channel.id)
        if is_banned:
            try:
                content_preview = message.content[:50] + "..." if len(message.content) > 50 else message.content
                await message.delete()
                logger.info("Banned User Message Deleted", [
                    ("User", f"{message.author.name} ({message.author.id})"),
                    ("Thread", f"{message.channel.name} ({message.channel.id})"),
                    ("Content Preview", content_preview),
                ])

                # Log to webhook
                if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                    await bot.interaction_logger.log_banned_user_message_deleted(
                        message.author, message.channel.name, content_preview
                    )

                # Send ephemeral-style DM to user with rate limit handling
                try:
                    await send_message_with_retry(
                        message.author,
                        content=(
                            f"🚫 You are banned from posting in this debate thread.\n"
                            f"Contact a moderator if you believe this is a mistake."
                        )
                    )
                except discord.Forbidden:
                    pass  # User has DMs disabled
            except discord.HTTPException as e:
                logger.warning("🚫 Failed To Delete Banned User Message", [
                    ("Error", str(e)),
                ])
            return

    # ACCESS CONTROL BYPASS: Skip for Debate Management role and developer
    is_debate_manager = has_debate_management_role(message.author)
    is_developer = message.author.id == DEVELOPER_ID
    skip_access_control = is_debate_manager or is_developer

    if skip_access_control:
        logger.info("Access Control Bypassed", [
            ("User", f"{message.author.name} ({message.author.id})"),
            ("Thread", f"{message.channel.name} ({message.channel.id})"),
            ("Is Manager", str(is_debate_manager)),
            ("Is Developer", str(is_developer)),
        ])

    # ACCESS CONTROL: Check if user has reacted to the analytics embed
    if not skip_access_control and hasattr(bot, 'debates_service') and bot.debates_service is not None:
        try:
            # Get analytics message ID from database
            analytics_message_id = bot.debates_service.db.get_analytics_message(message.channel.id)

            if analytics_message_id:
                # Fetch the analytics message
                try:
                    analytics_message = await message.channel.fetch_message(analytics_message_id)

                    # Check if the user has reacted with ✅
                    user_has_reacted = False
                    for reaction in analytics_message.reactions:
                        if str(reaction.emoji) == PARTICIPATE_EMOJI:
                            # Check if the current user is in the list of users who reacted
                            async for user in reaction.users():
                                if user.id == message.author.id:
                                    user_has_reacted = True
                                    break
                            break

                    # If user hasn't reacted, send DM and delete their message
                    if not user_has_reacted:
                        try:
                            # Delete the user's message first
                            await message.delete()

                            # Try to send a DM to the user with rate limit handling
                            try:
                                await send_message_with_retry(
                                    message.author,
                                    content=(
                                        f"Hi {message.author.name},\n\n"
                                        f"To participate in the debate **{message.channel.name}**, you need to react with ✅ to the analytics embed first.\n\n"
                                        f"Please go back to the thread and react with ✅ to the analytics message to unlock posting access."
                                    )
                                )
                                logger.info("User Blocked - No Participation React", [
                                    ("User", f"{message.author.name} ({message.author.id})"),
                                    ("Thread", f"{message.channel.name} ({message.channel.id})"),
                                    ("Action", "DM sent with instructions"),
                                ])

                                # Log to webhook
                                if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                                    await bot.interaction_logger.log_access_blocked(
                                        message.author, message.channel.name, "No participation react"
                                    )
                            except discord.Forbidden:
                                # User has DMs disabled, send a temporary message in the channel
                                await send_message_with_retry(
                                    message.channel,
                                    content=f"{message.author.mention} You need to react with ✅ to the analytics embed above to participate in this debate.",
                                    delete_after=8
                                )
                                logger.info("User Blocked - No Participation React", [
                                    ("User", f"{message.author.name} ({message.author.id})"),
                                    ("Thread", f"{message.channel.name} ({message.channel.id})"),
                                    ("Action", "Channel message sent (DMs disabled)"),
                                ])

                                # Log to webhook
                                if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                                    await bot.interaction_logger.log_access_blocked(
                                        message.author, message.channel.name, "No participation react (DMs disabled)"
                                    )
                        except discord.HTTPException as e:
                            logger.warning("🔐 Failed To Enforce Access Control", [
                                ("Error", str(e)),
                            ])
                        return

                except discord.NotFound:
                    # Clear stale reference to prevent repeated warnings
                    bot.debates_service.db.clear_analytics_message(message.channel.id)
                    logger.info("🔐 Cleared Stale Analytics Reference (Access Control)", [
                        ("Message ID", str(analytics_message_id)),
                        ("Thread ID", str(message.channel.id)),
                    ])
                except discord.Forbidden:
                    logger.warning("🔐 No Permission to Fetch Analytics Message", [
                        ("Message ID", str(analytics_message_id)),
                        ("Thread ID", str(message.channel.id)),
                    ])
                except discord.HTTPException as e:
                    logger.warning("🔐 Failed to Fetch Analytics Message", [
                        ("Message ID", str(analytics_message_id)),
                        ("Error", str(e)),
                    ])
        except discord.HTTPException as e:
            logger.warning("🔐 Access Control HTTP Error", [
                ("Error", str(e)),
            ])
        except (ValueError, AttributeError) as e:
            logger.error("🔐 Error Checking Access Control", [
                ("Error", str(e)),
            ])

    # For regular replies - only add vote reactions for long messages
    # Use language-aware minimum: 400 chars for Arabic, 200 chars for English/other
    min_length = get_min_message_length(message.content)
    if len(message.content) >= min_length:
        # Add upvote and downvote reactions with rate limit handling
        try:
            await add_reactions_with_delay(message, [UPVOTE_EMOJI, DOWNVOTE_EMOJI])
            logger.info("Vote Reactions Added to Reply", [
                ("User", f"{message.author.name} ({message.author.id})"),
                ("Thread", f"{message.channel.name} ({message.channel.id})"),
                ("Message ID", str(message.id)),
                ("Content Length", f"{len(message.content)} chars"),
            ])

            # Log to webhook
            if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                await bot.interaction_logger.log_vote_reactions_added(
                    message.author, message.channel.name, message.id, len(message.content)
                )
        except discord.HTTPException as e:
            logger.warning("🗳️ Failed To Add Vote Reactions", [
                ("Error", str(e)),
            ])
    else:
        logger.debug("⏭️ Skipped Reactions For Short Message", [
            ("User", message.author.name),
            ("Length", f"{len(message.content)} chars"),
            ("Min Required", f"{min_length} chars"),
        ])

    # ALWAYS update analytics embed after any valid message
    await update_analytics_embed(bot, message.channel)


# =============================================================================
# Thread Create Handler
# =============================================================================

async def on_thread_create_handler(bot: "OthmanBot", thread: discord.Thread) -> None:
    """
    Event handler for new thread creation in debates forum.

    Args:
        bot: The OthmanBot instance
        thread: The thread that was created

    DESIGN: Auto-number debates, add reactions to original post, and post analytics embed
    Renames thread to "N | Original Title" format
    Posts analytics embed with debate rules and ✅ reaction for participation access
    """
    # Null safety checks for Discord API objects
    if thread is None:
        return

    # Wait for bot to be fully ready (prevents init race conditions)
    if not _is_bot_ready(bot):
        return

    # Check if it's in debates forum (with null check for parent_id)
    if thread.parent_id is None or thread.parent_id != DEBATES_FORUM_ID:
        return

    # Get the starter message
    try:
        # DESIGN: For forum threads, the starter message might not be immediately available
        # Try multiple methods to retrieve it with a small delay
        starter_message = thread.starter_message

        # If not available, wait a moment and try fetching from thread
        if starter_message is None:
            await asyncio.sleep(DISCORD_API_DELAY)  # Small delay to let Discord populate the message

            # Try to fetch the starter message from the thread itself
            # For forum threads, the thread ID is also the starter message ID
            try:
                starter_message = await thread.fetch_message(thread.id)
            except discord.NotFound:
                pass

        # Last resort: try thread history
        if starter_message is None:
            async for message in thread.history(limit=1, oldest_first=True):
                starter_message = message
                break

        if starter_message is None:
            logger.warning("🔍 Could Not Find Starter Message For Debate Thread")
            return

        # Skip if it's a bot message
        if starter_message.author.bot:
            return

        # Add upvote and downvote reactions to the original post (always, regardless of language)
        # Use rate-limited helper to prevent 429 errors
        try:
            await add_reactions_with_delay(starter_message, [UPVOTE_EMOJI, DOWNVOTE_EMOJI])
            logger.info("Vote Reactions Added to Debate Post", [
                ("Author", f"{starter_message.author.name} ({starter_message.author.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
                ("Content Length", f"{len(starter_message.content)} chars"),
            ])
        except discord.HTTPException as e:
            logger.warning("🗳️ Failed To Add Vote Reactions To Debate Post", [
                ("Error", str(e)),
            ])

        # VALIDATION: Check if title is English-only
        original_title = thread.name
        if not is_english_only(original_title):
            logger.warning("Non-English Debate Title Detected", [
                ("Author", f"{starter_message.author.name} ({starter_message.author.id})"),
                ("Title", original_title),
                ("Thread ID", str(thread.id)),
            ])

            try:
                # Import translation utility
                from src.utils.translate import translate_to_english

                # Get AI translation suggestion
                suggested_title = translate_to_english(original_title)
                logger.info("AI Translation Suggested", [
                    ("Original", original_title),
                    ("Suggested", suggested_title),
                ])

                # Lock and archive the thread with rate limit handling
                await edit_thread_with_retry(thread, locked=True, archived=True)
                logger.info("Thread Locked for Non-English Title", [
                    ("Thread", f"{original_title} ({thread.id})"),
                    ("Author", f"{starter_message.author.name} ({starter_message.author.id})"),
                    ("Action", "Locked and archived"),
                ])

                # Post moderation message in the thread
                moderation_message = (
                    f"<@&{MODERATOR_ROLE_ID}>\n\n"
                    f"⚠️ **Non-English Title Detected**\n\n"
                    f"This debate thread has been locked because the title contains non-English characters.\n\n"
                    f"**Original Title:** {original_title}\n"
                    f"**Suggested Title:** {suggested_title}\n\n"
                    f"**📌 Moderators:** Please rename this thread to an appropriate English title and unlock it."
                )

                await send_message_with_retry(thread, content=moderation_message)
                logger.info("Moderation Message Posted", [
                    ("Thread", f"{original_title} ({thread.id})"),
                    ("Reason", "Non-English title"),
                ])

                # Log to webhook
                if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                    await bot.interaction_logger.log_non_english_title_blocked(
                        starter_message.author, original_title, suggested_title, thread.id
                    )

            except discord.HTTPException as e:
                logger.error("🌐 Failed To Handle Non-English Title (Discord Error)", [
                    ("Error", str(e)),
                ])
            except (ValueError, AttributeError) as e:
                logger.error("🌐 Failed To Handle Non-English Title (Data Error)", [
                    ("Error", str(e)),
                ])

            return

        # Get next debate number and rename thread
        debate_number = await get_next_debate_number()

        # Only add number if not already numbered
        if not original_title.split("|")[0].strip().isdigit():
            new_title = f"{debate_number} | {original_title}"
            # Truncate to Discord's 100 character limit
            if len(new_title) > 100:
                new_title = new_title[:97] + "..."
            # Use rate limit wrapper for thread edit
            success = await edit_thread_with_retry(thread, name=new_title)
            if success:
                logger.success("New Debate Thread Created", [
                    ("Number", f"#{debate_number}"),
                    ("Author", f"{starter_message.author.name} ({starter_message.author.id})"),
                    ("Title", new_title),
                    ("Thread ID", str(thread.id)),
                ])
            else:
                logger.warning("🔢 Failed To Rename Debate Thread", [
                    ("Thread ID", str(thread.id)),
                ])


        # AUTO-TAG: Detect and apply AI-powered tags
        try:
            # Get thread title and description (first message content)
            thread_title = original_title  # Use original title before numbering
            thread_description = starter_message.content if starter_message.content else ""

            # Detect tags using AI
            tag_ids = await detect_debate_tags(thread_title, thread_description)

            if tag_ids:
                # Get the thread object (we need to edit it to apply tags)
                # Convert tag IDs to ForumTag objects
                parent_forum = bot.get_channel(DEBATES_FORUM_ID)
                if parent_forum and hasattr(parent_forum, 'available_tags'):
                    # Get the available tags from the forum
                    available_tags = {tag.id: tag for tag in parent_forum.available_tags}

                    # Build list of tags to apply
                    tags_to_apply = []
                    for tag_id in tag_ids:
                        if tag_id in available_tags:
                            tags_to_apply.append(available_tags[tag_id])

                    if tags_to_apply:
                        # Apply tags to the thread with rate limit handling
                        success = await edit_thread_with_retry(thread, applied_tags=tags_to_apply)
                        if success:
                            tag_names = [tag.name for tag in tags_to_apply]
                            logger.info("Auto-Tags Applied to Debate", [
                                ("Debate", f"#{debate_number}"),
                                ("Thread ID", str(thread.id)),
                                ("Tags", ", ".join(tag_names)),
                            ])
        except discord.HTTPException as e:
            logger.warning("🏷️ Failed To Auto-Tag Debate Thread (Discord Error)", [
                ("Error", str(e)),
            ])
        except (ValueError, KeyError, AttributeError) as e:
            logger.error("🏷️ Failed To Auto-Tag Debate Thread (Data Error)", [
                ("Error", str(e)),
            ])

        # Post analytics embed
        if hasattr(bot, 'debates_service') and bot.debates_service is not None:
            try:
                # Calculate initial analytics
                analytics = await calculate_debate_analytics(thread, bot.debates_service.db)

                # Generate and send analytics embed with rate limit handling
                embed = await generate_analytics_embed(bot, analytics)
                analytics_message = await send_message_with_retry(thread, embed=embed)

                if not analytics_message:
                    logger.warning("📊 Failed to send analytics embed")
                    return

                # Add participation reaction for access control (with rate limit handling)
                await add_reactions_with_delay(analytics_message, [PARTICIPATE_EMOJI])

                # Pin the analytics message
                try:
                    await analytics_message.pin()

                    # Delete the "pinned a message" system message using safe delete
                    await asyncio.sleep(DISCORD_API_DELAY)  # Wait for Discord to create the system message
                    async for msg in thread.history(limit=5):
                        if msg.type == discord.MessageType.pins_add:
                            await delete_message_safe(msg)
                            logger.debug("🗑️ Deleted 'pinned a message' system message")
                            break
                except discord.HTTPException as e:
                    logger.warning("📊 Failed to pin analytics message", [
                        ("Thread", str(thread.id)),
                        ("Error", str(e)),
                    ])

                # Store analytics message ID in database
                bot.debates_service.db.set_analytics_message(thread.id, analytics_message.id)

                # Track debate creator for leaderboard
                try:
                    await bot.debates_service.db.set_debate_creator_async(
                        thread.id, starter_message.author.id
                    )
                except sqlite3.Error as e:
                    logger.warning("📊 Failed To Track Debate Creator (DB Error)", [
                        ("Error", str(e)),
                    ])
                    # Log to webhook for visibility
                    try:
                        if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                            await bot.webhook_alerts.send_error_alert(
                                "Database Error - Debate Creator Tracking",
                                f"Thread: {thread.id}, Creator: {starter_message.author.id}, Error: {str(e)}"
                            )
                    except Exception as webhook_err:
                        logger.debug("Webhook alert failed", [("Error", str(webhook_err))])
                except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                    logger.warning("📊 Failed To Track Debate Creator (Async Error)", [
                        ("Error", str(e)),
                    ])

                logger.info("Analytics Embed Posted", [
                    ("Debate", f"#{debate_number}"),
                    ("Thread ID", str(thread.id)),
                    ("Message ID", str(analytics_message.id)),
                    ("Pinned", "Yes"),
                ])

                # Log debate creation to webhook
                if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                    await bot.interaction_logger.log_debate_created(
                        thread, starter_message.author, debate_number, original_title
                    )

                # Track stats
                if hasattr(bot, 'daily_stats') and bot.daily_stats:
                    bot.daily_stats.record_debate_created(
                        thread.id, original_title, starter_message.author.id, starter_message.author.name
                    )
            except discord.HTTPException as e:
                logger.warning("📊 Failed To Post Analytics Embed For Debate Thread", [
                    ("Error", str(e)),
                ])
            except (ValueError, KeyError) as e:
                logger.error("📊 Analytics Embed Data Error", [
                    ("Error", str(e)),
                ])

    except discord.HTTPException as e:
        logger.warning("🧵 Failed To Process Debate Thread Creation", [
            ("Error", str(e)),
        ])


# =============================================================================
# Reaction Handlers
# =============================================================================

async def on_debate_reaction_add(
    bot: "OthmanBot",
    reaction: discord.Reaction,
    user: discord.User
) -> None:
    """
    Track upvotes/downvotes when reactions are added.

    Args:
        bot: The OthmanBot instance
        reaction: The reaction that was added
        user: The user who added the reaction
    """
    # Wait for bot to be fully ready (prevents init race conditions)
    if not _is_bot_ready(bot):
        return

    # Ignore bot reactions
    if user.bot:
        return

    # Check if it's in debates forum
    if not is_debates_forum_message(reaction.message.channel):
        return

    # Check if it's an upvote or downvote
    emoji = str(reaction.emoji)
    if emoji not in (UPVOTE_EMOJI, DOWNVOTE_EMOJI):
        return

    # Get debates service
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return

    message = reaction.message
    author_id = message.author.id
    voter_id = user.id

    # Prevent self-voting
    if voter_id == author_id:
        try:
            await reaction.remove(user)
            vote_type = "Upvote" if emoji == UPVOTE_EMOJI else "Downvote"
            logger.info("Self-Vote Prevented", [
                ("User", f"{user.name} ({user.id})"),
                ("Thread", f"{message.channel.name} ({message.channel.id})"),
                ("Message ID", str(message.id)),
            ])

            # Log to webhook
            if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                await bot.interaction_logger.log_self_vote_blocked(
                    user, message.channel.name, vote_type
                )
        except discord.HTTPException as e:
            logger.warning("🗳️ Failed To Remove Self-Vote Reaction", [
                ("Error", str(e)),
            ])
        return

    # Record the vote with error handling
    vote_type = "Upvote" if emoji == UPVOTE_EMOJI else "Downvote"
    try:
        if emoji == UPVOTE_EMOJI:
            success = await bot.debates_service.record_upvote_async(voter_id, message.id, author_id)
        else:
            success = await bot.debates_service.record_downvote_async(voter_id, message.id, author_id)

        if not success:
            logger.warning("Vote Recording Failed (No Change)", [
                ("Voter", str(voter_id)),
                ("Message", str(message.id)),
                ("Type", vote_type),
            ])
            # Remove the reaction to signal the vote didn't count
            try:
                await reaction.remove(user)
            except discord.HTTPException:
                pass
            return
    except Exception as e:
        logger.error("Vote Recording Exception", [
            ("Voter", str(voter_id)),
            ("Message", str(message.id)),
            ("Type", vote_type),
            ("Error", str(e)),
        ])
        # Remove the reaction to signal the vote didn't count
        try:
            await reaction.remove(user)
        except discord.HTTPException:
            pass
        return

    logger.info("Vote Recorded", [
        ("Voter", f"{user.name} ({user.id})"),
        ("Author", f"{message.author.name} ({author_id})"),
        ("Type", vote_type),
        ("Thread", f"{message.channel.name} ({message.channel.id})"),
        ("Message ID", str(message.id)),
    ])

    # Get updated karma for logging
    karma_data = bot.debates_service.get_karma(author_id)
    change = 1 if emoji == UPVOTE_EMOJI else -1

    # Log karma change to webhook
    if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
        await bot.interaction_logger.log_karma_change(
            message.author, user, change, karma_data.total_karma, message.channel.name
        )

    # Track stats
    if hasattr(bot, 'daily_stats') and bot.daily_stats:
        bot.daily_stats.record_karma_vote(
            author_id, message.author.name, emoji == UPVOTE_EMOJI
        )

    # Update analytics embed
    await update_analytics_embed(bot, reaction.message.channel)


async def on_debate_reaction_remove(
    bot: "OthmanBot",
    reaction: discord.Reaction,
    user: discord.User
) -> None:
    """
    Remove vote when reaction is removed.

    Args:
        bot: The OthmanBot instance
        reaction: The reaction that was removed
        user: The user who removed the reaction
    """
    # Wait for bot to be fully ready (prevents init race conditions)
    if not _is_bot_ready(bot):
        return

    # Ignore bot reactions
    if user.bot:
        return

    # Check if it's in debates forum
    if not is_debates_forum_message(reaction.message.channel):
        return

    # Check if it's an upvote or downvote
    emoji = str(reaction.emoji)
    if emoji not in (UPVOTE_EMOJI, DOWNVOTE_EMOJI):
        return

    # Get debates service
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return

    # Remove the vote and check if it existed
    vote_type = "Upvote" if emoji == UPVOTE_EMOJI else "Downvote"
    removed = bot.debates_service.remove_vote(user.id, reaction.message.id)

    if not removed:
        # Vote wasn't in database (already removed or never recorded)
        logger.debug("Vote Already Removed Or Not Found", [
            ("Voter", f"{user.name} ({user.id})"),
            ("Message", str(reaction.message.id)),
            ("Type", vote_type),
        ])
        return

    logger.info("Vote Removed", [
        ("Voter", f"{user.name} ({user.id})"),
        ("Author", f"{reaction.message.author.name} ({reaction.message.author.id})"),
        ("Type", vote_type),
        ("Thread", f"{reaction.message.channel.name} ({reaction.message.channel.id})"),
        ("Message ID", str(reaction.message.id)),
    ])

    # Log to webhook - vote removal (negative karma change)
    try:
        if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
            karma_data = bot.debates_service.get_karma(reaction.message.author.id)
            # Vote removal = negative change (removing upvote = -1, removing downvote = +1)
            change = -1 if emoji == UPVOTE_EMOJI else 1
            await bot.interaction_logger.log_karma_change(
                reaction.message.author, user, change,
                karma_data.total_karma, reaction.message.channel.name
            )
    except Exception as e:
        logger.warning("Failed to log vote removal to webhook", [
            ("Error", str(e)),
        ])

    # Update analytics embed
    await update_analytics_embed(bot, reaction.message.channel)


# =============================================================================
# Member Leave Handler
# =============================================================================

async def on_member_remove_handler(bot: "OthmanBot", member: discord.Member) -> None:
    """
    Event handler for member leaving the server.

    Args:
        bot: The OthmanBot instance
        member: The member who left

    DESIGN: When a user leaves:
    1. Delete all debate threads they created
    2. Delete all their messages/replies in other debate threads
    3. Reset their karma to 0 and remove all their data from database
    """
    # Get the debates forum
    debates_forum = bot.get_channel(DEBATES_FORUM_ID)
    if not debates_forum or not isinstance(debates_forum, discord.ForumChannel):
        logger.warning("Debates forum not available for cleanup", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
            ("Type", type(debates_forum).__name__ if debates_forum else "None"),
        ])
        return

    deleted_threads = 0
    deleted_messages = 0
    reactions_removed = 0
    deleted_data: dict = {}  # Initialize before try block for safe access later

    try:
        # Collect all threads (active + archived) to process with timeout
        all_threads = list(debates_forum.threads)
        try:
            async with asyncio.timeout(30.0):  # 30s timeout for fetching archived threads
                async for archived_thread in debates_forum.archived_threads(limit=100):
                    all_threads.append(archived_thread)
        except asyncio.TimeoutError:
            logger.warning("👋 Timeout Fetching Archived Threads For Member Cleanup", [
                ("User", member.name),
                ("Threads Collected", str(len(all_threads))),
            ])

        # First, remove user's reactions from all thread starter messages
        for thread in all_threads:
            try:
                starter_message = thread.starter_message
                if not starter_message:
                    starter_message = await thread.fetch_message(thread.id)

                if starter_message:
                    for reaction in starter_message.reactions:
                        # Use safe remove with delay between reactions
                        success = await remove_reaction_safe(reaction, member)
                        if success:
                            reactions_removed += 1
                        await asyncio.sleep(REACTION_DELAY)  # Rate limit delay between reaction removals
            except discord.HTTPException:
                pass
            await asyncio.sleep(DISCORD_API_DELAY)  # Delay between threads

        for thread in all_threads:
            # If user owns the thread, delete the entire thread
            if thread.owner_id == member.id:
                try:
                    await thread.delete()
                    deleted_threads += 1
                    logger.info("Debate Thread Deleted - User Left", [
                        ("User", f"{member.name} ({member.id})"),
                        ("Thread", f"{thread.name} ({thread.id})"),
                    ])
                except discord.HTTPException as e:
                    logger.warning("🗑️ Failed To Delete Thread", [
                        ("Thread", thread.name),
                        ("Error", str(e)),
                    ])
            else:
                # Delete all messages by this user in threads they don't own
                try:
                    async for message in thread.history(limit=500):
                        if message.author.id == member.id:
                            # Use safe delete with delay between deletes
                            success = await delete_message_safe(message)
                            if success:
                                deleted_messages += 1
                            await asyncio.sleep(DISCORD_API_DELAY)  # Rate limit delay between message deletes
                except discord.HTTPException as e:
                    logger.warning("🔍 Failed To Scan Thread For Messages", [
                        ("Thread", thread.name),
                        ("Error", str(e)),
                    ])

        # Reset karma and delete all database records for this user
        if hasattr(bot, 'debates_service') and bot.debates_service is not None:
            try:
                deleted_data = bot.debates_service.db.delete_user_data(member.id)
                logger.info("User Database Records Deleted", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Karma", str(deleted_data.get('karma', 0))),
                    ("Votes Cast", str(deleted_data.get('votes_cast', 0))),
                    ("Votes Received", str(deleted_data.get('votes_received', 0))),
                    ("Bans", str(deleted_data.get('bans', 0))),
                ])
            except (sqlite3.Error, AttributeError) as e:
                logger.error("🗄️ Failed To Delete Database Records", [
                    ("User", member.name),
                    ("Error", str(e)),
                ])

        # Update leaderboard to mark user as left
        if hasattr(bot, 'leaderboard_manager') and bot.leaderboard_manager is not None:
            try:
                await bot.leaderboard_manager.on_member_leave(member.id)
            except (discord.HTTPException, AttributeError) as e:
                logger.error("📊 Failed To Update Leaderboard For Leaving Member", [
                    ("User", member.name),
                    ("Error", str(e)),
                ])

        # Log summary
        if deleted_threads > 0 or deleted_messages > 0 or reactions_removed > 0:
            logger.success("Member Leave Cleanup Complete", [
                ("User", f"{member.name} ({member.id})"),
                ("Threads Deleted", str(deleted_threads)),
                ("Messages Deleted", str(deleted_messages)),
                ("Reactions Removed", str(reactions_removed)),
            ])

            # Log to webhook
            if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
                karma_reset = deleted_data.get('karma', 0)
                await bot.interaction_logger.log_member_leave_cleanup(
                    member.name, member.id, deleted_threads, deleted_messages, reactions_removed, karma_reset
                )

    except discord.HTTPException as e:
        logger.error("👋 Discord Error Cleaning Up Debate Data", [
            ("User", member.name),
            ("Error", str(e)),
        ])


# =============================================================================
# Member Join Handler
# =============================================================================

async def on_member_join_handler(bot: "OthmanBot", member: discord.Member) -> None:
    """
    Event handler for member joining the server.

    Args:
        bot: The OthmanBot instance
        member: The member who joined

    DESIGN: When a user joins/rejoins:
    1. If they were previously cached, update leaderboard to remove "(left)" suffix
    """
    # Update leaderboard to mark user as rejoined (if they were previously cached)
    if hasattr(bot, 'leaderboard_manager') and bot.leaderboard_manager is not None:
        try:
            await bot.leaderboard_manager.on_member_join(
                member.id,
                member.name,
                member.display_name
            )
        except (discord.HTTPException, AttributeError) as e:
            logger.error("📊 Failed To Update Leaderboard For Rejoining Member", [
                ("User", member.name),
                ("Error", str(e)),
            ])

    # Log to webhook
    if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
        await bot.interaction_logger.log_member_rejoin(member)


# =============================================================================
# Thread Delete Handler - Auto Renumbering
# =============================================================================

def _extract_debate_number(thread_name: str) -> Optional[int]:
    """
    Extract debate number from thread name.

    Args:
        thread_name: Thread name in format "N | Title"

    Returns:
        Debate number or None if not numbered
    """
    parts = thread_name.split("|", 1)
    if len(parts) >= 1:
        try:
            return int(parts[0].strip())
        except ValueError:
            return None
    return None


async def _renumber_debates_after_deletion(bot: "OthmanBot", deleted_number: int) -> int:
    """
    Renumber all debates with numbers higher than the deleted one.

    When debate #5 is deleted, debates 6, 7, 8... become 5, 6, 7...

    Args:
        bot: The OthmanBot instance
        deleted_number: The debate number that was deleted

    Returns:
        Number of threads renumbered
    """
    debates_forum = bot.get_channel(DEBATES_FORUM_ID)
    if not debates_forum or not isinstance(debates_forum, discord.ForumChannel):
        logger.warning("Debates forum not available for renumbering", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
            ("Type", type(debates_forum).__name__ if debates_forum else "None"),
        ])
        return 0

    renumbered_count = 0
    threads_to_renumber = []

    try:
        # Collect all threads (active + archived)
        all_threads = list(debates_forum.threads)
        async for archived_thread in debates_forum.archived_threads(limit=100):
            all_threads.append(archived_thread)

        # Find threads with numbers higher than deleted
        for thread in all_threads:
            thread_number = _extract_debate_number(thread.name)
            if thread_number is not None and thread_number > deleted_number:
                threads_to_renumber.append((thread, thread_number))

        # Sort by number (ascending) to rename in order
        threads_to_renumber.sort(key=lambda x: x[1])

        # Track successfully renamed threads
        successfully_renamed = set()

        # Rename each thread
        for thread, old_number in threads_to_renumber:
            new_number = old_number - 1
            # Extract the title part after the number
            parts = thread.name.split("|", 1)
            if len(parts) == 2:
                title_part = parts[1].strip()
                new_name = f"{new_number} | {title_part}"
            else:
                # Fallback: just replace the number
                new_name = thread.name.replace(str(old_number), str(new_number), 1)

            try:
                await edit_thread_with_retry(thread, name=new_name)
                renumbered_count += 1
                successfully_renamed.add(thread.id)  # Track success
                logger.info("🔢 Debate Renumbered", [
                    ("Old Number", f"#{old_number}"),
                    ("New Number", f"#{new_number}"),
                    ("Thread", title_part if len(parts) == 2 else thread.name),
                    ("Thread ID", str(thread.id)),
                ])
                await asyncio.sleep(DISCORD_API_DELAY)  # Rate limit protection
            except discord.HTTPException as e:
                logger.warning("🔢 Failed To Renumber Debate", [
                    ("Thread", thread.name),
                    ("Error", str(e)),
                ])

        # Update the debate counter to reflect the new highest number
        # Recalculate based on ACTUAL final state, not assumed success
        if threads_to_renumber:
            # Build lookup dict only for SUCCESSFULLY renamed threads
            renumbered_ids = {
                t[0].id: t[1] for t in threads_to_renumber
                if t[0].id in successfully_renamed
            }

            # Find the actual highest number now
            max_number = 0
            for thread in all_threads:
                if thread.id in renumbered_ids:
                    # This thread was successfully renumbered - use old number - 1
                    max_number = max(max_number, renumbered_ids[thread.id] - 1)
                else:
                    # Thread wasn't renamed or rename failed - use current number
                    num = _extract_debate_number(thread.name)
                    if num is not None:
                        max_number = max(max_number, num)

            # Update the counter file with file locking to prevent race conditions
            lock_file = DEBATE_COUNTER_FILE.with_suffix('.lock')
            try:
                with open(lock_file, 'w') as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        with open(DEBATE_COUNTER_FILE, "w") as f:
                            json.dump({"count": max_number}, f)
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                logger.info("🔢 Debate Counter Updated", [
                    ("New Count", str(max_number)),
                    ("Renamed", str(len(successfully_renamed))),
                    ("Failed", str(len(threads_to_renumber) - len(successfully_renamed))),
                ])
            except (IOError, OSError) as e:
                logger.warning("🔢 Failed To Update Debate Counter", [
                    ("Error", str(e)),
                ])

    except discord.HTTPException as e:
        logger.error("🔢 Discord Error During Renumbering", [
            ("Error", str(e)),
        ])

    return renumbered_count


async def on_thread_delete_handler(bot: "OthmanBot", thread: discord.Thread) -> None:
    """
    Event handler for thread deletion in debates forum.

    Args:
        bot: The OthmanBot instance
        thread: The thread that was deleted

    DESIGN: When a debate thread is deleted:
    1. Extract the deleted debate's number
    2. Renumber all debates with higher numbers to fill the gap
    3. Update the debate counter

    Example: If #5 is deleted, #6 becomes #5, #7 becomes #6, etc.
    """
    # Check if it was in debates forum
    if thread.parent_id != DEBATES_FORUM_ID:
        return

    # Extract the debate number from the deleted thread
    deleted_number = _extract_debate_number(thread.name)

    if deleted_number is None:
        logger.debug("🗑️ Non-Numbered Debate Thread Deleted", [
            ("Thread", thread.name),
            ("Thread ID", str(thread.id)),
        ])
        return

    logger.info("🗑️ Debate Thread Deleted", [
        ("Number", f"#{deleted_number}"),
        ("Thread", thread.name),
        ("Thread ID", str(thread.id)),
    ])

    # Log deletion to webhook
    if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
        await bot.interaction_logger.log_debate_deleted(
            thread.id, thread.name
        )

    # Clean up database records for this thread
    if hasattr(bot, 'debates_service') and bot.debates_service is not None:
        try:
            bot.debates_service.db.delete_thread_data(thread.id)
            logger.debug("🗄️ Thread Database Records Cleaned", [
                ("Thread ID", str(thread.id)),
            ])
        except sqlite3.Error as e:
            logger.warning("🗄️ Failed To Clean Thread Database", [
                ("Error", str(e)),
            ])

    # Renumber remaining debates
    renumbered = await _renumber_debates_after_deletion(bot, deleted_number)

    if renumbered > 0:
        logger.success("🔢 Debate Renumbering Complete", [
            ("Deleted", f"#{deleted_number}"),
            ("Renumbered", str(renumbered)),
        ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "on_message_handler",
    "on_thread_create_handler",
    "on_debate_reaction_add",
    "on_debate_reaction_remove",
    "on_member_remove_handler",
    "on_member_join_handler",
    "on_thread_delete_handler",
]
