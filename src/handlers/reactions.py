"""
Othman Discord Bot - Reaction Handler
======================================

Block reactions on announcement embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord

from src.core.logger import logger


# =============================================================================
# Reaction Handler
# =============================================================================

async def on_reaction_add_handler(
    bot,
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
        logger.info(
            f"🗑️ Removed reaction {reaction.emoji} from {user.name} on announcement"
        )
    except discord.HTTPException as e:
        logger.warning(f"Failed to remove reaction: {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["on_reaction_add_handler"]
