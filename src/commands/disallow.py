"""
OthmanBot - Disallow Command
============================

Slash command for banning users from debate threads.

Commands:
- /disallow - Ban a user from a debate thread with optional duration

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import (
    DEBATES_FORUM_ID, NY_TZ, BATCH_PROCESSING_DELAY, REACTION_DELAY,
    DISCORD_API_DELAY, DISCORD_AUTOCOMPLETE_LIMIT, has_debates_management_role, EmbedColors
)
from src.core.colors import EmbedIcons
from src.utils.discord_rate_limit import log_http_error
from src.utils import remove_reaction_safe
from src.utils.footer import set_footer
from src.utils.duration import parse_duration, format_duration
from src.utils.autocomplete import thread_id_autocomplete, duration_autocomplete
from src.views.appeals import AppealButtonView

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Disallow Cog
# =============================================================================

class DisallowCog(commands.Cog):
    """Cog for /disallow command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @app_commands.command(name="disallow", description="Ban a user from a debate thread")
    @app_commands.describe(
        user="User to ban from debates",
        thread_id="Thread ID to ban from (use 'all' for all debates)",
        duration="Ban duration (e.g., 1h, 1d, 1w, 1mo, permanent)",
        reason="Reason for the ban (optional, will be asked in case thread if not provided)"
    )
    @app_commands.autocomplete(thread_id=thread_id_autocomplete, duration=duration_autocomplete)
    @app_commands.default_permissions(manage_messages=True)
    async def disallow(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        thread_id: str,
        duration: str,
        reason: str = None
    ) -> None:
        """Ban a user from a specific debate thread."""
        # Log command invocation
        logger.info("/disallow Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Target User", f"{user.name} ({user.id})"),
            ("Thread ID Param", thread_id),
            ("Duration", duration),
        ])

        # Security check: Verify user has Debates Management role
        if not has_debates_management_role(interaction.user):
            logger.warning("/disallow Command Denied - Missing Role", [
                ("User", f"{interaction.user.name} ({interaction.user.display_name})"),
                ("ID", str(interaction.user.id)),
            ])
            await interaction.response.send_message(
                "You don't have permission to use this command. "
                "Only users with the Debates Management role can ban users from debates.",
                ephemeral=True
            )
            return

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/disallow Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                ("Reason", "Debates service not initialized"),
            ])
            await interaction.response.send_message(
                "Debates system is not available.",
                ephemeral=True
            )
            return

        # Prevent self-ban
        if user.id == interaction.user.id:
            logger.warning("/disallow Command Rejected - Self-Ban Attempt", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                ("Reason", "User attempted to ban themselves"),
            ])
            await interaction.response.send_message(
                "You cannot ban yourself from debates.",
                ephemeral=True
            )
            return

        # Protect Debates Management role members (only developer can ban them)
        from src.core.config import DEVELOPER_ID, DEBATES_MANAGEMENT_ROLE_ID
        if DEBATES_MANAGEMENT_ROLE_ID and interaction.user.id != DEVELOPER_ID:
            if any(role.id == DEBATES_MANAGEMENT_ROLE_ID for role in user.roles):
                logger.warning("/disallow Command Rejected - Protected User", [
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                    ("Target User", f"{user.name} ({user.id})"),
                    ("Reason", "Target has Debates Management role"),
                ])
                await interaction.response.send_message(
                    "You cannot ban a member of the Debates Management team. "
                    "Only the developer can do this.",
                    ephemeral=True
                )
                return

        # Parse thread_id (required, must be a number or 'all')
        if thread_id.lower() == "all":
            target_thread_id = None
            scope = "all debates"
        else:
            try:
                target_thread_id = int(thread_id)
                scope = f"thread `{target_thread_id}`"
            except ValueError:
                logger.warning("/disallow Command Failed - Invalid Thread ID", [
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

        # Parse duration
        try:
            duration_td = parse_duration(duration)
            duration_display = format_duration(duration_td)
        except ValueError as e:
            logger.warning("/disallow Command Failed - Invalid Duration", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                ("Invalid Duration", duration),
                ("Error", str(e)),
            ])
            await interaction.response.send_message(
                f"Invalid duration format: `{duration}`\n\n"
                "Valid formats: `1m`, `1h`, `1d`, `1w`, `1mo`, `permanent`",
                ephemeral=True
            )
            return

        if duration_td is not None:
            expires_at = datetime.now(NY_TZ) + duration_td
            # Convert to UTC for SQLite storage (matches datetime('now') format)
            expires_at_utc = expires_at.astimezone(timezone.utc)
            expires_at_str = expires_at_utc.strftime("%Y-%m-%d %H:%M:%S")
        else:
            expires_at = None
            expires_at_str = None

        # Add the ban
        success = self.bot.debates_service.db.add_debate_ban(
            user_id=user.id,
            thread_id=target_thread_id,
            banned_by=interaction.user.id,
            expires_at=expires_at_str
        )

        if success:
            logger.tree("User Banned From Debates", [
                ("Banned User", f"{user.name} ({user.id})"),
                ("Banned By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Scope", scope),
                ("Thread ID", str(target_thread_id) if target_thread_id else "Global"),
                ("Duration", duration_display),
                ("Expires At", expires_at_str if expires_at_str else "Never"),
            ], emoji="🚫")

            # Create public embed for the ban
            embed = discord.Embed(
                title="User Banned from Debates",
                description=(
                    f"**{user.mention}** has been banned from {scope}.\n\n"
                    f"They can no longer post messages there."
                ),
                color=EmbedColors.BAN
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Banned By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Scope", value=scope.title(), inline=True)
            embed.add_field(name="Duration", value=duration_display, inline=True)

            if expires_at:
                embed.add_field(
                    name="Expires",
                    value=f"<t:{int(expires_at.timestamp())}:R>",
                    inline=True
                )

            set_footer(embed)

            # Create appeal button view for the banned user
            appeal_view = AppealButtonView(
                action_type="disallow",
                action_id=user.id,
                user_id=user.id,
            )

            await interaction.response.send_message(embed=embed, view=appeal_view)

            # Log to case system (for mods server forum)
            try:
                if self.bot.case_log_service:
                    await self.bot.case_log_service.log_ban(
                        user=user,
                        banned_by=interaction.user,
                        scope=scope,
                        duration=duration_display,
                        thread_id=target_thread_id,
                        reason=reason
                    )
            except Exception as e:
                logger.warning("Failed to log to case system", [
                    ("Error", str(e)),
                ])

            # Send DM notification to the banned user
            try:
                if self.bot.ban_notifier:
                    # Get past ban count for this user (excluding the current one)
                    past_ban_count = 0
                    if self.bot.debates_service and self.bot.debates_service.db:
                        # Count is already +1 from the ban we just added, so subtract 1
                        past_ban_count = max(0, self.bot.debates_service.db.get_user_ban_count(user.id) - 1)

                    await self.bot.ban_notifier.notify_ban(
                        user=user,
                        banned_by=interaction.user,
                        scope=scope,
                        duration=duration_display,
                        expires_at=expires_at,
                        thread_id=target_thread_id,
                        reason=reason,
                        past_ban_count=past_ban_count
                    )
            except Exception as e:
                logger.warning("Failed to send ban notification DM", [
                    ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                    ("Error", str(e)),
                ])

            # Remove user's reactions in background (so they must re-acknowledge rules when unbanned)
            asyncio.create_task(self._remove_user_reactions(user, target_thread_id))
        else:
            logger.info("/disallow Command - User Already Banned", [
                ("Target User", f"{user.name} ({user.id})"),
                ("Invoked By", f"{interaction.user.name} ({interaction.user.display_name})"),
            ("ID", str(interaction.user.id)),
                ("Scope", scope),
            ])
            await interaction.response.send_message(
                f"**{user.display_name}** is already banned from {scope}.",
                ephemeral=True
            )

    async def _remove_user_reactions(
        self,
        user: discord.Member,
        target_thread_id: int | None
    ) -> None:
        """Remove user's reactions from debate threads in background.

        DESIGN: Always fetches threads via API to avoid cache issues.
        - For specific thread: Fetch directly by ID
        - For all threads: Use database as source of truth, fetch each via API
        """
        reactions_removed = 0
        threads_to_process: list[discord.Thread] = []

        try:
            # Get thread IDs to process
            if target_thread_id:
                # Single thread - fetch directly via API (never rely on cache)
                thread_ids = [target_thread_id]
            else:
                # All threads - use database as source of truth
                if not hasattr(self.bot, 'debates_service') or not self.bot.debates_service:
                    logger.warning("Debates service not available for reaction cleanup")
                    return
                thread_ids = self.bot.debates_service.db.get_all_debate_thread_ids()

            logger.info("Reaction Cleanup Starting", [
                ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                ("Thread IDs To Fetch", str(len(thread_ids))),
            ])

            # Fetch each thread via API (guarantees fresh data)
            for thread_id in thread_ids:
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                    if thread and isinstance(thread, discord.Thread):
                        threads_to_process.append(thread)
                except discord.NotFound:
                    # Thread was deleted
                    logger.debug("Thread Not Found (Deleted)", [
                        ("Thread ID", str(thread_id)),
                    ])
                except discord.HTTPException as e:
                    log_http_error(e, "Fetch Thread For Cleanup", [
                        ("Thread ID", str(thread_id)),
                        ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                    ])
                # Small delay between fetches to avoid rate limits
                await asyncio.sleep(BATCH_PROCESSING_DELAY)

            logger.info("Threads Fetched For Cleanup", [
                ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                ("Threads Found", str(len(threads_to_process))),
            ])

            # Remove only the green checkmark (✅) reaction from the analytics embed
            # The analytics embed is the pinned message with rules - NOT the starter message
            for thread in threads_to_process:
                try:
                    # Get the analytics message ID from database
                    analytics_msg_id = self.bot.debates_service.db.get_analytics_message(thread.id)

                    if not analytics_msg_id:
                        logger.debug("No Analytics Message Found", [
                            ("Thread ID", str(thread.id)),
                        ])
                        continue

                    # Fetch the analytics message
                    try:
                        analytics_message = await thread.fetch_message(analytics_msg_id)
                    except discord.NotFound:
                        logger.debug("Analytics Message Not Found", [
                            ("Message ID", str(analytics_msg_id)),
                            ("Thread ID", str(thread.id)),
                        ])
                        continue

                    # Log all reactions on this message for debugging
                    reaction_summary = [(str(r.emoji), r.count) for r in analytics_message.reactions]
                    logger.info("Checking Analytics Message For Reactions", [
                        ("Thread", thread.name[:30]),
                        ("Analytics Msg ID", str(analytics_msg_id)),
                        ("Reactions", str(reaction_summary)),
                    ])

                    for reaction in analytics_message.reactions:
                        # Only remove the verify/participate reaction
                        emoji_str = str(reaction.emoji)
                        if emoji_str == EmbedIcons.PARTICIPATE:
                            # Check if user has this reaction by fetching users
                            user_has_reaction = False
                            async for reaction_user in reaction.users():
                                if reaction_user.id == user.id:
                                    user_has_reaction = True
                                    break

                            if user_has_reaction:
                                success = await remove_reaction_safe(reaction, user)
                                if success:
                                    reactions_removed += 1
                                    logger.info("Removed Checkmark Reaction", [
                                        ("Thread", thread.name[:30]),
                                        ("Thread ID", str(thread.id)),
                                        ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                                    ])
                                else:
                                    logger.warning("Failed To Remove Checkmark Reaction", [
                                        ("Thread", thread.name[:30]),
                                        ("Thread ID", str(thread.id)),
                                    ])
                            await asyncio.sleep(REACTION_DELAY)  # Rate limit delay
                except discord.NotFound:
                    logger.debug("Message Not Found During Reaction Cleanup", [
                        ("Thread ID", str(thread.id)),
                    ])
                except discord.HTTPException as e:
                    log_http_error(e, "Process Thread Reactions", [
                        ("Thread", thread.name[:30]),
                        ("Thread ID", str(thread.id)),
                    ])
                await asyncio.sleep(DISCORD_API_DELAY)  # Delay between threads

            logger.info("Ban Reactions Cleanup Complete", [
                ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                ("Threads Processed", str(len(threads_to_process))),
                ("Reactions Removed", str(reactions_removed)),
            ])

        except Exception as e:
            logger.error("Failed To Remove Reactions For Banned User", [
                ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                ("Error", str(e)),
            ])


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(DisallowCog(bot))
    logger.tree("Command Loaded", [("Name", "disallow")], emoji="✅")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DisallowCog", "setup"]
