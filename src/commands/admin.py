"""
Othman Discord Bot - Admin Commands
====================================

Admin-only slash commands for bot control.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEVELOPER_ID, SYRIA_GUILD_ID

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Admin Cog
# =============================================================================

class AdminCommands(commands.Cog):
    """Admin commands for bot control."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    # =========================================================================
    # Toggle Command
    # =========================================================================

    @app_commands.command(name="toggle", description="Toggle bot on/off (Developer only)")
    @app_commands.guilds(discord.Object(id=SYRIA_GUILD_ID))
    async def toggle(self, interaction: discord.Interaction) -> None:
        """
        Toggle bot enabled/disabled state.

        When disabled:
        - All event handlers stop processing
        - All schedulers stop posting
        - Presence shows "OFFLINE - Disabled"
        - Bot stays connected for re-enabling
        """
        # Check if user is developer
        if interaction.user.id != DEVELOPER_ID:
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True
            )
            return

        # Toggle state
        current_state = getattr(self.bot, 'disabled', False)
        new_state = not current_state
        self.bot.disabled = new_state

        if new_state:
            # Bot is now DISABLED
            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="OFFLINE - Disabled"
                )
            )
            logger.warning("Bot Disabled", [
                ("By", interaction.user.name),
                ("User ID", str(interaction.user.id)),
            ])
            await interaction.response.send_message(
                "Bot has been **disabled**.\n"
                "- All posting/scheduling stopped\n"
                "- All event handlers disabled\n"
                "- Presence set to OFFLINE\n\n"
                "Use `/toggle` again to re-enable.",
                ephemeral=True
            )
        else:
            # Bot is now ENABLED
            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="Syria"
                )
            )
            logger.success("Bot Enabled", [
                ("By", interaction.user.name),
                ("User ID", str(interaction.user.id)),
            ])
            await interaction.response.send_message(
                "Bot has been **enabled**.\n"
                "- All posting/scheduling resumed\n"
                "- All event handlers active\n"
                "- Presence restored",
                ephemeral=True
            )


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Load the admin cog."""
    await bot.add_cog(AdminCommands(bot))
    logger.info("Admin Commands Cog Loaded")
