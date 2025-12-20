"""
OthmanBot - Rename Command
==========================

Slash command for renaming locked debate threads.

Commands:
- /rename - Rename a locked debate thread with proper numbering

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import sqlite3
from typing import Optional, TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import (
    DEBATES_FORUM_ID,
    REACTION_DELAY,
    PIN_SYSTEM_MESSAGE_DELAY,
    LOG_TITLE_PREVIEW_LENGTH,
    DISCORD_THREAD_NAME_LIMIT,
    has_debates_management_role,
    EmbedIcons,
)
from src.utils import (
    edit_thread_with_retry,
    send_message_with_retry,
    add_reactions_with_delay,
    delete_message_safe,
    is_english_only,
)
from src.handlers.debates import get_next_debate_number
from src.services.debates.tags import detect_debate_tags
from src.services.debates.analytics import calculate_debate_analytics, generate_analytics_embed

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

SUGGESTED_TITLE_SEARCH_LIMIT: int = 50
"""Maximum messages to search for suggested title."""

CLEANUP_MESSAGE_LIMIT: int = 100
"""Maximum messages to scan during thread cleanup."""

PIN_SYSTEM_MESSAGE_SEARCH_LIMIT: int = 10
"""Maximum messages to search for 'pinned a message' system message."""

TITLE_TRUNCATION_SUFFIX: str = "..."
"""Suffix to append when title is truncated."""


# =============================================================================
# Rename Cog
# =============================================================================

class RenameCog(commands.Cog):
    """Cog for /rename command."""

    def __init__(self, bot: "OthmanBot") -> None:
        self.bot = bot

    @app_commands.command(name="rename", description="Rename a locked debate thread with proper numbering")
    @app_commands.describe(
        title="New English title for the debate (leave empty to use suggested title from bot message)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def rename(
        self,
        interaction: discord.Interaction,
        title: Optional[str] = None
    ) -> None:
        """
        Rename a locked debate thread with proper numbering.

        This command is designed for moderators to properly rename threads
        that were locked due to non-English titles. It:
        1. Gets the next debate number from the counter
        2. Renames the thread with the format "{number} | {title}"
        3. Unlocks and unarchives the thread
        4. Applies auto-tags
        5. Adds analytics embed
        """
        # Log command invocation
        logger.info("/rename Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Title Param", title if title else "Auto-detect from suggested"),
        ])

        # Security check: Verify user has Debates Management role
        if not has_debates_management_role(interaction.user):
            logger.warning("/rename Command Denied - Missing Role", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.response.send_message(
                "You don't have permission to use this command. "
                "Only users with the Debates Management role can rename debates.",
                ephemeral=True
            )
            return

        # Must be used in a thread
        if not isinstance(interaction.channel, discord.Thread):
            logger.warning("/rename Command Failed - Not In Thread", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Channel Type", type(interaction.channel).__name__),
                ("Reason", "Command must be used inside a debate thread"),
            ])
            await interaction.response.send_message(
                "This command must be used inside a debate thread.",
                ephemeral=True
            )
            return

        thread = interaction.channel

        # Check if thread is in the debates forum
        if thread.parent_id != DEBATES_FORUM_ID:
            logger.warning("/rename Command Failed - Wrong Forum", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
                ("Parent ID", str(thread.parent_id)),
                ("Expected Forum ID", str(DEBATES_FORUM_ID)),
                ("Reason", "Thread not in debates forum"),
            ])
            await interaction.response.send_message(
                "This command can only be used in debate threads.",
                ephemeral=True
            )
            return

        # Defer EARLY since searching history can take time
        await interaction.response.defer()

        # Unlock/unarchive thread if needed before searching history
        if thread.locked or thread.archived:
            try:
                await thread.edit(locked=False, archived=False)
            except Exception as e:
                logger.warning("/rename Failed to Unlock Thread", [
                    ("Thread", f"{thread.name} ({thread.id})"),
                    ("Error", str(e)),
                ])

        # If no title provided, try to extract suggested title from bot's moderation message
        if title is None:
            try:
                async with asyncio.timeout(10):
                    async for message in thread.history(limit=SUGGESTED_TITLE_SEARCH_LIMIT):
                        if message.author.id == self.bot.user.id and "Suggested Title:" in message.content:
                            lines = message.content.split("\n")
                            for line in lines:
                                if "Suggested Title:" in line:
                                    title = line.replace("**Suggested Title:**", "").replace("Suggested Title:", "").strip()
                                    break
                            break
            except asyncio.TimeoutError:
                logger.warning("/rename History Search Timed Out", [
                    ("Thread", f"{thread.name} ({thread.id})"),
                ])

        if title is None:
            logger.warning("/rename Command Failed - No Title Found", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
                ("Reason", "No title provided and no suggested title in thread"),
            ])
            await interaction.followup.send(
                "No title provided and couldn't find a suggested title in this thread.\n"
                "Please provide a title: `/rename title:Your English Title Here`",
                ephemeral=True
            )
            return

        # Validate title is English-only
        if not is_english_only(title):
            logger.warning("/rename Command Failed - Non-English Title", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
                ("Provided Title", title),
                ("Reason", "Title contains non-English characters"),
            ])
            await interaction.followup.send(
                "The title must be in English only. Please provide an English title.",
                ephemeral=True
            )
            return

        try:
            # Get next debate number
            debate_number = await get_next_debate_number(self.bot)

            # Calculate available space for title (Discord limit minus number prefix)
            number_prefix = f"{debate_number} | "
            available_length = DISCORD_THREAD_NAME_LIMIT - len(number_prefix)

            # Truncate title if needed to fit Discord's thread name limit
            if len(title) > available_length:
                truncate_length = available_length - len(TITLE_TRUNCATION_SUFFIX)
                title = title[:truncate_length] + TITLE_TRUNCATION_SUFFIX

            # Create new title with number prefix
            new_title = f"{number_prefix}{title}"

            # Rename, unlock, and unarchive the thread
            success = await edit_thread_with_retry(
                thread,
                name=new_title,
                locked=False,
                archived=False
            )

            if not success:
                logger.error("/rename Command Failed - Thread Edit Failed", [
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Thread", f"{thread.name} ({thread.id})"),
                    ("Attempted Title", new_title),
                    ("Reason", "edit_thread_with_retry returned False"),
                ])
                await interaction.followup.send(
                    "Failed to rename the thread. Please try again.",
                    ephemeral=True
                )
                return

            # Get thread owner for logging
            thread_owner = thread.owner
            owner_info = f"{thread_owner.name} ({thread_owner.id})" if thread_owner else "Unknown"

            logger.success("Debate Thread Renamed via /rename", [
                ("Number", f"#{debate_number}"),
                ("Original Title", thread.name),
                ("New Title", new_title),
                ("Thread Owner", owner_info),
                ("Renamed By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread ID", str(thread.id)),
            ])

            # Try to apply auto-tags
            try:
                # Get first message for description
                starter_message = None
                async for msg in thread.history(oldest_first=True, limit=1):
                    starter_message = msg
                    break

                thread_description = starter_message.content if starter_message and starter_message.content else ""
                tag_ids = await detect_debate_tags(title, thread_description)

                if tag_ids:
                    parent_forum = self.bot.get_channel(DEBATES_FORUM_ID)
                    if parent_forum and hasattr(parent_forum, 'available_tags'):
                        available_tags = {tag.id: tag for tag in parent_forum.available_tags}
                        tags_to_apply = [available_tags[tid] for tid in tag_ids if tid in available_tags]

                        if tags_to_apply:
                            await edit_thread_with_retry(thread, applied_tags=tags_to_apply)
                            logger.info("Auto-Tags Applied to Renamed Debate", [
                                ("Debate", f"#{debate_number}"),
                                ("Tags", ", ".join(t.name for t in tags_to_apply)),
                            ])
            except (discord.HTTPException, KeyError, AttributeError) as e:
                logger.warning("Failed to auto-tag renamed debate", [("Error", str(e))])

            # Delete ALL messages except the original post (first message / thread starter)
            # This cleans up bot warnings, system messages (including "pinned a message"), and any other clutter
            deleted_count = 0
            messages_to_delete = []

            # First, find the original post (oldest message in the thread)
            original_post_id = None
            async for message in thread.history(limit=1, oldest_first=True):
                original_post_id = message.id
                break

            async for message in thread.history(limit=CLEANUP_MESSAGE_LIMIT):
                # Skip the original post (the oldest message, which is the thread starter)
                if message.id == original_post_id:
                    continue
                # Delete everything else (bot messages, system messages like pins_add, etc.)
                messages_to_delete.append(message)

            for msg in messages_to_delete:
                await delete_message_safe(msg)
                deleted_count += 1
                await asyncio.sleep(REACTION_DELAY)  # Small delay to avoid rate limits

            if deleted_count > 0:
                logger.info("Thread Cleanup Complete", [
                    ("Debate", f"#{debate_number}"),
                    ("Thread ID", str(thread.id)),
                    ("Messages Deleted", str(deleted_count)),
                    ("Original Post Preserved", "Yes"),
                ])

            # Post analytics embed if service available (matching normal flow)
            if hasattr(self.bot, 'debates_service') and self.bot.debates_service is not None:
                try:
                    # Calculate initial analytics
                    analytics = await calculate_debate_analytics(thread, self.bot.debates_service.db)

                    # Generate and send analytics embed
                    embed = await generate_analytics_embed(self.bot, analytics)
                    analytics_message = await send_message_with_retry(thread, embed=embed)

                    if analytics_message:
                        # Add participation reaction for access control
                        await add_reactions_with_delay(analytics_message, [EmbedIcons.PARTICIPATE])

                        # Pin the analytics message
                        await analytics_message.pin()

                        # Delete the "pinned a message" system message
                        await asyncio.sleep(PIN_SYSTEM_MESSAGE_DELAY)  # Wait for Discord to create the system message
                        async for msg in thread.history(limit=PIN_SYSTEM_MESSAGE_SEARCH_LIMIT):
                            if msg.type == discord.MessageType.pins_add:
                                await delete_message_safe(msg)
                                logger.debug("Deleted 'pinned a message' system message")
                                break

                        # Store analytics message ID in database
                        self.bot.debates_service.db.set_analytics_message(thread.id, analytics_message.id)

                        logger.success("Analytics Embed Posted For Renamed Debate", [
                            ("Debate", f"#{debate_number}"),
                            ("Thread ID", str(thread.id)),
                            ("Message ID", str(analytics_message.id)),
                            ("Participation Emoji", EmbedIcons.PARTICIPATE),
                            ("Pinned", "Yes"),
                            ("Stored in DB", "Yes"),
                        ])
                except (discord.HTTPException, sqlite3.Error) as e:
                    logger.warning("Failed to post analytics for renamed debate", [("Error", str(e))])

            # Track debate creator (thread owner) in database
            if hasattr(self.bot, 'debates_service') and self.bot.debates_service is not None:
                try:
                    if thread.owner_id:
                        await self.bot.debates_service.db.set_debate_creator_async(
                            thread.id, thread.owner_id
                        )
                        logger.debug("Debate Creator Tracked For Renamed Thread", [
                            ("Debate", f"#{debate_number}"),
                            ("Creator ID", str(thread.owner_id)),
                        ])
                except sqlite3.Error as e:
                    logger.warning("Failed to track debate creator", [("Error", str(e))])

            # Send success message
            followup_msg = await interaction.followup.send(
                f"Thread renamed to **{new_title}** and unlocked.",
                ephemeral=False,
                wait=True
            )

            # Get message ID for webhook link
            message_id = followup_msg.id if followup_msg else None

            # Log success to webhook
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_command(
                    interaction, "rename", success=True,
                    message_id=message_id,
                    debate=f"#{debate_number}", title=title[:LOG_TITLE_PREVIEW_LENGTH]
                )

        except (discord.HTTPException, discord.Forbidden, sqlite3.Error, ValueError) as e:
            logger.error("Failed to rename debate thread", [
                ("Error", str(e)),
                ("Error Type", type(e).__name__),
                ("Thread ID", str(thread.id)),
            ])
            await interaction.followup.send(
                f"An error occurred while renaming the thread: {e}",
                ephemeral=True
            )

            # Log failure to webhook
            if self.bot.interaction_logger:
                await self.bot.interaction_logger.log_command(
                    interaction, "rename", success=False, error=str(e)
                )


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Setup function for loading the cog."""
    await bot.add_cog(RenameCog(bot))
    logger.info("Rename Cog Loaded", [
        ("Commands", "/rename"),
    ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["RenameCog", "setup"]
