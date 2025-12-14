"""
OthmanBot - Cases Command
=========================

Slash command for looking up moderation cases.

Commands:
- /cases - Look up a user's case history or search by case ID

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import List, TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DISCORD_AUTOCOMPLETE_LIMIT, CASE_LOG_FORUM_ID
from src.utils import get_developer_avatar

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Autocomplete Functions
# =============================================================================

async def case_search_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplete for case search - shows users with cases."""
    bot = interaction.client

    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return []

    choices = []
    db = bot.debates_service.db

    # Get all case logs
    all_cases = db.get_all_case_logs()

    for case in all_cases[:DISCORD_AUTOCOMPLETE_LIMIT]:
        user_id = case['user_id']
        case_id = case['case_id']

        # Try to get the member from the guild
        member = interaction.guild.get_member(user_id) if interaction.guild else None

        if member:
            name = f"[{case_id:04d}] {member.display_name}"
        else:
            name = f"[{case_id:04d}] User {user_id}"

        # Filter by current input (case ID or user ID)
        if not current or current.lower() in name.lower() or current in str(user_id) or current in str(case_id):
            choices.append(app_commands.Choice(
                name=name[:100],  # Discord limit
                value=str(user_id)
            ))

    return choices[:DISCORD_AUTOCOMPLETE_LIMIT]


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
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("User Param", user),
        ])

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/cases Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
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
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
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
            except Exception:
                display_name = f"User {user_id}"
                avatar_url = None

        # Build case info embed
        embed = discord.Embed(
            title=f"Case [{case['case_id']:04d}]",
            description=f"Moderation case for **{display_name}**",
            color=discord.Color.blue()
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

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        await interaction.followup.send(embed=embed)

        logger.tree("Case Lookup Complete", [
            ("User", f"{display_name} ({user_id})"),
            ("Case ID", f"{case['case_id']:04d}"),
            ("Ban Count", str(case['ban_count'])),
            ("Looked Up By", f"{interaction.user.name}"),
        ], emoji="📋")


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(CasesCog(bot))
    logger.info("Cases Cog Loaded", [
        ("Commands", "/cases"),
    ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CasesCog", "setup"]
