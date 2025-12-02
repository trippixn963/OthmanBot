"""
Othman Discord Bot - Debates Commands
======================================

Slash commands for karma viewing, leaderboard, and moderation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID
from src.utils import get_developer_avatar


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
    for user_id in banned_ids[:25]:  # Discord limits to 25 choices
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

    return choices[:25]


# =============================================================================
# Cog Class
# =============================================================================

class DebatesCog(commands.Cog):
    """Cog for debate karma commands."""

    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(name="karma", description="Check karma points for yourself or another user")
    @app_commands.describe(user="User to check karma for (leave empty for yourself)")
    async def karma(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None
    ) -> None:
        """View karma for a user."""
        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
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
            value=f"**{karma_data.total_karma:,}**",
            inline=True
        )
        embed.add_field(
            name="Rank",
            value=f"#{rank}",
            inline=True
        )
        embed.add_field(
            name="Votes Received",
            value=f"⬆️ {karma_data.upvotes_received:,} | ⬇️ {karma_data.downvotes_received:,}",
            inline=False
        )

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Show top users by karma")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        """Show karma leaderboard."""
        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            await interaction.response.send_message(
                "Karma system is not available.",
                ephemeral=True
            )
            return

        top_users = self.bot.debates_service.get_leaderboard(10)

        if not top_users:
            await interaction.response.send_message(
                "No karma data yet. Start voting in debates!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏆 Debates Karma Leaderboard",
            description="Top 10 users by karma points",
            color=discord.Color.gold()
        )

        leaderboard_text = []
        medals = ["🥇", "🥈", "🥉"]

        for i, karma_data in enumerate(top_users):
            # Use Discord mention format for usernames
            user_mention = f"<@{karma_data.user_id}>"

            medal = medals[i] if i < 3 else f"**{i + 1}.**"
            leaderboard_text.append(
                f"{medal} {user_mention} — **{karma_data.total_karma:,}** karma"
            )

        embed.description = "\n".join(leaderboard_text)

        developer_avatar_url = await get_developer_avatar(self.bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

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
        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            await interaction.response.send_message(
                "Debates system is not available.",
                ephemeral=True
            )
            return

        # Prevent self-ban
        if user.id == interaction.user.id:
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
            logger.info(f"🚫 {interaction.user.name} banned {user.name} from {scope}")

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
                                    try:
                                        await reaction.remove(user)
                                        reactions_removed += 1
                                    except discord.HTTPException:
                                        pass
                        except discord.HTTPException:
                            pass

                if reactions_removed > 0:
                    logger.info(f"🗑️ Removed {reactions_removed} reaction(s) from {user.name}")
            except Exception as e:
                logger.warning(f"Failed to remove reactions for banned user: {e}")

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
        if not hasattr(self.bot, 'debates_service') or self.bot.debates_service is None:
            await interaction.response.send_message(
                "Debates system is not available.",
                ephemeral=True
            )
            return

        # Resolve user string to ID
        try:
            user_id = int(user)
        except ValueError:
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
            logger.info(f"✅ {interaction.user.name} unbanned {display_name} from {scope}")

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
            await interaction.response.send_message(
                f"**{display_name}** was not banned from {scope}.",
                ephemeral=True
            )


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot) -> None:
    """Add cog to bot."""
    await bot.add_cog(DebatesCog(bot))
    logger.info("🗳️ Debates commands cog loaded")
