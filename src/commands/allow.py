"""
OthmanBot - Allow Command
=========================

Slash command for unbanning users from debate threads.

Commands:
- /allow - Unban a user from a debate thread or all debates

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import List, TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DISCORD_AUTOCOMPLETE_LIMIT
from src.utils import get_developer_avatar

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Autocomplete Functions
# =============================================================================

async def banned_user_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplete for banned users in /allow command."""
    bot = interaction.client

    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return []

    # Get all banned user IDs
    banned_ids = bot.debates_service.db.get_all_banned_users()

    choices = []
    for user_id in banned_ids[:DISCORD_AUTOCOMPLETE_LIMIT]:
        # Try to get the member from the guild
        member = interaction.guild.get_member(user_id)
        if member:
            name = member.display_name
            # Filter by current input
            if current.lower() in name.lower() or current in str(user_id):
                choices.append(app_commands.Choice(
                    name=f"{name} (Banned)",
                    value=str(user_id)
                ))
        else:
            # User left the server but still in ban list
            if current in str(user_id):
                choices.append(app_commands.Choice(
                    name=f"User ID: {user_id} (Left server)",
                    value=str(user_id)
                ))

    return choices[:DISCORD_AUTOCOMPLETE_LIMIT]


async def thread_id_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplete for thread_id field - shows 'All' option plus allows custom thread IDs."""
    choices = []
    current_lower = current.lower()

    # Always show "All" option if it matches
    if not current or "all" in current_lower:
        choices.append(app_commands.Choice(name="All Debates", value="all"))

    # If user typed something that looks like a thread ID, show it
    if current and current != "all" and current_lower != "all debates":
        choices.append(app_commands.Choice(name=f"Thread: {current}", value=current))

    return choices[:DISCORD_AUTOCOMPLETE_LIMIT]


# =============================================================================
# Allow Cog
# =============================================================================

class AllowCog(commands.Cog):
    """Cog for /allow command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @app_commands.command(name="allow", description="Unban a user from a debate thread")
    @app_commands.describe(
        user="User to unban from debates (shows banned users)",
        thread_id="Thread ID to unban from (use 'all' for all debates)",
        reason="Reason for the unban (optional, will be asked in case thread if not provided)"
    )
    @app_commands.autocomplete(user=banned_user_autocomplete, thread_id=thread_id_autocomplete)
    @app_commands.default_permissions(manage_messages=True)
    async def allow(
        self,
        interaction: discord.Interaction,
        user: str,
        thread_id: str,
        reason: str = None
    ) -> None:
        """Unban a user from a specific debate thread or all debates."""
        # Log command invocation
        logger.info("/allow Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("User Param", user),
            ("Thread ID Param", thread_id),
        ])

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/allow Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", "Debates service not initialized"),
            ])
            await interaction.response.send_message(
                "Debates system is not available.",
                ephemeral=True
            )
            return

        # Resolve user string to ID
        try:
            user_id = int(user)
        except ValueError:
            logger.warning("/allow Command Failed - Invalid User ID", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Invalid User Param", user),
                ("Reason", "Could not parse user as integer"),
            ])
            await interaction.response.send_message(
                "Invalid user. Please select a user from the autocomplete list.",
                ephemeral=True
            )
            return

        # Try to get the member from the guild
        member = interaction.guild.get_member(user_id)
        display_name = member.display_name if member else f"User {user_id}"

        # Parse thread_id (required)
        if thread_id.lower() == "all":
            target_thread_id = None
            scope = "all debates"
        else:
            try:
                target_thread_id = int(thread_id)
                scope = f"thread `{target_thread_id}`"
            except ValueError:
                logger.warning("/allow Command Failed - Invalid Thread ID", [
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Invalid Thread ID", thread_id),
                    ("Reason", "Could not parse thread ID as integer"),
                ])
                await interaction.response.send_message(
                    "Invalid thread ID. Use a number or 'all'.",
                    ephemeral=True
                )
                return

        # Defer the response for consistency
        await interaction.response.defer()

        # Remove the ban
        success = self.bot.debates_service.db.remove_debate_ban(
            user_id=user_id,
            thread_id=target_thread_id
        )

        if success:
            logger.tree("User Unbanned From Debates", [
                ("Unbanned User", f"{display_name} ({user_id})"),
                ("Unbanned By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Scope", scope),
                ("Thread ID", str(target_thread_id) if target_thread_id else "Global"),
            ], emoji="✅")

            # Create user mention (works even if user left server)
            user_mention = f"<@{user_id}>"

            # Create public embed for the unban
            embed = discord.Embed(
                title="User Unbanned from Debates",
                description=(
                    f"**{user_mention}** has been unbanned from {scope}.\n\n"
                    f"They can now post messages there again."
                ),
                color=discord.Color.green()
            )
            # Only set thumbnail if member is still in server
            if member:
                embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Unbanned By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Scope", value=scope.title(), inline=True)

            developer_avatar_url = await get_developer_avatar(self.bot)
            embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

            await interaction.followup.send(embed=embed)

            # Log success to webhook (non-blocking)
            try:
                if self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_user_unbanned(
                        user_id, interaction.user, scope, display_name
                    )
            except Exception as e:
                logger.warning("Failed to log allow to webhook", [
                    ("Error", str(e)),
                ])

            # Log to case system (for mods server forum)
            try:
                if self.bot.case_log_service:
                    await self.bot.case_log_service.log_unban(
                        user_id=user_id,
                        unbanned_by=interaction.user,
                        scope=scope,
                        display_name=display_name,
                        reason=reason
                    )
            except Exception as e:
                logger.warning("Failed to log to case system", [
                    ("Error", str(e)),
                ])
        else:
            logger.info("/allow Command - User Was Not Banned", [
                ("Target User", f"{display_name} ({user_id})"),
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Scope", scope),
            ])
            await interaction.followup.send(
                f"**{display_name}** was not banned from {scope}.",
                ephemeral=True
            )


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(AllowCog(bot))
    logger.info("Allow Cog Loaded", [
        ("Commands", "/allow"),
    ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AllowCog", "setup"]
