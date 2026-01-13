"""
OthmanBot - Cases Command
=========================

Slash command for looking up moderation cases.

Commands:
- /cases - Look up a user's case history or search by case ID

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import CASE_LOG_FORUM_ID, has_debates_management_role, EmbedColors
from src.utils.footer import set_footer
from src.utils.autocomplete import case_search_autocomplete

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Cases Cog
# =============================================================================

class CasesCog(commands.Cog):
    """Cog for /cases command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @app_commands.command(name="cases", description="Look up a user's moderation case history")
    @app_commands.describe(
        user="User to look up (search by name, user ID, or case ID)"
    )
    @app_commands.autocomplete(user=case_search_autocomplete)
    @app_commands.default_permissions(manage_messages=True)
    async def cases(
        self,
        interaction: discord.Interaction,
        user: str
    ) -> None:
        """Look up a user's case history."""
        # Log command invocation
        logger.info("/cases Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("User Param", user),
        ])

        # Security check: Verify user has Debates Management role
        if not has_debates_management_role(interaction.user):
            logger.warning("/cases Command Denied - Missing Role", [
                ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
            ])
            await interaction.response.send_message(
                "You don't have permission to use this command. "
                "Only users with the Debates Management role can view cases.",
                ephemeral=True
            )
            return

        # Guild check - command only works in servers
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True
            )
            return

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/cases Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                ("Reason", "Debates service not initialized"),
            ])
            await interaction.response.send_message(
                "Case system is not available.",
                ephemeral=True
            )
            return

        if not CASE_LOG_FORUM_ID:
            await interaction.response.send_message(
                "Case logging is not configured.",
                ephemeral=True
            )
            return

        # Resolve user string to ID
        try:
            user_id = int(user)
        except ValueError:
            logger.warning("/cases Command Failed - Invalid User ID", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                ("Invalid User Param", user),
                ("Reason", "Could not parse user as integer"),
            ])
            await interaction.response.send_message(
                "Invalid user. Please select a user from the autocomplete list.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        # Get case info
        db = self.bot.debates_service.db
        case = db.get_case_log(user_id)

        if not case:
            # Try to get member info for the message
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            display_name = member.display_name if member else f"User {user_id}"

            await interaction.followup.send(
                f"No case found for **{display_name}**.",
                ephemeral=True
            )
            return

        # Try to get user info
        member = interaction.guild.get_member(user_id) if interaction.guild else None
        if member:
            display_name = member.display_name
            avatar_url = member.display_avatar.url
        else:
            # Try to fetch user
            try:
                fetched_user = await self.bot.fetch_user(user_id)
                display_name = fetched_user.display_name if fetched_user else f"User {user_id}"
                avatar_url = fetched_user.display_avatar.url if fetched_user else None
            except discord.HTTPException as e:
                logger.debug("Failed to fetch user for case lookup", [("User ID", str(user_id)), ("Error", str(e))])
                display_name = f"User {user_id}"
                avatar_url = None

        # Build case info embed
        embed = discord.Embed(
            title=f"Case [{case['case_id']:04d}]",
            description=f"Moderation case for **{display_name}**",
            color=EmbedColors.INFO
        )

        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case['case_id']:04d}`", inline=True)
        embed.add_field(name="Total Bans", value=f"`{case['ban_count']}`", inline=True)

        # Case thread link
        thread_link = f"https://discord.com/channels/{interaction.guild.id}/{case['thread_id']}"
        embed.add_field(
            name="Case Thread",
            value=f"[View Thread]({thread_link})",
            inline=True
        )

        # Case created date
        if case.get('created_at'):
            embed.add_field(
                name="First Banned",
                value=f"`{case['created_at'][:19]}`",  # Truncate microseconds
                inline=True
            )

        # Last unban date
        if case.get('last_unban_at'):
            embed.add_field(
                name="Last Unbanned",
                value=f"`{case['last_unban_at'][:19]}`",
                inline=True
            )

        set_footer(embed)

        await interaction.followup.send(embed=embed)

        logger.success("📋 Case Lookup Complete", [
            ("User", f"{display_name} ({user_id})"),
            ("Case ID", f"{case['case_id']:04d}"),
            ("Ban Count", str(case['ban_count'])),
            ("Looked Up By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("Mod ID", str(interaction.user.id)),
        ])


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(CasesCog(bot))
    logger.tree("Command Loaded", [("Name", "cases")], emoji="✅")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CasesCog", "setup"]
