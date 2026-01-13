"""
OthmanBot - Allow Command
=========================

Slash command for unbanning users from debate threads.

Commands:
- /allow - Unban a user from a debate thread or all debates

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import has_debates_management_role, EmbedColors
from src.utils.footer import set_footer
from src.utils.autocomplete import banned_user_autocomplete, thread_id_autocomplete

if TYPE_CHECKING:
    from src.bot import OthmanBot


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
            ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("User Param", user),
            ("Thread ID Param", thread_id),
        ])

        # Security check: Verify user has Debates Management role
        if not has_debates_management_role(interaction.user):
            logger.warning("/allow Command Denied - Missing Role", [
                ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
            ])
            await interaction.response.send_message(
                "You don't have permission to use this command. "
                "Only users with the Debates Management role can unban users from debates.",
                ephemeral=True
            )
            return

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/allow Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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

        # Try to get the member from the guild
        member = interaction.guild.get_member(user_id)
        display_name = member.display_name if member else f"User {user_id}"

        # Protect Debates Management role members (only developer can unban them)
        from src.core.config import DEVELOPER_ID, DEBATES_MANAGEMENT_ROLE_ID
        if member and DEBATES_MANAGEMENT_ROLE_ID and interaction.user.id != DEVELOPER_ID:
            if any(role.id == DEBATES_MANAGEMENT_ROLE_ID for role in member.roles):
                logger.warning("/allow Command Rejected - Protected User", [
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                    ("Target User", f"{member.name} ({member.id})"),
                    ("Reason", "Target has Debates Management role"),
                ])
                await interaction.response.send_message(
                    "You cannot unban a member of the Debates Management team. "
                    "Only the developer can do this.",
                    ephemeral=True
                )
                return

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
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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
                color=EmbedColors.UNBAN
            )
            # Only set thumbnail if member is still in server
            if member:
                embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Unbanned By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Scope", value=scope.title(), inline=True)

            set_footer(embed)

            await interaction.followup.send(embed=embed, wait=True)

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

            # Send DM notification to the unbanned user
            try:
                if self.bot.ban_notifier and member:
                    await self.bot.ban_notifier.notify_unban(
                        user=member,
                        unbanned_by=interaction.user,
                        scope=scope,
                        thread_id=target_thread_id,
                        reason=reason
                    )
            except Exception as e:
                logger.warning("Failed to send unban notification DM", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)),
                ])
        else:
            logger.info("/allow Command - User Was Not Banned", [
                ("Target User", f"{display_name} ({user_id})"),
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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
    logger.tree("Command Loaded", [("Name", "allow")], emoji="✅")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AllowCog", "setup"]
