"""
OthmanBot - Debates Reaction Handlers
=====================================

Karma tracking via upvote/downvote reactions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID
from src.core.emojis import UPVOTE_EMOJI, DOWNVOTE_EMOJI
from src.utils.discord_rate_limit import log_http_error
from src.handlers.debates_modules.analytics import update_analytics_embed

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Helper Functions
# =============================================================================

def is_debates_forum_message(channel) -> bool:
    """Check if channel is a thread in the debates forum."""
    if not isinstance(channel, discord.Thread):
        return False
    return channel.parent_id == DEBATES_FORUM_ID


def _is_bot_ready(bot: "OthmanBot") -> bool:
    """Check if the bot is fully ready to handle events."""
    if not bot.is_ready():
        return False
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return False
    return True


# =============================================================================
# Reaction Add Handler
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
    try:
        # Null safety checks
        if reaction is None or user is None or reaction.message is None:
            return

        # Wait for bot to be fully ready
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

        # Skip vote tracking for Open Discussion thread
        if hasattr(bot, 'open_discussion') and bot.open_discussion:
            if bot.open_discussion.is_open_discussion_thread(reaction.message.channel.id):
                return

        message = reaction.message
        author_id = message.author.id
        voter_id = user.id

        # Prevent self-voting
        if voter_id == author_id:
            try:
                await reaction.remove(user)
                vote_type = "Upvote" if emoji == UPVOTE_EMOJI else "Downvote"
                logger.info("🚫 Self-Vote Prevented", [
                    ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                    ("Type", vote_type),
                    ("Thread", f"{message.channel.name} ({message.channel.id})"),
                ])
            except discord.HTTPException as e:
                log_http_error(e, "Remove Self-Vote Reaction", [
                    ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                    ("Message ID", str(message.id)),
                ])
            return

        # Record the vote
        vote_type = "Upvote" if emoji == UPVOTE_EMOJI else "Downvote"
        try:
            if emoji == UPVOTE_EMOJI:
                success = await bot.debates_service.record_upvote_async(voter_id, message.id, author_id)
            else:
                success = await bot.debates_service.record_downvote_async(voter_id, message.id, author_id)

            if not success:
                logger.warning("Vote Recording Failed (No Change)", [
                    ("Voter", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                    ("Message", str(message.id)),
                    ("Type", vote_type),
                ])
                try:
                    await reaction.remove(user)
                except discord.HTTPException as remove_err:
                    logger.debug("Failed To Remove Reaction After Vote Failure", [
                        ("Error", str(remove_err)[:50]),
                    ])
                return

        except Exception as e:
            logger.error("Vote Recording Exception", [
                ("Voter", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Message", str(message.id)),
                ("Type", vote_type),
                ("Error", str(e)),
            ])
            try:
                await reaction.remove(user)
            except discord.HTTPException as remove_err:
                logger.debug("Failed To Remove Reaction After Exception", [
                    ("Error", str(remove_err)[:50]),
                ])
            return

        # Get updated karma for logging
        karma_data = bot.debates_service.get_karma(author_id)
        change = 1 if emoji == UPVOTE_EMOJI else -1

        logger.info("⭐ Karma Changed", [
            ("Author", f"{message.author.name} ({message.author.display_name})"),
            ("ID", str(author_id)),
            ("Change", f"{'+' if change > 0 else ''}{change}"),
            ("New Total", str(karma_data.total_karma)),
            ("Voter", f"{user.name} ({user.display_name})"),
            ("ID", str(user.id)),
            ("Thread", message.channel.name[:30]),
        ])

        # Track stats
        if hasattr(bot, 'daily_stats') and bot.daily_stats:
            bot.daily_stats.record_karma_vote(
                author_id, message.author.name, emoji == UPVOTE_EMOJI
            )

        # Update analytics embed
        await update_analytics_embed(bot, reaction.message.channel)

    except Exception as e:
        logger.error("🗳️ Unhandled Exception In Reaction Add Handler", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
            ("User", f"{user.name} ({user.display_name})" if user else "Unknown"),
            ("ID", str(user.id) if user else "N/A"),
        ])


# =============================================================================
# Reaction Remove Handler
# =============================================================================

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
    try:
        # Null safety checks
        if reaction is None or user is None or reaction.message is None:
            return

        # Wait for bot to be fully ready
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

        # Skip vote tracking for Open Discussion thread
        if hasattr(bot, 'open_discussion') and bot.open_discussion:
            if bot.open_discussion.is_open_discussion_thread(reaction.message.channel.id):
                return

        # Remove the vote
        vote_type = "Upvote" if emoji == UPVOTE_EMOJI else "Downvote"
        removed = bot.debates_service.remove_vote(user.id, reaction.message.id)

        if not removed:
            logger.debug("Vote Already Removed Or Not Found", [
                ("Voter", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Message", str(reaction.message.id)),
                ("Type", vote_type),
            ])
            return

        # Get updated karma for logging
        karma_data = bot.debates_service.get_karma(reaction.message.author.id)
        change = -1 if emoji == UPVOTE_EMOJI else 1

        logger.info("⭐ Vote Removed", [
            ("Author", f"{reaction.message.author.name} ({reaction.message.author.display_name})"),
            ("ID", str(reaction.message.author.id)),
            ("Change", f"{'+' if change > 0 else ''}{change}"),
            ("New Total", str(karma_data.total_karma)),
            ("Voter", f"{user.name} ({user.display_name})"),
            ("ID", str(user.id)),
            ("Thread", reaction.message.channel.name[:30]),
        ])

        # Update analytics embed
        await update_analytics_embed(bot, reaction.message.channel)

    except Exception as e:
        logger.error("🗳️ Unhandled Exception In Reaction Remove Handler", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
            ("User", f"{user.name} ({user.display_name})" if user else "Unknown"),
            ("ID", str(user.id) if user else "N/A"),
        ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "on_debate_reaction_add",
    "on_debate_reaction_remove",
    "is_debates_forum_message",
]
