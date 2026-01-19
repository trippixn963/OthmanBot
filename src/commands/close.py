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
from src.core.config import DEBATES_FORUM_ID, NY_TZ, has_debates_management_role, EmbedColors, EmbedIcons
from src.utils import edit_thread_with_retry, get_ordinal
from src.utils.footer import set_footer
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
            ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Reason", reason[:50] + "..." if len(reason) > 50 else reason),
        ])

        # Security check: Verify user has Debates Management role
        if not has_debates_management_role(interaction.user):
            logger.warning("/close Command Denied - Missing Role", [
                ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
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
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
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
            title=f"{EmbedIcons.CLOSE} Debate Closed",
            color=EmbedColors.CLOSE
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        # Truncate fields to stay within Discord's embed field limits (1024 chars)
        debate_display = title[:100] + "..." if len(title) > 100 else title
        reason_display = reason[:1000] + "..." if len(reason) > 1000 else reason

        embed.add_field(name="Debate", value=debate_display, inline=False)
        embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(now.timestamp())}:f>", inline=True)
        embed.add_field(name="Reason", value=reason_display, inline=False)

        set_footer(embed)

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

        # Protect Debates Management role members (only developer can close their threads)
        from src.core.config import DEVELOPER_ID, DEBATES_MANAGEMENT_ROLE_ID
        if owner and DEBATES_MANAGEMENT_ROLE_ID and interaction.user.id != DEVELOPER_ID:
            # Check if owner is a member with Debates Management role
            owner_member = interaction.guild.get_member(owner.id) if interaction.guild else None
            if owner_member and any(role.id == DEBATES_MANAGEMENT_ROLE_ID for role in owner_member.roles):
                logger.warning("/close Command Rejected - Protected User", [
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
                    ("ID", str(interaction.user.id)),
                    ("Thread Owner", f"{owner.name} ({owner.display_name})"),
                    ("ID", str(owner.id)),
                    ("Thread", f"{thread.name} ({thread.id})"),
                    ("Reason", "Owner has Debates Management role"),
                ])
                await interaction.response.send_message(
                    "You cannot close a debate owned by a member of the Debates Management team. "
                    "Only the developer can do this.",
                    ephemeral=True
                )
                return

        # Create appeal button view if owner was found
        view = None
        if owner:
            view = AppealButtonView(
                action_type="close",
                action_id=thread.id,
                user_id=owner.id,
            )

        # Send the embed with appeal button (only pass view if not None)
        if view:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)

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
            rename_success = await edit_thread_with_retry(thread, name=new_name)
            if rename_success:
                logger.tree("Thread Renamed", [
                    ("Thread ID", str(thread.id)),
                    ("New Name", new_name[:50]),
                ], emoji="✏️")
            else:
                logger.tree("Thread Rename Failed", [
                    ("Thread", f"{original_name} ({thread.id})"),
                    ("Target Name", new_name[:50]),
                ], emoji="⚠️")

            # Lock the thread (don't archive - let Discord auto-archive based on forum settings)
            lock_success = await edit_thread_with_retry(thread, locked=True)
            if lock_success:
                logger.tree("Thread Locked", [
                    ("Thread ID", str(thread.id)),
                ], emoji="🔒")
            else:
                logger.tree("Thread Lock Failed", [
                    ("Thread", f"{new_name} ({thread.id})"),
                ], emoji="⚠️")

            # Log success
            logger.tree("Debate Closed", [
                ("Thread", f"{original_name} ({thread.id})"),
                ("Renamed", "Yes" if rename_success else "No"),
                ("Locked", "Yes" if lock_success else "No"),
                ("Closed By", f"{closed_by.name} ({closed_by.display_name})"),
                ("ID", str(closed_by.id)),
                ("Owner", f"{owner.name} ({owner.display_name})" if owner else "Unknown"),
                ("ID", str(owner.id) if owner else "Unknown"),
                ("Reason", reason[:50]),
            ], emoji="✅" if rename_success and lock_success else "⚠️")

            # Log to case system (creates case for debate owner)
            if owner:
                if self.bot.case_log_service:
                    try:
                        await self.bot.case_log_service.log_debate_closed(
                            thread=thread,
                            closed_by=closed_by,
                            owner=owner,
                            original_name=original_name,
                            reason=reason
                        )
                        logger.debug("Case Log Updated (Debate Closed)", [
                            ("Thread ID", str(thread.id)),
                            ("Owner", f"{owner.name} ({owner.display_name})"),
                            ("ID", str(owner.id)),
                        ])
                    except Exception as e:
                        logger.tree("Failed to Update Case Log (Debate Closed)", [
                            ("Thread ID", str(thread.id)),
                            ("Owner", f"{owner.name} ({owner.display_name})"),
                            ("ID", str(owner.id)),
                            ("Error", str(e)[:80]),
                        ], emoji="⚠️")
                else:
                    logger.debug("Case Log Service Not Available", [
                        ("Thread ID", str(thread.id)),
                        ("Event", "Debate Closed"),
                    ])
            else:
                logger.debug("No Owner Found for Case Log", [
                    ("Thread ID", str(thread.id)),
                    ("Event", "Debate Closed"),
                ])

            # Record to closure history and send DM notification
            past_closure_count = 0
            if owner:
                # Add to closure history
                if self.bot.debates_service and self.bot.debates_service.db:
                    try:
                        await asyncio.to_thread(
                            self.bot.debates_service.db.add_to_closure_history,
                            thread.id,
                            original_name,
                            closed_by.id,
                            reason,
                            owner.id
                        )
                        # Get count (subtract 1 since we just added this one)
                        closure_count = await asyncio.to_thread(self.bot.debates_service.db.get_user_closure_count, owner.id)
                        past_closure_count = max(0, closure_count - 1)
                        logger.debug("Closure History Recorded", [
                            ("Thread ID", str(thread.id)),
                            ("Owner", f"{owner.name} ({owner.display_name})"),
                            ("ID", str(owner.id)),
                            ("Past Closures", str(past_closure_count)),
                        ])
                    except Exception as e:
                        logger.tree("Failed to Record Closure History", [
                            ("Thread ID", str(thread.id)),
                            ("Owner", f"{owner.name} ({owner.display_name})"),
                            ("ID", str(owner.id)),
                            ("Error", str(e)[:80]),
                        ], emoji="⚠️")
                else:
                    logger.debug("Debates Service Not Available for Closure History", [
                        ("Thread ID", str(thread.id)),
                    ])

                # Send DM notification to owner with appeal button
                try:
                    await self._send_close_notification_dm(
                        owner=owner,
                        closed_by=closed_by,
                        thread=thread,
                        original_name=original_name,
                        reason=reason,
                        past_closure_count=past_closure_count,
                    )
                except Exception as e:
                    logger.warning("Failed to send close notification DM", [
                        ("Owner", f"{owner.name} ({owner.display_name})"),
                        ("Owner ID", str(owner.id)),
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
        past_closure_count: int = 0,
    ) -> bool:
        """
        Send DM notification to thread owner when their debate is closed.

        Args:
            owner: The debate thread owner
            closed_by: The moderator who closed it
            thread: The closed thread
            original_name: Original thread name before [CLOSED] prefix
            reason: Reason for closing
            past_closure_count: Number of previous closures for this user

        Returns:
            True if DM sent successfully, False otherwise
        """
        try:
            now = datetime.now(NY_TZ)
            embed = discord.Embed(
                title=f"{EmbedIcons.CLOSE} Your Debate Thread Was Closed",
                description=(
                    "A moderator has closed your debate thread.\n"
                    "Please review the details below."
                ),
                color=EmbedColors.CLOSE,
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
                name="Thread",
                value=f"<#{thread.id}>",
                inline=True,
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

            # Past closure history (only show if not first closure)
            if past_closure_count > 0:
                ordinal = get_ordinal(past_closure_count + 1)
                embed.add_field(
                    name=f"{EmbedIcons.WARNING} Closure History",
                    value=f"This is your **{ordinal}** debate closure.",
                    inline=True,
                )

                # Add consequence warning for repeat closures
                if past_closure_count == 1:
                    # 2nd closure
                    consequence_warning = (
                        "This is your second debate closure. Please review the debate rules "
                        "to avoid future closures. Continued violations may result in "
                        "temporary bans from creating debates."
                    )
                elif past_closure_count == 2:
                    # 3rd closure
                    consequence_warning = (
                        "This is your third debate closure. Further violations will likely "
                        "result in a temporary ban from debates."
                    )
                else:
                    # 4th+ closure
                    consequence_warning = (
                        "You have had multiple debates closed. Any further violations "
                        "may result in a ban from debates."
                    )

                embed.add_field(
                    name=f"{EmbedIcons.ALERT} Warning",
                    value=consequence_warning,
                    inline=False
                )

            # Server join date (if owner is a Member in any guild)
            # Try to get member object from the thread's guild
            try:
                if thread.guild:
                    member = thread.guild.get_member(owner.id)
                    if member and member.joined_at:
                        embed.add_field(
                            name="Member Since",
                            value=f"<t:{int(member.joined_at.timestamp())}:D>",
                            inline=True,
                        )
            except Exception as e:
                logger.debug("Could Not Get Member Join Date For Close DM", [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)[:50]),
                ])

            # What's Next guidance
            embed.add_field(
                name="What's Next?",
                value="You may appeal this decision using the button below.",
                inline=False,
            )

            set_footer(embed)

            # Create appeal button view
            appeal_view = AppealButtonView(
                action_type="close",
                action_id=thread.id,
                user_id=owner.id,
            )

            # Send DM with appeal button
            await owner.send(embed=embed, view=appeal_view)

            logger.info("Close Notification DM Sent", [
                ("User", f"{owner.name} ({owner.display_name})"),
                ("ID", str(owner.id)),
                ("Thread", f"{original_name} ({thread.id})"),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Close Notification DM Failed - DMs Disabled", [
                ("User", f"{owner.name} ({owner.display_name})"),
                ("ID", str(owner.id)),
            ])
            return False

        except discord.HTTPException as e:
            logger.warning("Close Notification DM Failed - HTTP Error", [
                ("User", f"{owner.name} ({owner.display_name})"),
                ("ID", str(owner.id)),
                ("Error", str(e)),
            ])
            return False


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(CloseCog(bot))
    logger.tree("Command Loaded", [("Name", "close")], emoji="✅")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CloseCog", "setup"]
