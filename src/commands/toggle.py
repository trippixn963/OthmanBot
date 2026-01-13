"""
OthmanBot - Toggle Command
==========================

Developer-only command for remote bot control.

Commands:
- /toggle - Enable/disable bot functionality

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, List

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEVELOPER_ID, SYRIA_GUILD_ID, TOGGLE_CHANNEL_IDS, CONTENT_PREVIEW_LENGTH, EmbedColors
from src.core.backup import create_backup

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Toggle Cog
# =============================================================================

class ToggleCog(commands.Cog):
    """Developer-only toggle command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

        logger.tree("Toggle Cog Loaded", [
            ("Commands", "/toggle"),
            ("Developer ID", str(DEVELOPER_ID) if DEVELOPER_ID else "Not set"),
            ("Channels to toggle", str(len(TOGGLE_CHANNEL_IDS))),
        ], emoji="🔧")

    def _is_developer(self, user_id: int) -> bool:
        """Check if user is the developer."""
        return DEVELOPER_ID is not None and user_id == DEVELOPER_ID

    # =========================================================================
    # Toggle Command
    # =========================================================================

    @app_commands.command(
        name="toggle",
        description="Toggle bot on/off (Developer only)"
    )
    @app_commands.describe(action="Turn the bot ON or OFF")
    @app_commands.choices(action=[
        app_commands.Choice(name="🟢 On", value="on"),
        app_commands.Choice(name="🔴 Off", value="off"),
    ])
    @app_commands.guilds(discord.Object(id=SYRIA_GUILD_ID))
    async def toggle_command(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str]
    ) -> None:
        """
        Toggle bot enabled/disabled state.

        When disabled:
        - All event handlers stop processing
        - All schedulers stop posting
        - Presence shows "OFFLINE - Disabled"
        - Channels are hidden from @everyone
        - Bot stays connected for re-enabling
        """
        # Check if user is developer
        if not self._is_developer(interaction.user.id):
            embed = discord.Embed(
                title="Access Denied",
                description="This command is restricted to the bot developer.",
                color=EmbedColors.BAN
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

            logger.warning("Unauthorized Toggle Attempt", [
                ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
                ("Action", action.value),
            ])
            return

        await interaction.response.defer(ephemeral=True)

        # Check current state
        is_disabled = getattr(self.bot, 'disabled', False)

        # Handle "off" action
        if action.value == "off":
            if is_disabled:
                embed = discord.Embed(
                    title="Already Disabled",
                    description="Bot is already turned off.",
                    color=EmbedColors.WARNING
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            await self._graceful_disable(interaction)

        # Handle "on" action
        else:
            if not is_disabled:
                embed = discord.Embed(
                    title="Already Enabled",
                    description="Bot is already turned on.",
                    color=EmbedColors.WARNING
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            await self._enable_bot(interaction)

    async def _graceful_disable(self, interaction: discord.Interaction) -> None:
        """Gracefully disable the bot with proper state saving."""
        steps_completed: List[str] = []

        try:
            # Step 1: Mark as disabled (prevents new processing)
            self.bot.disabled = True
            steps_completed.append("Marked disabled")

            # Step 2: Save database state (flush any pending writes)
            if hasattr(self.bot, 'debates_service') and self.bot.debates_service:
                try:
                    # Flush pending transactions and checkpoint WAL
                    self.bot.debates_service.db.flush()
                    steps_completed.append("Database flushed")
                except Exception as e:
                    logger.warning("Failed to flush database during toggle", [
                        ("Error", str(e)),
                    ])

            # Step 3: Create backup before disabling
            try:
                async with asyncio.timeout(10.0):
                    backup_path = await asyncio.to_thread(create_backup)
                    if backup_path:
                        steps_completed.append("Backup created")
            except asyncio.TimeoutError:
                logger.warning("Backup timed out during toggle")
            except Exception as e:
                logger.warning("Failed to create backup during toggle", [
                    ("Error", str(e)),
                ])

            # Step 4: Hide channels from @everyone
            hidden_count = await self._hide_channels(interaction.guild)
            if hidden_count > 0:
                steps_completed.append(f"Hidden {hidden_count} channels")

            # Step 5: Update presence to show offline
            try:
                async with asyncio.timeout(5.0):
                    await self.bot.change_presence(
                        status=discord.Status.dnd,
                        activity=discord.Activity(
                            type=discord.ActivityType.watching,
                            name="OFFLINE - Disabled"
                        )
                    )
                steps_completed.append("Presence updated")
            except asyncio.TimeoutError:
                logger.warning("Presence update timed out")
            except Exception as e:
                logger.warning("Failed to update presence", [
                    ("Error", str(e)),
                ])

            # Step 6: Update status channel to offline
            try:
                async with asyncio.timeout(5.0):
                    await self.bot.update_status_channel(online=False)
                steps_completed.append("Status updated")
            except asyncio.TimeoutError:
                logger.warning("Status channel update timed out")
            except Exception as e:
                logger.warning("Failed to update status channel", [
                    ("Error", str(e)),
                ])

            # Step 7: Send webhook shutdown alert
            if hasattr(self.bot, 'alert_service') and self.bot.alert_service:
                try:
                    async with asyncio.timeout(5.0):
                        await self.bot.alert_service.send_shutdown_alert()
                    steps_completed.append("Shutdown alert")
                except asyncio.TimeoutError:
                    logger.warning("Shutdown alert timed out")
                except Exception as e:
                    logger.warning("Failed to send shutdown alert", [
                        ("Error", str(e)),
                    ])

            # Build success embed
            embed = discord.Embed(
                title="Bot Disabled",
                description="Bot paused. Use `/toggle on` to resume.\nWebhook monitoring remains active.",
                color=EmbedColors.BAN
            )
            embed.add_field(name="Status", value="`Offline`", inline=True)
            embed.add_field(name="Channels", value=f"`{hidden_count} hidden`", inline=True)
            embed.add_field(
                name="Steps Completed",
                value=", ".join(steps_completed),
                inline=False
            )

            logger.warning("🔴 Bot Toggled OFF (Paused)", [
                ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
                ("Guild", interaction.guild.name if interaction.guild else "DM"),
                ("Channel", getattr(interaction.channel, 'name', 'Unknown')),
                ("Channels Hidden", str(hidden_count)),
                ("Steps", ", ".join(steps_completed)),
            ])

        except Exception as e:
            embed = discord.Embed(
                title="Disable Failed",
                description=f"Error during shutdown: {str(e)[:CONTENT_PREVIEW_LENGTH]}",
                color=EmbedColors.BAN
            )
            embed.add_field(
                name="Steps Completed",
                value=", ".join(steps_completed) if steps_completed else "None",
                inline=False
            )

            logger.error("Toggle OFF Failed", [
                ("Error", str(e)),
                ("Steps Completed", ", ".join(steps_completed)),
            ])

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _enable_bot(self, interaction: discord.Interaction) -> None:
        """Enable the bot and restore functionality."""
        steps_completed: List[str] = []

        try:
            # Step 1: Mark as enabled
            self.bot.disabled = False
            steps_completed.append("Enabled")

            # Step 2: Unhide channels for @everyone
            unhidden_count = await self._unhide_channels(interaction.guild)
            if unhidden_count > 0:
                steps_completed.append(f"Unhidden {unhidden_count} channels")

            # Step 3: Update presence to show online
            try:
                async with asyncio.timeout(5.0):
                    await self.bot.change_presence(
                        status=discord.Status.online,
                        activity=discord.Activity(
                            type=discord.ActivityType.watching,
                            name="Syria"
                        )
                    )
                steps_completed.append("Presence updated")
            except asyncio.TimeoutError:
                logger.warning("Presence update timed out")
            except Exception as e:
                logger.warning("Failed to update presence", [
                    ("Error", str(e)),
                ])

            # Step 4: Update status channel to online
            try:
                async with asyncio.timeout(5.0):
                    await self.bot.update_status_channel(online=True)
                steps_completed.append("Status updated")
            except asyncio.TimeoutError:
                logger.warning("Status channel update timed out")
            except Exception as e:
                logger.warning("Failed to update status channel", [
                    ("Error", str(e)),
                ])

            # Step 5: Send webhook startup alert
            if hasattr(self.bot, 'alert_service') and self.bot.alert_service:
                try:
                    async with asyncio.timeout(5.0):
                        await self.bot.alert_service.send_startup_alert()
                    steps_completed.append("Startup alert")
                except asyncio.TimeoutError:
                    logger.warning("Startup alert timed out")
                except Exception as e:
                    logger.warning("Failed to send startup alert", [
                        ("Error", str(e)),
                    ])

            # Step 6: Restart hourly alerts
            if hasattr(self.bot, 'alert_service') and self.bot.alert_service:
                try:
                    await self.bot.alert_service.start_hourly_alerts()
                    steps_completed.append("Hourly alerts")
                except Exception as e:
                    logger.warning("Failed to start hourly alerts", [
                        ("Error", str(e)),
                    ])

            # Build success embed
            embed = discord.Embed(
                title="Bot Enabled",
                description="Full startup sequence completed successfully.",
                color=EmbedColors.SUCCESS
            )
            embed.add_field(name="Status", value="`Online`", inline=True)
            embed.add_field(name="Channels", value=f"`{unhidden_count} visible`", inline=True)
            embed.add_field(
                name="Steps Completed",
                value=", ".join(steps_completed),
                inline=False
            )

            logger.success("🟢 Bot Toggled ON (Full Startup)", [
                ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
                ("Guild", interaction.guild.name if interaction.guild else "DM"),
                ("Channel", getattr(interaction.channel, 'name', 'Unknown')),
                ("Channels Unhidden", str(unhidden_count)),
                ("Steps", ", ".join(steps_completed)),
            ])

        except Exception as e:
            embed = discord.Embed(
                title="Enable Failed",
                description=f"Error during enable: {str(e)[:CONTENT_PREVIEW_LENGTH]}",
                color=EmbedColors.BAN
            )
            embed.add_field(
                name="Steps Completed",
                value=", ".join(steps_completed) if steps_completed else "None",
                inline=False
            )

            logger.error("Toggle ON Failed", [
                ("Error", str(e)),
                ("Steps Completed", ", ".join(steps_completed)),
            ])

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _hide_channels(self, guild: discord.Guild) -> int:
        """Hide channels from @everyone role."""
        if not guild:
            return 0

        hidden_count = 0
        everyone_role = guild.default_role

        for channel_id in TOGGLE_CHANNEL_IDS:
            try:
                channel = guild.get_channel(channel_id)
                if channel:
                    # Deny view_channel permission for @everyone
                    await channel.set_permissions(
                        everyone_role,
                        view_channel=False,
                        reason="Bot toggled off - hiding channel"
                    )
                    hidden_count += 1
                    logger.info("Channel Hidden", [
                        ("Channel", channel.name),
                        ("ID", str(channel_id)),
                    ])
            except discord.HTTPException as e:
                # Error 350003 = Onboarding channels must be readable by everyone
                if e.code == 350003:
                    logger.info("Skipped Onboarding Channel (Cannot Hide)", [
                        ("Channel ID", str(channel_id)),
                    ])
                else:
                    logger.warning("Failed to hide channel", [
                        ("Channel ID", str(channel_id)),
                        ("Error", str(e)),
                    ])
            except Exception as e:
                logger.warning("Failed to hide channel", [
                    ("Channel ID", str(channel_id)),
                    ("Error", str(e)),
                ])

        return hidden_count

    async def _unhide_channels(self, guild: discord.Guild) -> int:
        """Unhide channels for @everyone role."""
        if not guild:
            return 0

        unhidden_count = 0
        everyone_role = guild.default_role

        for channel_id in TOGGLE_CHANNEL_IDS:
            try:
                channel = guild.get_channel(channel_id)
                if channel:
                    # Reset view_channel permission for @everyone (inherit)
                    await channel.set_permissions(
                        everyone_role,
                        view_channel=None,  # Reset to inherit
                        reason="Bot toggled on - unhiding channel"
                    )
                    unhidden_count += 1
                    logger.info("Channel Unhidden", [
                        ("Channel", channel.name),
                        ("ID", str(channel_id)),
                    ])
            except discord.HTTPException as e:
                # Error 350003 = Onboarding channels (always visible to everyone)
                if e.code == 350003:
                    logger.info("Skipped Onboarding Channel (Already Visible)", [
                        ("Channel ID", str(channel_id)),
                    ])
                else:
                    logger.warning("Failed to unhide channel", [
                        ("Channel ID", str(channel_id)),
                        ("Error", str(e)),
                    ])
            except Exception as e:
                logger.warning("Failed to unhide channel", [
                    ("Channel ID", str(channel_id)),
                    ("Error", str(e)),
                ])

        return unhidden_count


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(ToggleCog(bot))
    logger.tree("Command Loaded", [("Name", "toggle")], emoji="✅")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ToggleCog", "setup"]
