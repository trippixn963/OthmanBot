"""
Othman Discord Bot - Debates Commands
======================================

Slash commands for karma viewing and moderation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import List, Optional, TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, DISCORD_AUTOCOMPLETE_LIMIT
from src.utils import get_developer_avatar, remove_reaction_safe, edit_thread_with_retry, send_message_with_retry, add_reactions_with_delay, delete_message_safe
from src.handlers.debates import get_next_debate_number, is_english_only, PARTICIPATE_EMOJI
from src.services.debates.tags import detect_debate_tags
from src.services.debates.analytics import calculate_debate_analytics, generate_analytics_embed

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


# =============================================================================
# Cog Class
# =============================================================================

class DebatesCog(commands.Cog):
    """Cog for debate karma commands."""

    def __init__(self, bot: "OthmanBot") -> None:
        """
        Initialize the DebatesCog.

        Args:
            bot: The OthmanBot instance to attach commands to.
        """
        self.bot = bot

    @app_commands.command(name="karma", description="Check karma points for yourself or another user")
    @app_commands.describe(user="User to check karma for (leave empty for yourself)")
    async def karma(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None
    ) -> None:
        """View karma for a user."""
        # Log command invocation
        logger.info("/karma Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Target User", f"{user.name} ({user.id})" if user else "Self"),
        ])

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/karma Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", "Debates service not initialized"),
            ])
            await interaction.response.send_message(
                "Karma system is not available.",
                ephemeral=True
            )
            return

        target = user or interaction.user
        karma_data = self.bot.debates_service.get_karma(target.id)
        rank = self.bot.debates_service.get_rank(target.id)

        embed = discord.Embed(
            title=f"🗳️ Karma for {target.display_name}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="Total Karma",
            value=f"`{karma_data.total_karma:,}`",
            inline=True
        )
        embed.add_field(
            name="Rank",
            value=f"`#{rank}`",
            inline=True
        )
        embed.add_field(
            name="Votes Received",
            value=f"⬆️ `{karma_data.upvotes_received:,}` | ⬇️ `{karma_data.downvotes_received:,}`",
            inline=False
        )

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        logger.success("/karma Command Completed", [
            ("Requested By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target User", f"{target.name} ({target.id})"),
            ("Karma", str(karma_data.total_karma)),
            ("Rank", f"#{rank}"),
            ("Upvotes", str(karma_data.upvotes_received)),
            ("Downvotes", str(karma_data.downvotes_received)),
        ])

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="disallow", description="Ban a user from a debate thread or all debates")
    @app_commands.describe(
        user="User to ban from debates",
        thread_id="Thread ID to ban from (use 'all' for all debates)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def disallow(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        thread_id: str
    ) -> None:
        """Ban a user from a specific debate thread or all debates."""
        # Log command invocation
        logger.info("/disallow Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("Target User", f"{user.name} ({user.id})"),
            ("Thread ID Param", thread_id),
        ])

        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            logger.warning("/disallow Command Failed - Service Unavailable", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
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
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", "User attempted to ban themselves"),
            ])
            await interaction.response.send_message(
                "You cannot ban yourself from debates.",
                ephemeral=True
            )
            return

        # Parse thread_id
        if thread_id.lower() == "all":
            target_thread_id = None
            scope = "all debates"
        else:
            try:
                target_thread_id = int(thread_id)
                scope = f"thread `{target_thread_id}`"
            except ValueError:
                logger.warning("/disallow Command Failed - Invalid Thread ID", [
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Invalid Thread ID", thread_id),
                    ("Reason", "Could not parse thread ID as integer"),
                ])
                await interaction.response.send_message(
                    "Invalid thread ID. Use a number or 'all'.",
                    ephemeral=True
                )
                return

        # Add the ban
        success = self.bot.debates_service.db.add_debate_ban(
            user_id=user.id,
            thread_id=target_thread_id,
            banned_by=interaction.user.id
        )

        if success:
            logger.success("/disallow Command Completed - User Banned", [
                ("Banned User", f"{user.name} ({user.id})"),
                ("Banned By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Scope", scope),
                ("Thread ID", str(target_thread_id) if target_thread_id else "Global"),
            ])

            # Remove user's reactions from debate threads (so they must re-acknowledge rules when unbanned)
            reactions_removed = 0
            try:
                debates_forum = self.bot.get_channel(DEBATES_FORUM_ID)
                if debates_forum:
                    threads_to_check = []

                    if target_thread_id:
                        # Specific thread ban - only check that thread
                        thread = debates_forum.get_thread(target_thread_id)
                        if thread:
                            threads_to_check.append(thread)
                    else:
                        # Global ban - check all threads
                        threads_to_check = list(debates_forum.threads)
                        async for archived_thread in debates_forum.archived_threads(limit=100):
                            threads_to_check.append(archived_thread)

                    # Remove reactions from first message of each thread
                    for thread in threads_to_check:
                        try:
                            # Get the starter message (first message in thread)
                            starter_message = thread.starter_message
                            if not starter_message:
                                starter_message = await thread.fetch_message(thread.id)

                            if starter_message:
                                for reaction in starter_message.reactions:
                                    success = await remove_reaction_safe(reaction, user)
                                    if success:
                                        reactions_removed += 1
                                    await asyncio.sleep(0.3)  # Rate limit delay between reaction removals
                            await asyncio.sleep(0.5)  # Rate limit delay between threads
                        except discord.HTTPException:
                            pass

                if reactions_removed > 0:
                    logger.info("Ban Reactions Cleanup", [
                        ("User", f"{user.name} ({user.id})"),
                        ("Reactions Removed", str(reactions_removed)),
                    ])
            except Exception as e:
                logger.warning("Failed To Remove Reactions For Banned User", [
                    ("Error", str(e)),
                ])

            # Create public embed for the ban
            embed = discord.Embed(
                title="User Banned from Debates",
                description=(
                    f"**{user.mention}** has been banned from {scope}.\n\n"
                    f"They can no longer post messages there."
                ),
                color=discord.Color.red()
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Banned By", value=interaction.user.mention, inline=True)
            embed.add_field(name="Scope", value=scope.title(), inline=True)

            developer_avatar_url = await get_developer_avatar(self.bot)
            embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

            await interaction.response.send_message(embed=embed)
        else:
            logger.info("/disallow Command - User Already Banned", [
                ("Target User", f"{user.name} ({user.id})"),
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Scope", scope),
            ])
            await interaction.response.send_message(
                f"**{user.display_name}** is already banned from {scope}.",
                ephemeral=True
            )

    @app_commands.command(name="allow", description="Unban a user from a debate thread or all debates")
    @app_commands.describe(
        user="User to unban from debates (shows banned users)",
        thread_id="Thread ID to unban from (use 'all' for all debates, leave empty to see bans)"
    )
    @app_commands.autocomplete(user=banned_user_autocomplete)
    @app_commands.default_permissions(manage_messages=True)
    async def allow(
        self,
        interaction: discord.Interaction,
        user: str,
        thread_id: str = None
    ) -> None:
        """Unban a user from a specific debate thread or all debates."""
        # Log command invocation
        logger.info("/allow Command Invoked", [
            ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channel", f"#{interaction.channel.name if interaction.channel else 'Unknown'} ({interaction.channel_id})"),
            ("User Param", user),
            ("Thread ID Param", thread_id if thread_id else "None (list bans)"),
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

        # Get user's current bans
        bans = self.bot.debates_service.db.get_user_bans(user_id)

        # If no thread_id provided, show list of bans
        if thread_id is None:
            if not bans:
                logger.info("/allow Command - User Has No Bans", [
                    ("Target User", f"{display_name} ({user_id})"),
                    ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ])
                await interaction.response.send_message(
                    f"**{display_name}** has no active debate bans.",
                    ephemeral=True
                )
                return

            # Build ban list
            ban_list = []
            for ban in bans:
                if ban['thread_id'] is None:
                    ban_list.append("• **All debates** (global ban)")
                else:
                    ban_list.append(f"• Thread `{ban['thread_id']}`")

            logger.info("/allow Command - Listing User Bans", [
                ("Target User", f"{display_name} ({user_id})"),
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Active Bans", str(len(bans))),
            ])
            await interaction.response.send_message(
                f"**{display_name}** is banned from:\n" + "\n".join(ban_list) +
                f"\n\nUse `/allow {display_name} <thread_id>` or `/allow {display_name} all` to unban.",
                ephemeral=True
            )
            return

        # Parse thread_id
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

        # Remove the ban
        success = self.bot.debates_service.db.remove_debate_ban(
            user_id=user_id,
            thread_id=target_thread_id
        )

        if success:
            logger.success("/allow Command Completed - User Unbanned", [
                ("Unbanned User", f"{display_name} ({user_id})"),
                ("Unbanned By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Scope", scope),
                ("Thread ID", str(target_thread_id) if target_thread_id else "Global"),
            ])

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

            await interaction.response.send_message(embed=embed)
        else:
            logger.info("/allow Command - User Was Not Banned", [
                ("Target User", f"{display_name} ({user_id})"),
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Scope", scope),
            ])
            await interaction.response.send_message(
                f"**{display_name}** was not banned from {scope}.",
                ephemeral=True
            )


    @app_commands.command(name="rename", description="Rename a locked debate thread with proper numbering")
    @app_commands.describe(
        title="New English title for the debate (leave empty to use suggested title from bot message)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def rename(
        self,
        interaction: discord.Interaction,
        title: str = None
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

        # If no title provided, try to extract suggested title from bot's moderation message
        if title is None:
            async for message in thread.history(limit=50):
                if message.author.id == self.bot.user.id and "Suggested Title:" in message.content:
                    # Extract suggested title from message using more robust parsing
                    lines = message.content.split("\n")
                    for line in lines:
                        # Handle various formatting: "**Suggested Title:**", "Suggested Title:", etc.
                        if "Suggested Title:" in line:
                            # Remove markdown formatting and extract title
                            title = line.replace("**Suggested Title:**", "").replace("Suggested Title:", "").strip()
                            break
                    break

        if title is None:
            logger.warning("/rename Command Failed - No Title Found", [
                ("Invoked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Thread", f"{thread.name} ({thread.id})"),
                ("Reason", "No title provided and no suggested title in thread"),
            ])
            await interaction.response.send_message(
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
            await interaction.response.send_message(
                "The title must be in English only. Please provide an English title.",
                ephemeral=True
            )
            return

        # Defer response since this might take a moment
        await interaction.response.defer()

        try:
            # Get next debate number
            debate_number = get_next_debate_number()

            # Create new title with number prefix
            new_title = f"{debate_number} | {title}"

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
            except Exception as e:
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

            async for message in thread.history(limit=100):
                # Skip the original post (the oldest message, which is the thread starter)
                if message.id == original_post_id:
                    continue
                # Delete everything else (bot messages, system messages like pins_add, etc.)
                messages_to_delete.append(message)

            for msg in messages_to_delete:
                await delete_message_safe(msg)
                deleted_count += 1
                await asyncio.sleep(0.3)  # Small delay to avoid rate limits

            if deleted_count > 0:
                logger.info("🧹 Thread Cleanup Complete", [
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
                        await add_reactions_with_delay(analytics_message, [PARTICIPATE_EMOJI])

                        # Pin the analytics message
                        await analytics_message.pin()

                        # Delete the "pinned a message" system message
                        await asyncio.sleep(1.0)  # Wait longer for Discord to create the system message
                        async for msg in thread.history(limit=10):
                            if msg.type == discord.MessageType.pins_add:
                                await delete_message_safe(msg)
                                logger.debug("Deleted 'pinned a message' system message")
                                break

                        # Store analytics message ID in database
                        self.bot.debates_service.db.set_analytics_message(thread.id, analytics_message.id)

                        logger.success("📊 Analytics Embed Posted For Renamed Debate", [
                            ("Debate", f"#{debate_number}"),
                            ("Thread ID", str(thread.id)),
                            ("Message ID", str(analytics_message.id)),
                            ("Participation Emoji", PARTICIPATE_EMOJI),
                            ("Pinned", "Yes"),
                            ("Stored in DB", "Yes"),
                        ])
                except Exception as e:
                    logger.warning("Failed to post analytics for renamed debate", [("Error", str(e))])

            # Send success message
            await interaction.followup.send(
                f"Thread renamed to **{new_title}** and unlocked.",
                ephemeral=False
            )

        except Exception as e:
            logger.error("Failed to rename debate thread", [
                ("Error", str(e)),
                ("Thread ID", str(thread.id)),
            ])
            await interaction.followup.send(
                f"An error occurred while renaming the thread: {e}",
                ephemeral=True
            )


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "OthmanBot") -> None:
    """Add cog to bot."""
    await bot.add_cog(DebatesCog(bot))
    logger.info("🗳️ Debates commands cog loaded")
