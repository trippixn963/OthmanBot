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
from src.core.config import EmbedColors
from src.utils.footer import set_footer

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
            if hasattr(self.bot, 'interaction_logger') and self.bot.interaction_logger:
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
        analytics = self.bot.debates_service.db.get_user_analytics(target.id)
        streak = self.bot.debates_service.db.get_user_streak(target.id)

        # Calculate engagement ratio
        total_votes = karma_data.upvotes_received + karma_data.downvotes_received
        if total_votes > 0:
            approval_rate = (karma_data.upvotes_received / total_votes) * 100
            approval_display = f"`{approval_rate:.1f}%`"
        else:
            approval_display = "`N/A`"

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
            name="Approval Rate",
            value=approval_display,
            inline=True
        )

        # Row 2: Votes breakdown
        embed.add_field(
            name="Votes Received",
            value=f"⬆️ `{karma_data.upvotes_received:,}` | ⬇️ `{karma_data.downvotes_received:,}`",
            inline=False
        )

        # Row 3: Participation stats
        embed.add_field(
            name="Debates Participated",
            value=f"`{analytics['debates_participated']:,}`",
            inline=True
        )
        embed.add_field(
            name="Debates Created",
            value=f"`{analytics['debates_created']:,}`",
            inline=True
        )
        embed.add_field(
            name="Total Messages",
            value=f"`{analytics['total_messages']:,}`",
            inline=True
        )

        # Row 4: Streak stats
        current_streak = streak['current_streak']
        longest_streak = streak['longest_streak']
        streak_emoji = "🔥" if current_streak >= 7 else "⚡" if current_streak >= 3 else "📅"
        embed.add_field(
            name=f"{streak_emoji} Daily Streak",
            value=f"`{current_streak}` day{'s' if current_streak != 1 else ''}",
            inline=True
        )
        embed.add_field(
            name="🏆 Longest Streak",
            value=f"`{longest_streak}` day{'s' if longest_streak != 1 else ''}",
            inline=True
        )
        # Empty field for alignment
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        set_footer(embed)

        logger.success("/karma Command Completed", [
            ("Requested By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target User", f"{target.name} ({target.id})"),
            ("Karma", str(karma_data.total_karma)),
            ("Rank", f"#{rank}"),
            ("Approval", approval_display.strip('`')),
            ("Debates", str(analytics['debates_participated'])),
        ])

        await interaction.response.send_message(embed=embed)

        # Get the message ID for direct linking in webhook
        message_id = None
        try:
            original_response = await interaction.original_response()
            message_id = original_response.id
            logger.debug("Got message ID for webhook", [
                ("Message ID", str(message_id)),
            ])
        except Exception as e:
            logger.debug("Could not get original response", [
                ("Error", str(e)),
            ])

        # Log success to webhook
        if self.bot.interaction_logger:
            await self.bot.interaction_logger.log_command(
                interaction, "karma", success=True,
                message_id=message_id,
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
