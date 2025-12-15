"""
OthmanBot - Close Command
=========================

Slash command for closing debate threads.

Commands:
- /close - Close a debate thread with a reason

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
# Close Cog
# =============================================================================

class CloseCog(commands.Cog):
    """Cog for /close command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @app_commands.command(name="close", description="Close a debate thread")
    @app_commands.describe(
        reason="Reason for closing this debate (required)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def close(
        self,
        interaction: discord.Interaction,
        reason: str
    ) -> None:
        """Close a debate thread with a reason."""
        # Log command invocation
        logger.info("/close Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Reason", reason[:50] + "..." if len(reason) > 50 else reason),
        ])

        # Validate: Must be used in a thread
        if not isinstance(interaction.channel, discord.Thread):
            logger.warning("/close Command Failed - Not A Thread", [
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
            logger.warning("/close Command Failed - Not In Debates Forum", [
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

        # Validate: Thread not already closed
        if thread.name.startswith("[CLOSED]"):
            logger.warning("/close Command Failed - Already Closed", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
            ])
            await interaction.response.send_message(
                "This debate is already closed.",
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
            logger.warning("/close Could Not Find Starter Message", [
                ("Thread ID", str(thread.id)),
            ])
        except discord.HTTPException as e:
            logger.warning("/close Failed To Fetch Starter Message", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)),
            ])

        # Store original name for logging
        original_name = thread.name

        # Rename thread: [CLOSED] | N | Title
        new_name = f"[CLOSED] | {thread.name}"
        if len(new_name) > 100:
            new_name = new_name[:97] + "..."

        # Rename, archive, and lock the thread
        rename_success = await edit_thread_with_retry(
            thread,
            name=new_name,
            archived=True,
            locked=True
        )

        if not rename_success:
            logger.error("/close Command Failed - Thread Edit Failed", [
                ("Thread", f"{thread.name} ({thread.id})"),
            ])
            await interaction.response.send_message(
                "Failed to close the debate. Please try again.",
                ephemeral=True
            )
            return

        # Build the public embed
        now = datetime.now(NY_TZ)
        embed = discord.Embed(
            title="🔒 Debate Closed",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        # Truncate fields to stay within Discord's embed field limits (1024 chars)
        debate_display = original_name[:100] + "..." if len(original_name) > 100 else original_name
        reason_display = reason[:1000] + "..." if len(reason) > 1000 else reason

        embed.add_field(name="Debate", value=debate_display, inline=False)
        embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(now.timestamp())}:t> EST", inline=True)
        embed.add_field(name="Reason", value=reason_display, inline=False)

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        # Send the embed
        await interaction.response.send_message(embed=embed)

        # Log success
        logger.tree("Debate Closed", [
            ("Thread", f"{original_name} ({thread.id})"),
            ("Closed By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Owner", f"{owner.name} ({owner.id})" if owner else "Unknown"),
            ("Reason", reason),
        ], emoji="🔒")

        # Log to webhook
        try:
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_debate_closed(
                    thread=thread,
                    closed_by=interaction.user,
                    owner=owner,
                    original_name=original_name,
                    reason=reason
                )
        except Exception as e:
            logger.warning("Failed to log debate close to webhook", [
                ("Error", str(e)),
            ])

        # Log to case system (creates case for debate owner)
        if owner:
            try:
                if self.bot.case_log_service:
                    await self.bot.case_log_service.log_debate_closed(
                        thread=thread,
                        closed_by=interaction.user,
                        owner=owner,
                        original_name=original_name,
                        reason=reason
                    )
            except Exception as e:
                logger.warning("Failed to log debate close to case system", [
                    ("Error", str(e)),
                ])


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(CloseCog(bot))
    logger.info("Close Cog Loaded", [
        ("Commands", "/close"),
    ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CloseCog", "setup"]
