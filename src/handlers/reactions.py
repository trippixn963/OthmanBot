"""
Othman Discord Bot - Reaction Handler
======================================

Block reactions on announcement embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Reaction Handler
# =============================================================================

async def on_reaction_add_handler(
    bot: "OthmanBot",
    reaction: discord.Reaction,
    user: discord.User
) -> None:
    """
    Event handler for when a reaction is added to a message.

    Args:
        bot: The OthmanBot instance
        reaction: The reaction that was added
        user: The user who added the reaction

    DESIGN: Block ALL reactions on announcement embeds
    Only enforces on tracked announcement messages
    Removes reactions immediately to keep announcements clean
    """
    # Ignore bot's own reactions
    if user.bot:
        return

    # Check if this is an announcement message
    if reaction.message.id not in bot.announcement_messages:
        return

    # Remove ALL reactions on announcement embeds
    try:
        await reaction.remove(user)
        logger.info("Announcement Reaction Removed", [
            ("User", f"{user.name} ({user.id})"),
            ("Emoji", str(reaction.emoji)),
            ("Message ID", str(reaction.message.id)),
            ("Channel", str(reaction.message.channel.id)),
        ])
    except discord.HTTPException as e:
        logger.warning("📛 Failed To Remove Reaction", [
            ("Error", str(e)),
        ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["on_reaction_add_handler"]
