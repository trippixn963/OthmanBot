"""
OthmanBot - Close Command
=========================

Slash command for closing debate threads.

Commands:
- /close - Close a debate thread with a reason

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, NY_TZ, has_debates_management_role
from src.utils import edit_thread_with_retry, get_developer_avatar
from src.views.appeals import AppealButtonView

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

        # Security check: Verify user has Debates Management role
        if not has_debates_management_role(interaction.user):
            logger.warning("/close Command Denied - Missing Role", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.response.send_message(
                "You don't have permission to use this command. "
                "Only users with the Debates Management role can close debates.",
                ephemeral=True
            )
            return

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

        # Validate: Must be in debates forum (check before deferring)
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

        # Validate: Thread not already closed (check name prefix)
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

        # Store original name for logging and embed
        original_name = thread.name

        # Extract the title without the number prefix
        # Format: "13 | Title" -> "Title"
        title_match = re.match(r'^\d+\s*\|\s*(.+)$', thread.name)
        if title_match:
            title = title_match.group(1)
        else:
            # Fallback if no number prefix found
            title = thread.name

        # Build the new name
        new_name = f"[CLOSED] | {title}"
        if len(new_name) > 100:
            new_name = new_name[:97] + "..."

        # Build the public embed FIRST (before any slow operations)
        now = datetime.now(NY_TZ)
        embed = discord.Embed(
            title="🔒 Debate Closed",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        # Truncate fields to stay within Discord's embed field limits (1024 chars)
        debate_display = title[:100] + "..." if len(title) > 100 else title
        reason_display = reason[:1000] + "..." if len(reason) > 1000 else reason

        embed.add_field(name="Debate", value=debate_display, inline=False)
        embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(now.timestamp())}:f>", inline=True)
        embed.add_field(name="Reason", value=reason_display, inline=False)

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        # Get the debate owner from the starter message before sending response
        # We need owner_id for the appeal button
        owner = None
        try:
            starter_message = await thread.fetch_message(thread.id)
            if starter_message and not starter_message.author.bot:
                owner = starter_message.author
        except Exception as e:
            logger.warning("/close Could Not Find Starter Message", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)),
            ])

        # Create appeal button view if owner was found
        view = None
        if owner:
            view = AppealButtonView(
                action_type="close",
                action_id=thread.id,
                user_id=owner.id,
            )

        # Send the embed with appeal button
        await interaction.response.send_message(embed=embed, view=view)

        # Do all slow operations in background (thread rename, archive, lock, logging, renumbering, owner DM)
        asyncio.create_task(self._close_thread_background(
            thread=thread,
            new_name=new_name,
            original_name=original_name,
            reason=reason,
            closed_by=interaction.user,
            owner=owner,
        ))

    async def _close_thread_background(
        self,
        thread: discord.Thread,
        new_name: str,
        original_name: str,
        reason: str,
        closed_by: discord.User,
        owner: Optional[discord.User] = None,
    ) -> None:
        """Handle all slow close operations in background."""
        try:
            # Rename the thread
            try:
                await edit_thread_with_retry(thread, name=new_name)
            except Exception as e:
                logger.warning("/close Thread Rename Failed", [
                    ("Thread", f"{original_name} ({thread.id})"),
                    ("Error", str(e)),
                ])

            # Lock the thread (don't archive - let Discord auto-archive based on forum settings)
            try:
                await edit_thread_with_retry(thread, locked=True)
            except Exception as e:
                logger.warning("/close Lock Failed", [
                    ("Thread", f"{new_name} ({thread.id})"),
                    ("Error", str(e)),
                ])

            # Log success
            logger.tree("Debate Closed", [
                ("Thread", f"{original_name} ({thread.id})"),
                ("Closed By", f"{closed_by.name} ({closed_by.id})"),
                ("Owner", f"{owner.name} ({owner.id})" if owner else "Unknown"),
                ("Reason", reason),
            ], emoji="🔒")

            # Log to webhook
            try:
                if self.bot.interaction_logger:
                    await self.bot.interaction_logger.log_debate_closed(
                        thread=thread,
                        closed_by=closed_by,
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
                            closed_by=closed_by,
                            owner=owner,
                            original_name=original_name,
                            reason=reason
                        )
                except Exception as e:
                    logger.warning("Failed to log debate close to case system", [
                        ("Error", str(e)),
                    ])

            # Send DM notification to owner with appeal button
            if owner:
                try:
                    await self._send_close_notification_dm(
                        owner=owner,
                        closed_by=closed_by,
                        thread=thread,
                        original_name=original_name,
                        reason=reason,
                    )
                except Exception as e:
                    logger.warning("Failed to send close notification DM", [
                        ("Owner", f"{owner.name} ({owner.id})"),
                        ("Error", str(e)),
                    ])

        except Exception as e:
            logger.error("/close Background Task Failed", [
                ("Thread", f"{original_name} ({thread.id})"),
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

    async def _send_close_notification_dm(
        self,
        owner: discord.User,
        closed_by: discord.User,
        thread: discord.Thread,
        original_name: str,
        reason: str,
    ) -> bool:
        """
        Send DM notification to thread owner when their debate is closed.

        Args:
            owner: The debate thread owner
            closed_by: The moderator who closed it
            thread: The closed thread
            original_name: Original thread name before [CLOSED] prefix
            reason: Reason for closing

        Returns:
            True if DM sent successfully, False otherwise
        """
        try:
            now = datetime.now(NY_TZ)
            embed = discord.Embed(
                title="Your Debate Thread Was Closed",
                description=(
                    "A moderator has closed your debate thread.\n"
                    "Please review the details below."
                ),
                color=discord.Color.red(),
                timestamp=now,
            )

            embed.set_thumbnail(url=closed_by.display_avatar.url)

            # Extract title without number prefix
            title = original_name
            title_match = re.match(r'^\d+\s*\|\s*(.+)$', original_name)
            if title_match:
                title = title_match.group(1)

            embed.add_field(
                name="Debate",
                value=title[:100] + "..." if len(title) > 100 else title,
                inline=False,
            )
            embed.add_field(
                name="Closed By",
                value=closed_by.display_name,
                inline=True,
            )
            embed.add_field(
                name="Time",
                value=f"<t:{int(now.timestamp())}:f>",
                inline=True,
            )
            embed.add_field(
                name="Reason",
                value=reason[:1000] + "..." if len(reason) > 1000 else reason,
                inline=False,
            )

            embed.set_footer(
                text="Syria Discord Server | Debates System",
                icon_url=self.bot.user.display_avatar.url if self.bot.user else None,
            )

            # Create appeal button view
            appeal_view = AppealButtonView(
                action_type="close",
                action_id=thread.id,
                user_id=owner.id,
            )

            # Send DM with appeal button
            await owner.send(embed=embed, view=appeal_view)

            logger.info("Close Notification DM Sent", [
                ("Owner", f"{owner.name} ({owner.id})"),
                ("Thread", f"{original_name} ({thread.id})"),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Close Notification DM Failed - DMs Disabled", [
                ("Owner", f"{owner.name} ({owner.id})"),
            ])
            return False

        except discord.HTTPException as e:
            logger.warning("Close Notification DM Failed - HTTP Error", [
                ("Owner", f"{owner.name} ({owner.id})"),
                ("Error", str(e)),
            ])
            return False


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
