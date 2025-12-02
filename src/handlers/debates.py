"""
Othman Discord Bot - Debates Handler
=====================================

Auto-react with upvote/downvote on forum thread replies and track karma.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict
import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, MODERATOR_ROLE_ID, DEVELOPER_ID
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
MIN_MESSAGE_LENGTH = 200  # Minimum characters for Latin/English replies
MIN_MESSAGE_LENGTH_ARABIC = 400  # Minimum characters for Arabic replies (Arabic has denser words)


def _is_primarily_arabic(text: str) -> bool:
    """Check if text is primarily Arabic (>50% Arabic characters)."""
    if not text:
        return False
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F')
    # Count only letters (not spaces/punctuation)
    letter_chars = sum(1 for c in text if c.isalpha())
    if letter_chars == 0:
        return False
    return arabic_chars / letter_chars > 0.5


def _get_min_message_length(text: str) -> int:
    """Get minimum message length based on language."""
    return MIN_MESSAGE_LENGTH_ARABIC if _is_primarily_arabic(text) else MIN_MESSAGE_LENGTH
DEBATE_COUNTER_FILE = Path("data/debate_counter.json")
DEBATE_MANAGEMENT_ROLE_ID = MODERATOR_ROLE_ID  # Debate Management role - can post without reacting
ANALYTICS_UPDATE_COOLDOWN = 30  # Seconds between analytics updates per thread

# In-memory cache for analytics update throttling
_analytics_last_update: Dict[int, datetime] = {}  # thread_id -> last_update_time


# =============================================================================
# Helper Functions
# =============================================================================

async def update_analytics_embed(bot, thread: discord.Thread, force: bool = False) -> None:
    """
    Update the analytics embed for a debate thread.

    Args:
        bot: The OthmanBot instance
        thread: The debate thread
        force: If True, bypass throttle and update immediately

    DESIGN: Updates analytics embed in-place without reposting
    Throttled to 30 seconds per thread to avoid rate limits
    """
    # Check if debates service is available
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return

    # Throttle check - skip if updated recently (unless forced)
    if not force:
        last_update = _analytics_last_update.get(thread.id)
        if last_update:
            elapsed = (datetime.now() - last_update).total_seconds()
            if elapsed < ANALYTICS_UPDATE_COOLDOWN:
                logger.debug(f"⏳ Throttled analytics update for thread {thread.id} ({elapsed:.0f}s < {ANALYTICS_UPDATE_COOLDOWN}s)")
                return

    try:
        # Get analytics message ID from database
        analytics_message_id = bot.debates_service.db.get_analytics_message(thread.id)
        if not analytics_message_id:
            logger.debug(f"No analytics message found for thread {thread.id}")
            return

        # Fetch the analytics message
        try:
            analytics_message = await thread.fetch_message(analytics_message_id)
        except discord.NotFound:
            logger.warning(f"Analytics message {analytics_message_id} not found in thread {thread.id}")
            return

        # Calculate updated analytics
        analytics = await calculate_debate_analytics(thread, bot.debates_service.db)

        # Get hostility score if tracker is available
        if hasattr(bot, 'hostility_tracker') and bot.hostility_tracker is not None:
            analytics.hostility_score = bot.hostility_tracker.get_thread_score(thread.id)

        # Generate updated embed
        embed = await generate_analytics_embed(bot, analytics)

        # Edit the message
        await analytics_message.edit(embed=embed)

        # Update throttle timestamp
        _analytics_last_update[thread.id] = datetime.now()

        logger.debug(f"📊 Updated analytics embed for debate thread {thread.name}")

    except discord.HTTPException as e:
        logger.warning(f"Failed to update analytics embed: {e}")
    except Exception as e:
        logger.error(f"Error updating analytics embed: {e}")


def get_next_debate_number() -> int:
    """Get and increment the debate counter."""
    DEBATE_COUNTER_FILE.parent.mkdir(exist_ok=True)

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
    except Exception as e:
        logger.warning(f"Failed to get debate number: {e}")
        return 1


def is_english_only(text: str) -> bool:
    """
    Check if text contains only English characters, numbers, and common punctuation.

    Args:
        text: The text to validate

    Returns:
        True if text is English-only, False otherwise

    DESIGN: Allows English letters, numbers, spaces, and common punctuation
    Rejects Arabic, Chinese, Cyrillic, and other non-Latin scripts
    """
    import unicodedata

    for char in text:
        # Allow English letters, numbers, spaces, and common punctuation
        if char.isascii():
            continue

        # Check Unicode category - reject anything that's not Latin-based
        category = unicodedata.category(char)
        name = unicodedata.name(char, "")

        # Reject Arabic, Chinese, Cyrillic, Hebrew, etc.
        if any(script in name for script in [
            "ARABIC",
            "CHINESE",
            "CJK",  # Chinese, Japanese, Korean
            "CYRILLIC",
            "HEBREW",
            "DEVANAGARI",
            "BENGALI",
            "TAMIL",
            "THAI",
            "HANGUL",  # Korean
            "HIRAGANA",  # Japanese
            "KATAKANA",  # Japanese
        ]):
            return False

    return True


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

async def on_message_handler(bot, message: discord.Message) -> None:
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
    """
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

    # DEBATE BAN CHECK: Check if user is banned from this thread or all debates
    if hasattr(bot, 'debates_service') and bot.debates_service is not None:
        is_banned = bot.debates_service.db.is_user_banned(message.author.id, message.channel.id)
        if is_banned:
            try:
                await message.delete()
                logger.info(f"🚫 Deleted message from banned user {message.author.name} in thread {message.channel.id}")
                # Send ephemeral-style DM to user
                try:
                    await message.author.send(
                        f"🚫 You are banned from posting in this debate thread.\n"
                        f"Contact a moderator if you believe this is a mistake."
                    )
                except discord.Forbidden:
                    pass  # User has DMs disabled
            except discord.HTTPException as e:
                logger.warning(f"Failed to delete banned user message: {e}")
            return

    # HOSTILITY CHECK: Process message for hostility detection
    if hasattr(bot, 'hostility_tracker') and bot.hostility_tracker is not None:
        try:
            await bot.hostility_tracker.process_message(message, bot)
        except Exception as e:
            logger.error(f"Hostility check error: {e}")

    # ACCESS CONTROL BYPASS: Skip for Debate Management role and developer
    is_debate_manager = has_debate_management_role(message.author)
    is_developer = message.author.id == DEVELOPER_ID
    skip_access_control = is_debate_manager or is_developer

    if skip_access_control:
        logger.info(f"✅ Bypassing access control for {message.author.name} (manager={is_debate_manager}, dev={is_developer})")

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

                            # Try to send a DM to the user
                            try:
                                await message.author.send(
                                    f"Hi {message.author.name},\n\n"
                                    f"To participate in the debate **{message.channel.name}**, you need to react with ✅ to the analytics embed first.\n\n"
                                    f"Please go back to the thread and react with ✅ to the analytics message to unlock posting access."
                                )
                                logger.info(
                                    f"🚫 Blocked {message.author.name} from posting - sent DM with instructions"
                                )
                            except discord.Forbidden:
                                # User has DMs disabled, send a temporary message in the channel
                                temp_msg = await message.channel.send(
                                    f"{message.author.mention} You need to react with ✅ to the analytics embed above to participate in this debate.",
                                    delete_after=8
                                )
                                logger.info(
                                    f"🚫 Blocked {message.author.name} from posting - sent channel message (DMs disabled)"
                                )
                        except discord.HTTPException as e:
                            logger.warning(f"Failed to enforce access control: {e}")
                        return

                except discord.NotFound:
                    logger.warning(f"Analytics message {analytics_message_id} not found in thread {message.channel.id}")
        except Exception as e:
            logger.error(f"Error checking access control: {e}")

    # For regular replies - only add vote reactions for long messages
    # Use language-aware minimum: 400 chars for Arabic, 200 chars for English/other
    min_length = _get_min_message_length(message.content)
    if len(message.content) >= min_length:
        # Add upvote and downvote reactions
        try:
            await message.add_reaction(UPVOTE_EMOJI)
            await message.add_reaction(DOWNVOTE_EMOJI)
            logger.info(
                f"🗳️ Added vote reactions to {message.author.name}'s reply in debates"
            )
        except discord.HTTPException as e:
            logger.warning(f"Failed to add vote reactions: {e}")
    else:
        logger.debug(
            f"⏭️ Skipped reactions for {message.author.name}'s short message "
            f"({len(message.content)} chars, min {min_length})"
        )

    # ALWAYS update analytics embed after any valid message
    await update_analytics_embed(bot, message.channel)


