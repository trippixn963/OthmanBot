"""
OthmanBot - Karma Command
=========================

Slash command for checking user karma points.

Commands:
- /karma - Check karma points for yourself or another user

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.utils import get_developer_avatar

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Karma Cog
# =============================================================================

class KarmaCog(commands.Cog):
    """Cog for /karma command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @app_commands.command(name="karma", description="Check karma points for yourself or another user")
    @app_commands.describe(user="User to check karma for (leave empty for yourself)")
    async def karma(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None
    ) -> None:
        """View karma for a user."""
        # Log command invocation
        logger.info("/karma Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Target User", f"{user.name} ({user.id})" if user else "Self"),
        ])

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/karma Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", "Debates service not initialized"),
            ])
            # Log failure to webhook
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_command(
                    interaction, "karma", success=False, error="Debates service not initialized"
                )
            await interaction.response.send_message(
                "Karma system is not available.",
                ephemeral=True
            )
            return

        target = user or interaction.user
        karma_data = self.bot.debates_service.get_karma(target.id)
        rank = self.bot.debates_service.get_rank(target.id)

        embed = discord.Embed(
            title=f"Karma for {target.display_name}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="Total Karma",
            value=f"`{karma_data.total_karma:,}`",
            inline=True
        )
        embed.add_field(
            name="Rank",
            value=f"`#{rank}`",
            inline=True
        )
        embed.add_field(
            name="Votes Received",
            value=f"Up `{karma_data.upvotes_received:,}` | Down `{karma_data.downvotes_received:,}`",
            inline=False
        )

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        logger.success("/karma Command Completed", [
            ("Requested By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target User", f"{target.name} ({target.id})"),
            ("Karma", str(karma_data.total_karma)),
            ("Rank", f"#{rank}"),
            ("Upvotes", str(karma_data.upvotes_received)),
            ("Downvotes", str(karma_data.downvotes_received)),
        ])

        await interaction.response.send_message(embed=embed)

        # Log success to webhook
        if self.bot.interaction_logger:
            await self.bot.interaction_logger.log_command(
                interaction, "karma", success=True,
                target=target.display_name, karma=karma_data.total_karma, rank=f"#{rank}"
            )


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(KarmaCog(bot))
    logger.info("Karma Cog Loaded", [
        ("Commands", "/karma"),
    ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["KarmaCog", "setup"]
