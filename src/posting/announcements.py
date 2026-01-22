"""
OthmanBot - Announcements Module
================================

Shared announcement embed logic for all content types.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import TEASER_LENGTH, EmbedColors
from src.core.emojis import READ_EMOJI
from src.utils import truncate
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import OthmanBot
    from src.services import Article as NewsArticle
    from src.services import Article as SoccerArticle


# =============================================================================
# General News Announcement
# =============================================================================

async def send_general_announcement(
    bot: "OthmanBot",
    thread: discord.Thread,
    article: "NewsArticle",
    applied_tags: list[discord.ForumTag]
) -> None:
    """
    Send news announcement embed to general chat channel.

    Args:
        bot: The OthmanBot instance
        thread: Forum thread that was created
        article: NewsArticle that was posted
        applied_tags: Tags applied to the forum thread

    DESIGN: Creates teaser embed with link button to forum thread
    Tracks message ID for reaction blocking
    Notifies users in main chat without cluttering forum
    """
    general_channel = bot.get_channel(bot.general_channel_id)
    if not general_channel or not isinstance(general_channel, discord.TextChannel):
        logger.warning("📣 General Channel Not Found Or Invalid", [
            ("Context", "News announcement"),
        ])
        return

    try:
        teaser = truncate(article.english_summary, TEASER_LENGTH)

        embed = discord.Embed(
            title=article.title,
            description=teaser,
            color=EmbedColors.INFO,
        )

        # Article image as main image
        if article.image_url:
            embed.set_image(url=article.image_url)

        # Developer footer
        set_footer(embed)

        # Create button
        view = discord.ui.View()
        button = discord.ui.Button(
            label="Read Full Article",
            emoji=discord.PartialEmoji.from_str(READ_EMOJI),
            style=discord.ButtonStyle.link,
            url=thread.jump_url
        )
        view.add_item(button)

        message = await general_channel.send(embed=embed, view=view)
        bot.announcement_messages.add(message.id)
        logger.info("📣 Sent News Announcement", [
            ("Title", article.title[:50]),
        ])

    except discord.HTTPException as e:
        logger.error("📣 Failed To Send News Announcement", [
            ("Error", str(e)),
        ])


# =============================================================================
# Soccer Announcement
# =============================================================================

async def send_soccer_announcement(
    bot: "OthmanBot",
    thread: discord.Thread,
    article: "SoccerArticle",
    applied_tags: list[discord.ForumTag]
) -> None:
    """
    Send soccer announcement embed to general chat channel.

    Args:
        bot: The OthmanBot instance
        thread: Forum thread that was created
        article: SoccerArticle that was posted
        applied_tags: Tags applied to the forum thread

    DESIGN: Identical format to news announcements for consistency
    Uses green color to distinguish from news (blue)
    Tracks message ID for reaction blocking
    """
    general_channel = bot.get_channel(bot.general_channel_id)
    if not general_channel or not isinstance(general_channel, discord.TextChannel):
        logger.warning("📣 General Channel Not Found Or Invalid", [
            ("Context", "Soccer announcement"),
        ])
        return

    try:
        teaser = truncate(article.english_summary, TEASER_LENGTH)

        embed = discord.Embed(
            title=article.title,
            description=teaser,
            color=EmbedColors.SUCCESS,
        )

        # Article image as main image
        if article.image_url:
            embed.set_image(url=article.image_url)

        # Developer footer
        set_footer(embed)

        # Create button
        view = discord.ui.View()
        button = discord.ui.Button(
            label="Read Full Article",
            emoji=discord.PartialEmoji.from_str(READ_EMOJI),
            style=discord.ButtonStyle.link,
            url=thread.jump_url
        )
        view.add_item(button)

        message = await general_channel.send(embed=embed, view=view)
        bot.announcement_messages.add(message.id)
        logger.info("📣 Sent Soccer Announcement", [
            ("Title", article.title[:50]),
        ])

    except discord.HTTPException as e:
        logger.error("📣 Failed To Send Soccer Announcement", [
            ("Error", str(e)),
        ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "send_general_announcement",
    "send_soccer_announcement",
]