# =============================================================================
# Thread Create Handler
# =============================================================================

async def on_thread_create_handler(bot, thread: discord.Thread) -> None:
    """
    Event handler for new thread creation in debates forum.

    Args:
        bot: The OthmanBot instance
        thread: The thread that was created

    DESIGN: Auto-number debates, add reactions to original post, and post analytics embed
    Renames thread to "N | Original Title" format
    Posts analytics embed with debate rules and ✅ reaction for participation access
    """
    # Check if it's in debates forum
    if thread.parent_id != DEBATES_FORUM_ID:
        return

    # Get the starter message
    try:
        # DESIGN: For forum threads, the starter message might not be immediately available
        # Try multiple methods to retrieve it with a small delay
        import asyncio

        starter_message = thread.starter_message

        # If not available, wait a moment and try fetching from thread
        if starter_message is None:
            await asyncio.sleep(0.5)  # Small delay to let Discord populate the message

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
            logger.warning("Could not find starter message for debate thread")
            return

        # Skip if it's a bot message
        if starter_message.author.bot:
            return

        # Add upvote and downvote reactions to the original post (always, regardless of language)
        try:
            await starter_message.add_reaction(UPVOTE_EMOJI)
            await starter_message.add_reaction(DOWNVOTE_EMOJI)
            logger.info(f"🗳️ Added vote reactions to {starter_message.author.name}'s debate post")
        except discord.HTTPException as e:
            logger.warning(f"Failed to add vote reactions: {e}")

        # VALIDATION: Check if title is English-only
        original_title = thread.name
        if not is_english_only(original_title):
            logger.info(f"🚫 Non-English debate title detected: '{original_title}' by {starter_message.author.name}")

            try:
                # Import translation utility
                from src.utils.translate import translate_to_english

                # Get AI translation suggestion
                suggested_title = translate_to_english(original_title)
                logger.info(f"💡 AI suggested English title: '{suggested_title}'")

                # Lock and archive the thread
                await thread.edit(locked=True, archived=True)
                logger.info(f"🔒 Locked and archived non-English debate thread: '{original_title}'")

                # Post moderation message in the thread
                moderation_message = (
                    f"<@&{MODERATOR_ROLE_ID}>\n\n"
                    f"⚠️ **Non-English Title Detected**\n\n"
                    f"This debate thread has been locked because the title contains non-English characters.\n\n"
                    f"**Original Title:** {original_title}\n"
                    f"**Suggested Title:** {suggested_title}\n\n"
                    f"**📌 Moderators:** Please rename this thread to an appropriate English title and unlock it."
                )

                await thread.send(moderation_message)
                logger.info(f"📨 Posted moderation message in locked thread '{original_title}'")

            except Exception as e:
                logger.error(f"Failed to handle non-English title: {e}")

            return

        # Get next debate number and rename thread
        debate_number = get_next_debate_number()

        # Only add number if not already numbered
        if not original_title.split("|")[0].strip().isdigit():
            new_title = f"{debate_number} | {original_title}"
            try:
                await thread.edit(name=new_title)
                logger.info(
                    f"📝 Renamed debate #{debate_number}: '{original_title}' → '{new_title}'"
                )
            except discord.HTTPException as e:
                logger.warning(f"Failed to rename debate thread: {e}")


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
                        # Apply tags to the thread
                        await thread.edit(applied_tags=tags_to_apply)
                        tag_names = [tag.name for tag in tags_to_apply]
                        logger.info(f"🏷️ Auto-applied tags to debate #{debate_number}: {', '.join(tag_names)}")
        except Exception as e:
            logger.error(f"Failed to auto-tag debate thread: {e}")

        # Post analytics embed
        if hasattr(bot, 'debates_service') and bot.debates_service is not None:
            try:
                # Calculate initial analytics
                analytics = await calculate_debate_analytics(thread, bot.debates_service.db)

                # Generate and send analytics embed
                embed = await generate_analytics_embed(bot, analytics)
                analytics_message = await thread.send(embed=embed)

                # Add participation reaction for access control
                await analytics_message.add_reaction(PARTICIPATE_EMOJI)

                # Pin the analytics message
                await analytics_message.pin()

                # Delete the "pinned a message" system message
                await asyncio.sleep(0.5)  # Wait for Discord to create the system message
                async for msg in thread.history(limit=5):
                    if msg.type == discord.MessageType.pins_add:
                        try:
                            await msg.delete()
                            logger.debug("🗑️ Deleted 'pinned a message' system message")
                        except discord.HTTPException:
                            pass
                        break

                # Store analytics message ID in database
                bot.debates_service.db.set_analytics_message(thread.id, analytics_message.id)

                logger.info(f"📊 Posted and pinned analytics embed for debate #{debate_number} with access control")
            except Exception as e:
                logger.error(f"Failed to post analytics embed for debate thread: {e}")

    except discord.HTTPException as e:
        logger.warning(f"Failed to process debate thread creation: {e}")


