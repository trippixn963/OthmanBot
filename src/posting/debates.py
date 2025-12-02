"""
Othman Discord Bot - Hot Debate Posting
========================================

Posts hot debates to general channel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Hot Debate Posting
# =============================================================================

async def post_hot_debate(bot: "OthmanBot") -> None:
    """
    Post the hottest debate to the general channel.

    Args:
        bot: The OthmanBot instance

    DESIGN: Fetches the hottest debate from the debates forum
    Posts a formatted announcement to the general channel
    Includes reply count, karma, and top contributor
    Format: **"Debate Title"** (debate)
            💬 24 replies | ⬆️ 156 karma | 🔥 Hot take by @user
    """
    try:
        # Validate configuration
        if not bot.general_channel_id:
            logger.warning("General channel not configured - skipping hot debate post")
            return

        if not bot.debates_service:
            logger.warning("Debates service not initialized - skipping hot debate post")
            return

        # Get general channel
        general_channel = bot.get_channel(bot.general_channel_id)
        if not general_channel or not isinstance(general_channel, discord.TextChannel):
            logger.warning(f"General channel {bot.general_channel_id} not found or invalid")
            return

        # Get hottest debate
        logger.info("🔥 Fetching hottest debate...")
        hot_debate = await bot.debates_service.get_hottest_debate(bot, DEBATES_FORUM_ID)

        if not hot_debate:
            logger.info("No hot debates found - skipping post")
            return

        # Format the announcement
        karma_display = f"⬆️ {hot_debate.karma}" if hot_debate.karma >= 0 else f"⬇️ {abs(hot_debate.karma)}"

        # Get top contributor mention
        contributor_text = "N/A"
        if hot_debate.top_contributor_id:
            # Use Discord mention format for proper clickable mention
            contributor_text = f"<@{hot_debate.top_contributor_id}>"
        elif hot_debate.top_contributor_name:
            contributor_text = hot_debate.top_contributor_name

        # Create embed
        embed = discord.Embed(
            title=f"🔥 {hot_debate.thread.name}",
            description="Join the hottest debate happening right now!",
            color=discord.Color.orange(),
            url=hot_debate.thread.jump_url
        )

        # Add fields
        embed.add_field(name="💬 Replies", value=str(hot_debate.reply_count), inline=True)
        embed.add_field(name="Karma", value=karma_display, inline=True)
        embed.add_field(name="🔥 Hot Take By", value=contributor_text, inline=True)

        # Create button to jump to debate
        view = discord.ui.View()
        button = discord.ui.Button(
            label="🔥 Join the Debate",
            style=discord.ButtonStyle.link,
            url=hot_debate.thread.jump_url
        )
        view.add_item(button)

        # Send message with embed
        await general_channel.send(embed=embed, view=view)

        logger.success(
            f"🔥 Posted hot debate: {hot_debate.thread.name} "
            f"(score: {hot_debate.hotness_score:.1f})"
        )

    except discord.HTTPException as e:
        logger.error(f"Failed to post hot debate (Discord API error): {e}")
    except Exception as e:
        logger.error(f"Failed to post hot debate: {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["post_hot_debate"]
