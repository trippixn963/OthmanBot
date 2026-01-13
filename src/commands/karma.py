"""
OthmanBot - Karma Command
=========================

Slash command for checking user karma points with a beautiful card.

Commands:
- /karma - Check karma points for yourself or another user

Author: John Hamwi
Server: discord.gg/syria
"""

import io
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import EmbedColors
from src.core.emojis import LEADERBOARD_EMOJI
from src.utils.footer import set_footer
from src.services.karma_card import generate_karma_card

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Karma Cog
# =============================================================================

class KarmaCog(commands.Cog):
    """Cog for /karma command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    def _get_member_status(self, member: discord.Member) -> str:
        """Get the Discord status of a member."""
        if member.status == discord.Status.online:
            return "online"
        elif member.status == discord.Status.idle:
            return "idle"
        elif member.status == discord.Status.dnd:
            return "dnd"
        elif member.status == discord.Status.offline:
            return "offline"
        else:
            # Streaming or other
            if any(isinstance(a, discord.Streaming) for a in member.activities):
                return "streaming"
            return "online"

    @app_commands.command(name="karma", description="Check karma points for yourself or another user")
    @app_commands.describe(user="User to check karma for (leave empty for yourself)")
    async def karma(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None
    ) -> None:
        """View karma for a user with a beautiful card."""
        # Defer to allow time for card generation
        await interaction.response.defer()

        # Log command invocation
        logger.info("/karma Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Target User", f"{user.name} ({user.id})" if user else "Self"),
        ])

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/karma Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                ("Reason", "Debates service not initialized"),
            ])
            await interaction.followup.send(
                "Karma system is not available.",
                ephemeral=True
            )
            return

        target = user or interaction.user
        karma_data = self.bot.debates_service.get_karma(target.id)
        rank = self.bot.debates_service.get_rank(target.id)

        # Get member status
        member = target if isinstance(target, discord.Member) else interaction.guild.get_member(target.id)
        status = self._get_member_status(member) if member else "online"

        # Get avatar URL (high resolution)
        avatar_url = target.display_avatar.with_size(256).url

        # Get banner URL if available
        banner_url = None
        if isinstance(target, discord.Member) and target.guild.banner:
            banner_url = target.guild.banner.with_size(1024).url

        try:
            # Generate the karma card
            card_bytes = await generate_karma_card(
                username=target.name,
                display_name=target.display_name,
                avatar_url=avatar_url,
                karma=karma_data.total_karma,
                rank=rank,
                upvotes=karma_data.upvotes_received,
                downvotes=karma_data.downvotes_received,
                status=status,
                banner_url=banner_url,
            )

            # Create file from bytes
            file = discord.File(io.BytesIO(card_bytes), filename="karma_card.png")

            # Create view with leaderboard button
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Leaderboard & More",
                url=f"https://trippixn.com/othman/leaderboard/{target.id}",
                emoji=discord.PartialEmoji.from_str(LEADERBOARD_EMOJI)
            ))

            logger.success("/karma Command Completed", [
                ("Requested By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Target User", f"{target.name} ({target.id})"),
                ("Karma", str(karma_data.total_karma)),
                ("Rank", f"#{rank}"),
            ])

            await interaction.followup.send(file=file, view=view)

        except Exception as e:
            # Fallback to embed if card generation fails
            logger.warning("/karma Card Generation Failed - Fallback to Embed", [
                ("User", f"{target.name} ({target.display_name})"),
                ("ID", str(target.id)),
                ("Error", str(e)[:100]),
            ])

            embed = discord.Embed(
                title=f"Karma for {target.display_name}",
                color=EmbedColors.INFO
            )
            embed.set_thumbnail(url=target.display_avatar.url)

            # Row 1: Core stats
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
                value=f"⬆️ `{karma_data.upvotes_received:,}` ⬇️ `{karma_data.downvotes_received:,}`",
                inline=True
            )

            set_footer(embed)

            # Create view with leaderboard button
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Leaderboard & More",
                url=f"https://trippixn.com/othman/leaderboard/{target.id}",
                emoji=discord.PartialEmoji.from_str(LEADERBOARD_EMOJI)
            ))

            await interaction.followup.send(embed=embed, view=view)


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(KarmaCog(bot))
    logger.tree("Command Loaded", [("Name", "karma")], emoji="✅")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["KarmaCog", "setup"]
