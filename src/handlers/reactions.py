"""
OthmanBot - Reaction Handler
============================

Block reactions on announcement embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import OthmanBot


class ReactionHandler(commands.Cog):
    """Handles reaction events - blocks reactions on announcements."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        user: discord.User
    ) -> None:
        """
        Block ALL reactions on announcement embeds.

        Only enforces on tracked announcement messages.
        Removes reactions immediately to keep announcements clean.
        """
        # Ignore bot's own reactions
        if user.bot:
            return

        # Check if this is an announcement message
        if reaction.message.id not in self.bot.announcement_messages:
            return

        # Remove ALL reactions on announcement embeds
        try:
            await reaction.remove(user)
            logger.info("Announcement Reaction Removed", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Emoji", str(reaction.emoji)),
                ("Message ID", str(reaction.message.id)),
                ("Channel", str(reaction.message.channel.id)),
            ])
        except discord.HTTPException as e:
            logger.warning("Failed To Remove Reaction", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Emoji", str(reaction.emoji)),
                ("Error", str(e)),
            ])


async def setup(bot: "OthmanBot") -> None:
    """Load the ReactionHandler cog."""
    await bot.add_cog(ReactionHandler(bot))
    logger.tree("Handler Loaded", [
        ("Name", "ReactionHandler"),
    ], emoji="✅")