# =============================================================================
# Reaction Handlers
# =============================================================================

async def on_debate_reaction_add(
    bot,
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
            logger.debug(
                f"🚫 Prevented self-vote: {user.name} tried to vote on their own post"
            )
        except discord.HTTPException as e:
            logger.warning(f"Failed to remove self-vote reaction: {e}")
        return

    # Record the vote
    if emoji == UPVOTE_EMOJI:
        bot.debates_service.record_upvote(voter_id, message.id, author_id)
    else:
        bot.debates_service.record_downvote(voter_id, message.id, author_id)

    # Update analytics embed
    await update_analytics_embed(bot, reaction.message.channel)


async def on_debate_reaction_remove(
    bot,
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

    # Remove the vote
    bot.debates_service.remove_vote(user.id, reaction.message.id)

    # Update analytics embed
    await update_analytics_embed(bot, reaction.message.channel)


# =============================================================================
# Member Leave Handler
# =============================================================================

async def on_member_remove_handler(bot, member: discord.Member) -> None:
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
    if not debates_forum:
        return

    deleted_threads = 0
    deleted_messages = 0
    reactions_removed = 0

    try:
        # Collect all threads (active + archived) to process
        all_threads = list(debates_forum.threads)
        async for archived_thread in debates_forum.archived_threads(limit=100):
            all_threads.append(archived_thread)

        # First, remove user's reactions from all thread starter messages
        for thread in all_threads:
            try:
                starter_message = thread.starter_message
                if not starter_message:
                    starter_message = await thread.fetch_message(thread.id)

                if starter_message:
                    for reaction in starter_message.reactions:
                        try:
                            await reaction.remove(member)
                            reactions_removed += 1
                        except discord.HTTPException:
                            pass
            except discord.HTTPException:
                pass

        for thread in all_threads:
            # If user owns the thread, delete the entire thread
            if thread.owner_id == member.id:
                try:
                    await thread.delete()
                    deleted_threads += 1
                    logger.info(
                        f"🗑️ Deleted debate thread '{thread.name}' "
                        f"(created by {member.name} who left)"
                    )
                except discord.HTTPException as e:
                    logger.warning(f"Failed to delete thread '{thread.name}': {e}")
            else:
                # Delete all messages by this user in threads they don't own
                try:
                    async for message in thread.history(limit=500):
                        if message.author.id == member.id:
                            try:
                                await message.delete()
                                deleted_messages += 1
                            except discord.HTTPException:
                                pass  # Message may already be deleted
                except discord.HTTPException as e:
                    logger.warning(f"Failed to scan thread '{thread.name}' for messages: {e}")

        # Reset karma and delete all database records for this user
        if hasattr(bot, 'debates_service') and bot.debates_service is not None:
            try:
                deleted_data = bot.debates_service.db.delete_user_data(member.id)
                logger.info(
                    f"🗑️ Deleted database records for {member.name}: "
                    f"karma={deleted_data.get('karma', 0)}, "
                    f"votes_cast={deleted_data.get('votes_cast', 0)}, "
                    f"votes_received={deleted_data.get('votes_received', 0)}, "
                    f"bans={deleted_data.get('bans', 0)}, "
                    f"hostility={deleted_data.get('hostility', 0)}"
                )
            except Exception as e:
                logger.error(f"Failed to delete database records for {member.name}: {e}")

        # Update leaderboard to mark user as left
        if hasattr(bot, 'leaderboard_manager') and bot.leaderboard_manager is not None:
            try:
                await bot.leaderboard_manager.on_member_leave(member.id)
            except Exception as e:
                logger.error(f"Failed to update leaderboard for {member.name}: {e}")

        # Log summary
        if deleted_threads > 0 or deleted_messages > 0 or reactions_removed > 0:
            logger.info(
                f"✅ Cleaned up {deleted_threads} thread(s), {deleted_messages} message(s), "
                f"and {reactions_removed} reaction(s) from {member.name} who left the server"
            )

    except Exception as e:
        logger.error(f"Error cleaning up debate data for {member.name}: {e}")


# =============================================================================
# Member Join Handler
# =============================================================================

async def on_member_join_handler(bot, member: discord.Member) -> None:
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
        except Exception as e:
            logger.error(f"Failed to update leaderboard for rejoining member {member.name}: {e}")


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
]
