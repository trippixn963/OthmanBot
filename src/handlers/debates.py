"""
Othman Discord Bot - Debates Handler
=====================================

Auto-react with upvote/downvote on forum thread replies and track karma.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.emojis import UPVOTE_EMOJI, DOWNVOTE_EMOJI, PARTICIPATE_EMOJI
from src.core.config import (
    NY_TZ,
    DEBATES_FORUM_ID,
    MODERATOR_ROLE_ID,
    DEVELOPER_ID,
    DISCORD_API_DELAY,
)
from src.caches import ban_evasion_cache
from src.caches.ban_evasion import BAN_EVASION_ACCOUNT_AGE_DAYS
from src.utils import (
    add_reactions_with_delay,
    send_message_with_retry,
    edit_thread_with_retry,
    delete_message_safe,
    get_min_message_length,
    is_english_only,
    send_webhook_alert_safe,
)
from src.utils.discord_rate_limit import log_http_error
from src.services.debates.analytics import (
    calculate_debate_analytics,
    generate_analytics_embed,
)
from src.services.debates.tags import detect_debate_tags

# Import from sub-modules
from src.handlers.debates_modules.analytics import (
    update_analytics_embed,
    refresh_all_analytics_embeds,
)
from src.handlers.debates_modules.access_control import (
    has_debate_management_role,
    should_skip_access_control,
    check_user_participation,
    check_user_ban,
)
from src.handlers.debates_modules.reactions import (
    on_debate_reaction_add,
    on_debate_reaction_remove,
    is_debates_forum_message,
)
from src.handlers.debates_modules.member_lifecycle import (
    on_member_remove_handler,
    on_member_join_handler,
)
from src.handlers.debates_modules.thread_management import (
    get_next_debate_number,
    on_thread_delete_handler,
)

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Bot Ready Check
# =============================================================================

def _is_bot_ready(bot: "OthmanBot") -> bool:
    """Check if the bot is fully ready to handle events."""
    if not bot.is_ready():
        return False
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return False
    return True


# =============================================================================
# Message Handler
# =============================================================================

async def on_message_handler(bot: "OthmanBot", message: discord.Message) -> None:
    """
    Event handler for messages in the debates forum.

    DESIGN: Auto-react with upvote/downvote on substantive replies in debates forum
    Only reacts on replies that meet minimum character threshold
    Filters out spam and low-effort messages

    ACCESS CONTROL: Checks if users have reacted to participate before allowing posts
    """
    # Null safety checks
    if message is None or message.author is None or message.channel is None:
        return

    if not _is_bot_ready(bot):
        return

    if message.author.bot:
        return

    if not isinstance(message.channel, discord.Thread):
        return

    if message.channel.parent_id != DEBATES_FORUM_ID:
        return

    # Skip thread starter messages
    is_thread_starter = (message.id == message.channel.id)
    if is_thread_starter:
        return

    # Handle Open Discussion thread separately
    if hasattr(bot, 'open_discussion') and bot.open_discussion:
        is_open_discussion = await bot.open_discussion.on_message(message)
        if is_open_discussion:
            return

    bot_disabled = getattr(bot, 'disabled', False)

    # Track participation ALWAYS
    if hasattr(bot, 'debates_service') and bot.debates_service is not None:
        try:
            await bot.debates_service.db.increment_participation_async(
                message.channel.id, message.author.id
            )
            await bot.debates_service.db.update_user_streak_async(message.author.id)
        except sqlite3.Error as e:
            logger.warning("📊 Failed To Track Participation (DB Error)", [("Error", str(e))])
            await send_webhook_alert_safe(
                bot, "Database Error - Participation Tracking",
                f"User: {message.author.id}, Thread: {message.channel.id}, Error: {str(e)}"
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.warning("📊 Failed To Track Participation (Async Error)", [("Error", str(e))])

    if bot_disabled:
        return

    # Ban evasion detection
    if ban_evasion_cache.should_alert(message.author.id):
        account_created = message.author.created_at
        now = datetime.now(account_created.tzinfo) if account_created.tzinfo else datetime.utcnow()
        account_age_days = (now - account_created).days

        if account_age_days < BAN_EVASION_ACCOUNT_AGE_DAYS:
            ban_evasion_cache.record_alert(message.author.id)
            logger.warning("🚨 Potential Ban Evasion Detected", [
                ("User", f"{message.author.name} ({message.author.display_name})"),
                ("ID", str(message.author.id)),
                ("Account Age", f"{account_age_days} days"),
                ("Thread", message.channel.name),
                ("Developer", f"<@{DEVELOPER_ID}>"),
            ])

    # Check if user is banned
    if not await check_user_ban(bot, message):
        return

    # Access control (skip for managers/mods/developer)
    skip_access_control = should_skip_access_control(message.author)
    if skip_access_control:
        logger.info("Access Control Bypassed", [
            ("User", f"{message.author.name} ({message.author.display_name})"),
            ("ID", str(message.author.id)),
            ("Thread", f"{message.channel.name} ({message.channel.id})"),
        ])

    if not skip_access_control:
        if not await check_user_participation(bot, message):
            return

    # Add vote reactions for long messages
    min_length = get_min_message_length(message.content)
    if len(message.content) >= min_length:
        try:
            await add_reactions_with_delay(message, [UPVOTE_EMOJI, DOWNVOTE_EMOJI])
            logger.info("⬆️ Vote Reactions Added to Reply", [
                ("User", f"{message.author.name} ({message.author.display_name})"),
                ("ID", str(message.author.id)),
                ("Thread", f"{message.channel.name} ({message.channel.id})"),
                ("Message ID", str(message.id)),
                ("Content Length", f"{len(message.content)} chars"),
            ])
        except discord.HTTPException as e:
            log_http_error(e, "Add Vote Reactions", [
                ("Message ID", str(message.id)),
                ("Thread", str(message.channel.id)),
            ])
    else:
        logger.debug("⏭️ Skipped Reactions For Short Message", [
            ("User", message.author.name),
            ("Length", f"{len(message.content)} chars"),
            ("Min Required", f"{min_length} chars"),
        ])

    await update_analytics_embed(bot, message.channel)


# =============================================================================
# Thread Create Handler
# =============================================================================

async def on_thread_create_handler(bot: "OthmanBot", thread: discord.Thread) -> None:
    """
    Event handler for new thread creation in debates forum.

    DESIGN: Auto-number debates, add reactions to original post, and post analytics embed
    """
    if thread is None:
        return

    if not _is_bot_ready(bot):
        return

    if thread.parent_id is None or thread.parent_id != DEBATES_FORUM_ID:
        return

    try:
        # Get the starter message
        starter_message = thread.starter_message

        if starter_message is None:
            await asyncio.sleep(DISCORD_API_DELAY)
            try:
                starter_message = await thread.fetch_message(thread.id)
            except discord.NotFound:
                logger.debug("Starter message not found by thread ID, trying history")

        if starter_message is None:
            async for message in thread.history(limit=1, oldest_first=True):
                starter_message = message
                break

        if starter_message is None:
            logger.warning("🔍 Could Not Find Starter Message For Debate Thread")
            return

        if starter_message.author.bot:
            return

        # Skip Open Discussion thread
        if hasattr(bot, 'open_discussion') and bot.open_discussion:
            if bot.open_discussion.is_open_discussion_thread(thread.id):
                return

        # Add upvote reaction to original post
        try:
            await starter_message.add_reaction(UPVOTE_EMOJI)
            logger.info("Vote Reactions Added to Debate Post", [
                ("Author", f"{starter_message.author.name} ({starter_message.author.display_name})"),
                ("ID", str(starter_message.author.id)),
                ("Thread", f"{thread.name} ({thread.id})"),
            ])
        except discord.HTTPException as e:
            log_http_error(e, "Add Vote Reactions To Post", [("Thread", f"{thread.name} ({thread.id})")])

        # Check if title is English-only
        original_title = thread.name
        if not is_english_only(original_title):
            logger.warning("Non-English Debate Title Detected", [
                ("User", f"{starter_message.author.name} ({starter_message.author.display_name})"),
                ("ID", str(starter_message.author.id)),
                ("Title", original_title),
            ])

            try:
                from src.utils.translate import translate_to_english
                suggested_title = await translate_to_english(original_title)

                await edit_thread_with_retry(thread, locked=True, archived=True)

                moderation_message = (
                    f"<@&{MODERATOR_ROLE_ID}>\n\n"
                    f"⚠️ **Non-English Title Detected**\n\n"
                    f"**Original Title:** {original_title}\n"
                    f"**Suggested Title:** {suggested_title}\n\n"
                    f"**📌 Moderators:** Use `/rename` to rename and unlock this thread."
                )
                await send_message_with_retry(thread, content=moderation_message)

                logger.warning("🌐 Non-English Debate Title Blocked", [
                    ("User", f"{starter_message.author.name} ({starter_message.author.display_name})"),
                    ("ID", str(starter_message.author.id)),
                    ("Original Title", original_title),
                    ("Suggested", suggested_title),
                ])
            except Exception as e:
                logger.error("🌐 Failed To Handle Non-English Title", [("Error", str(e))])

            return

        # Get next debate number and rename thread
        debate_number = await get_next_debate_number(bot)

        if not original_title.split("|")[0].strip().isdigit():
            new_title = f"{debate_number} | {original_title}"
            if len(new_title) > 100:
                new_title = new_title[:97] + "..."
            success = await edit_thread_with_retry(thread, name=new_title)
            if success:
                logger.success("New Debate Thread Created", [
                    ("Number", f"#{debate_number}"),
                    ("User", f"{starter_message.author.name} ({starter_message.author.display_name})"),
                    ("ID", str(starter_message.author.id)),
                    ("Title", new_title),
                ])

        # Auto-tag
        try:
            thread_title = original_title
            thread_description = starter_message.content if starter_message.content else ""
            tag_ids = await detect_debate_tags(thread_title, thread_description)

            if tag_ids:
                parent_forum = bot.get_channel(DEBATES_FORUM_ID)
                if parent_forum and hasattr(parent_forum, 'available_tags'):
                    available_tags = {tag.id: tag for tag in parent_forum.available_tags}
                    tags_to_apply = [available_tags[tid] for tid in tag_ids if tid in available_tags]

                    if tags_to_apply:
                        success = await edit_thread_with_retry(thread, applied_tags=tags_to_apply)
                        if success:
                            logger.info("Auto-Tags Applied to Debate", [
                                ("Debate", f"#{debate_number}"),
                                ("Tags", ", ".join(t.name for t in tags_to_apply)),
                            ])
        except Exception as e:
            logger.error("🏷️ Failed To Auto-Tag Debate Thread", [("Error", str(e))])

        # Post analytics embed
        if hasattr(bot, 'debates_service') and bot.debates_service is not None:
            try:
                analytics = await calculate_debate_analytics(thread, bot.debates_service.db)
                embed = await generate_analytics_embed(bot, analytics)
                analytics_message = await send_message_with_retry(thread, embed=embed)

                if analytics_message:
                    await add_reactions_with_delay(analytics_message, [PARTICIPATE_EMOJI])

                    try:
                        await analytics_message.pin()
                        await asyncio.sleep(DISCORD_API_DELAY)
                        async for msg in thread.history(limit=5):
                            if msg.type == discord.MessageType.pins_add:
                                await delete_message_safe(msg)
                                break
                    except discord.HTTPException as e:
                        log_http_error(e, "Pin Analytics Message", [("Thread", str(thread.id))])

                    bot.debates_service.db.set_analytics_message(thread.id, analytics_message.id)

                    try:
                        await bot.debates_service.db.set_debate_creator_async(
                            thread.id, starter_message.author.id
                        )
                    except Exception as e:
                        logger.warning("📊 Failed To Track Debate Creator", [("Error", str(e))])

                    logger.success("📊 New Debate Created", [
                        ("Number", f"#{debate_number}"),
                        ("User", f"{starter_message.author.name} ({starter_message.author.display_name})"),
                        ("ID", str(starter_message.author.id)),
                        ("Title", original_title[:50]),
                    ])

                    if hasattr(bot, 'daily_stats') and bot.daily_stats:
                        bot.daily_stats.record_debate_created(
                            thread.id, original_title, starter_message.author.id, starter_message.author.name
                        )

            except Exception as e:
                logger.error("📊 Analytics Embed Error", [("Error", str(e))])

    except discord.HTTPException as e:
        log_http_error(e, "Process Debate Thread Creation", [("Thread", f"{thread.name} ({thread.id})")])


# =============================================================================
# Debates Handler Cog
# =============================================================================

class DebatesHandler(commands.Cog):
    """Handles all debate forum events: messages, reactions, threads, members."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Route message events to the debates handler."""
        await on_message_handler(self.bot, message)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        """Route thread creation events."""
        if getattr(self.bot, 'disabled', False):
            return
        await on_thread_create_handler(self.bot, thread)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        """Route thread deletion events."""
        if getattr(self.bot, 'disabled', False):
            return
        await on_thread_delete_handler(self.bot, thread)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        """Route reaction add events."""
        await on_debate_reaction_add(self.bot, reaction, user)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User) -> None:
        """Route reaction remove events."""
        await on_debate_reaction_remove(self.bot, reaction, user)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Route member remove events."""
        if getattr(self.bot, 'disabled', False):
            return
        await on_member_remove_handler(self.bot, member)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Route member join events."""
        if getattr(self.bot, 'disabled', False):
            return
        await on_member_join_handler(self.bot, member)


async def setup(bot: "OthmanBot") -> None:
    """Load the DebatesHandler cog."""
    await bot.add_cog(DebatesHandler(bot))
    logger.tree("Handler Loaded", [("Name", "DebatesHandler")], emoji="✅")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DebatesHandler",
    "on_message_handler",
    "on_thread_create_handler",
    "on_debate_reaction_add",
    "on_debate_reaction_remove",
    "on_member_remove_handler",
    "on_member_join_handler",
    "on_thread_delete_handler",
    "refresh_all_analytics_embeds",
    "update_analytics_embed",
    "get_next_debate_number",
]
