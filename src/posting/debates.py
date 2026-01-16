"""
OthmanBot - Hot Debate Posting
========================================

Posts hot debates to general channel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID, EmbedColors
from src.utils.footer import set_footer

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
            logger.warning("🔥 General Channel Not Configured", [
                ("Action", "Skipping hot debate post"),
            ])
            return

        if not bot.debates_service:
            logger.warning("🔥 Debates Service Not Initialized", [
                ("Action", "Skipping hot debate post"),
            ])
            return

        # Get general channel
        general_channel = bot.get_channel(bot.general_channel_id)
        if not general_channel or not isinstance(general_channel, discord.TextChannel):
            logger.warning("🔥 General Channel Not Found Or Invalid", [
                ("Channel ID", str(bot.general_channel_id)),
            ])
            return

        # Get hottest debate
        logger.info("🔥 Fetching Hottest Debate", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
        ])
        hot_debate = await bot.debates_service.get_hottest_debate(bot, DEBATES_FORUM_ID)

        if not hot_debate:
            logger.info("🔥 No Hot Debates Found", [
                ("Action", "Skipping post"),
            ])
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
            color=EmbedColors.WARNING,
            url=hot_debate.thread.jump_url
        )

        # Add fields
        embed.add_field(name="💬 Replies", value=str(hot_debate.reply_count), inline=True)
        embed.add_field(name="Karma", value=karma_display, inline=True)
        embed.add_field(name="🔥 Hot Take By", value=contributor_text, inline=True)

        # Add footer
        set_footer(embed)

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

        logger.success("🔥 Posted Hot Debate", [
            ("Title", hot_debate.thread.name[:50]),
            ("Score", f"{hot_debate.hotness_score:.1f}"),
            ("Channel", general_channel.name),
        ])

    except discord.HTTPException as e:
        logger.error("🔥 Failed To Post Hot Debate (Discord API Error)", [
            ("Status", str(e.status)),
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "Hot Debate Posting Error (Discord API)",
                    f"Status: {e.status}, Error: {str(e)}"
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        logger.error("🔥 Failed To Post Hot Debate (Data Error)", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "Hot Debate Posting Error (Data)",
                    f"{type(e).__name__}: {str(e)}"
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["post_hot_debate"]
