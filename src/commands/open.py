"""
OthmanBot - Open Command
========================

Slash command for reopening closed debate threads.

Commands:
- /open - Reopen a closed debate thread with a reason

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, NY_TZ
from src.utils import get_developer_avatar, edit_thread_with_retry

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Open Cog
# =============================================================================

class OpenCog(commands.Cog):
    """Cog for /open command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @app_commands.command(name="open", description="Reopen a closed debate thread")
    @app_commands.describe(
        reason="Reason for reopening this debate (required)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def open(
        self,
        interaction: discord.Interaction,
        reason: str
    ) -> None:
        """Reopen a closed debate thread with a reason."""
        # Log command invocation
        logger.info("/open Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Reason", reason[:50] + "..." if len(reason) > 50 else reason),
        ])

        # Validate: Must be used in a thread
        if not isinstance(interaction.channel, discord.Thread):
            logger.warning("/open Command Failed - Not A Thread", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Channel Type", type(interaction.channel).__name__),
            ])
            await interaction.response.send_message(
                "This command can only be used inside a debate thread.",
                ephemeral=True
            )
            return

        thread = interaction.channel

        # Validate: Must be in debates forum
        if thread.parent_id != DEBATES_FORUM_ID:
            logger.warning("/open Command Failed - Not In Debates Forum", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
                ("Parent ID", str(thread.parent_id)),
                ("Expected", str(DEBATES_FORUM_ID)),
            ])
            await interaction.response.send_message(
                "This command can only be used in debate threads.",
                ephemeral=True
            )
            return

        # Validate: Thread must be closed (has [CLOSED] prefix)
        if not thread.name.startswith("[CLOSED]"):
            logger.warning("/open Command Failed - Not Closed", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
            ])
            await interaction.response.send_message(
                "This debate is not closed.",
                ephemeral=True
            )
            return

        # Get the debate owner from the starter message
        owner = None
        try:
            # For forum threads, the thread ID is also the starter message ID
            starter_message = await thread.fetch_message(thread.id)
            if starter_message and not starter_message.author.bot:
                owner = starter_message.author
        except discord.NotFound:
            logger.warning("/open Could Not Find Starter Message", [
                ("Thread ID", str(thread.id)),
            ])
        except discord.HTTPException as e:
            logger.warning("/open Failed To Fetch Starter Message", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)),
            ])

        # Store original name for logging
        original_name = thread.name

        # Rename thread: Remove [CLOSED] | prefix
        # Format: [CLOSED] | N | Title -> N | Title
        new_name = thread.name
        if new_name.startswith("[CLOSED] | "):
            new_name = new_name[11:]  # Remove "[CLOSED] | "
        elif new_name.startswith("[CLOSED]"):
            new_name = new_name[8:].lstrip(" |")  # Handle variations

        # Rename, unarchive, and unlock the thread
        rename_success = await edit_thread_with_retry(
            thread,
            name=new_name,
            archived=False,
            locked=False
        )

        if not rename_success:
            logger.error("/open Command Failed - Thread Edit Failed", [
                ("Thread", f"{thread.name} ({thread.id})"),
            ])
            await interaction.response.send_message(
                "Failed to reopen the debate. Please try again.",
                ephemeral=True
            )
            return

        # Build the public embed
        now = datetime.now(NY_TZ)
        embed = discord.Embed(
            title="🔓 Debate Reopened",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        # Truncate fields to stay within Discord's embed field limits (1024 chars)
        debate_display = new_name[:100] + "..." if len(new_name) > 100 else new_name
        reason_display = reason[:1000] + "..." if len(reason) > 1000 else reason

        embed.add_field(name="Debate", value=debate_display, inline=False)
        embed.add_field(name="Reopened By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(now.timestamp())}:t> EST", inline=True)
        embed.add_field(name="Reason", value=reason_display, inline=False)

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        # Send the embed
        await interaction.response.send_message(embed=embed)

        # Log success
        logger.tree("Debate Reopened", [
            ("Thread", f"{new_name} ({thread.id})"),
            ("Reopened By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Owner", f"{owner.name} ({owner.id})" if owner else "Unknown"),
            ("Reason", reason),
        ], emoji="🔓")

        # Log to webhook
        try:
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_debate_reopened(
                    thread=thread,
                    reopened_by=interaction.user,
                    owner=owner,
                    original_name=original_name,
                    new_name=new_name,
                    reason=reason
                )
        except Exception as e:
            logger.warning("Failed to log debate reopen to webhook", [
                ("Error", str(e)),
            ])

        # Log to case system (if owner has a case)
        if owner:
            try:
                if self.bot.case_log_service:
                    await self.bot.case_log_service.log_debate_reopened(
                        thread=thread,
                        reopened_by=interaction.user,
                        owner=owner,
                        original_name=original_name,
                        new_name=new_name,
                        reason=reason
                    )
            except Exception as e:
                logger.warning("Failed to log debate reopen to case system", [
                    ("Error", str(e)),
                ])


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(OpenCog(bot))
    logger.info("Open Cog Loaded", [
        ("Commands", "/open"),
    ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["OpenCog", "setup"]
