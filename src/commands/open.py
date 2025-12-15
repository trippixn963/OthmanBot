"""
OthmanBot - Open Command
========================

Slash command for reopening closed debate threads.

Commands:
- /open - Reopen a closed debate thread with a reason

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, NY_TZ, has_debates_management_role
from src.utils import edit_thread_with_retry, get_developer_avatar

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

        # Security check: Verify user has Debates Management role
        if not has_debates_management_role(interaction.user):
            logger.warning("/open Command Denied - Missing Role", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.response.send_message(
                "You don't have permission to use this command. "
                "Only users with the Debates Management role can reopen debates.",
                ephemeral=True
            )
            return

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
                "This debate is not closed. Use /close first.",
                ephemeral=True
            )
            return

        # Store original name for logging
        original_name = thread.name

        # Get the debate owner to check for protection
        owner = None
        try:
            starter_message = await thread.fetch_message(thread.id)
            if starter_message and not starter_message.author.bot:
                owner = starter_message.author
        except Exception as e:
            logger.warning("/open Could Not Find Starter Message", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)),
            ])

        # Protect Debates Management role members (only developer can reopen their threads)
        from src.core.config import DEVELOPER_ID, DEBATES_MANAGEMENT_ROLE_ID
        if owner and DEBATES_MANAGEMENT_ROLE_ID and interaction.user.id != DEVELOPER_ID:
            # Check if owner is a member with Debates Management role
            owner_member = interaction.guild.get_member(owner.id) if interaction.guild else None
            if owner_member and any(role.id == DEBATES_MANAGEMENT_ROLE_ID for role in owner_member.roles):
                logger.warning("/open Command Rejected - Protected User", [
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Thread Owner", f"{owner.name} ({owner.id})"),
                    ("Thread", f"{thread.name} ({thread.id})"),
                    ("Reason", "Owner has Debates Management role"),
                ])
                await interaction.response.send_message(
                    "You cannot reopen a debate owned by a member of the Debates Management team. "
                    "Only the developer can do this.",
                    ephemeral=True
                )
                return

        # Extract the title from the closed thread name
        # Format: [CLOSED] | Title -> Title
        title = thread.name
        if title.startswith("[CLOSED] | "):
            title = title[11:]  # Remove "[CLOSED] | "
        elif title.startswith("[CLOSED]"):
            title = title[8:].lstrip(" |")  # Handle variations

        # Handle legacy format where number was kept: "13 | Title" -> "Title"
        legacy_match = re.match(r'^\d+\s*\|\s*(.+)$', title)
        if legacy_match:
            title = legacy_match.group(1)

        # Get the next debate number from the database
        next_num = 1
        if self.bot.debates_service and self.bot.debates_service.db:
            next_num = self.bot.debates_service.db.get_next_debate_number()

        # Rename thread with new number: N | Title
        new_name = f"{next_num} | {title}"
        if len(new_name) > 100:
            new_name = new_name[:97] + "..."

        # Build the public embed (no slow operations before response)
        now = datetime.now(NY_TZ)
        embed = discord.Embed(
            title="🔓 Debate Reopened",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        debate_display = new_name[:100] + "..." if len(new_name) > 100 else new_name
        reason_display = reason[:1000] + "..." if len(reason) > 1000 else reason

        embed.add_field(name="Debate", value=debate_display, inline=False)
        embed.add_field(name="Reopened By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(now.timestamp())}:f>", inline=True)
        embed.add_field(name="Reason", value=reason_display, inline=False)

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        # Send the embed
        await interaction.response.send_message(embed=embed)

        # Do all slow operations in background
        asyncio.create_task(self._open_thread_background(
            thread=thread,
            new_name=new_name,
            original_name=original_name,
            reason=reason,
            reopened_by=interaction.user
        ))

    async def _open_thread_background(
        self,
        thread: discord.Thread,
        new_name: str,
        original_name: str,
        reason: str,
        reopened_by: discord.User
    ) -> None:
        """Handle all slow open operations in background."""
        try:
            # Get the debate owner from the starter message
            owner = None
            try:
                starter_message = await thread.fetch_message(thread.id)
                if starter_message and not starter_message.author.bot:
                    owner = starter_message.author
            except Exception as e:
                logger.warning("/open Could Not Find Starter Message", [
                    ("Thread ID", str(thread.id)),
                    ("Error", str(e)),
                ])

            # Rename and unlock the thread
            try:
                await edit_thread_with_retry(thread, name=new_name, archived=False, locked=False)
            except Exception as e:
                logger.warning("/open Thread Edit Failed", [
                    ("Thread", f"{original_name} ({thread.id})"),
                    ("Error", str(e)),
                ])

            # Log success
            logger.tree("Debate Reopened", [
                ("Thread", f"{new_name} ({thread.id})"),
                ("Reopened By", f"{reopened_by.name} ({reopened_by.id})"),
                ("Owner", f"{owner.name} ({owner.id})" if owner else "Unknown"),
                ("Reason", reason),
            ], emoji="🔓")

            # Log to webhook
            try:
                if self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_debate_reopened(
                        thread=thread,
                        reopened_by=reopened_by,
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
                            reopened_by=reopened_by,
                            owner=owner,
                            original_name=original_name,
                            new_name=new_name,
                            reason=reason
                        )
                except Exception as e:
                    logger.warning("Failed to log debate reopen to case system", [
                        ("Error", str(e)),
                    ])

        except Exception as e:
            logger.error("/open Background Task Failed", [
                ("Thread", f"{original_name} ({thread.id})"),
                ("Error Type", type(e).__name__),
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
