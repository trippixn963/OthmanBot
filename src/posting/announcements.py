"""
Othman Discord Bot - Announcements Module
==========================================

Shared announcement embed logic for all content types.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.utils import get_developer_avatar

if TYPE_CHECKING:
    from src.bot import OthmanBot
    from src.services import Article as NewsArticle
    from src.services import Article as SoccerArticle
    from src.services import GamingArticle


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
        logger.warning(f"General channel not found or invalid")
        return

    try:
        teaser = article.english_summary[:100] + "..." if len(article.english_summary) > 100 else article.english_summary

        embed = discord.Embed(
            title=article.title,
            description=teaser,
            color=discord.Color.blue(),
        )

        # Developer footer
        developer_avatar_url = await get_developer_avatar(bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        # Create button
        view = discord.ui.View()
        button = discord.ui.Button(
            label="📰 Read Full Article",
            style=discord.ButtonStyle.link,
            url=thread.jump_url
        )
        view.add_item(button)

        message = await general_channel.send(embed=embed, view=view)
        bot.announcement_messages.add(message.id)
        logger.info(f"📣 Sent news announcement: {article.title[:50]}")

    except discord.HTTPException as e:
        logger.error(f"Failed to send news announcement: {e}")


# =============================================================================
# Soccer Announcement
# =============================================================================

async def send_soccer_announcement(
    bot: "OthmanBot",
    thread: discord.Thread,
    article: "SoccerArticle",
    applied_tags: list[discord.Object]
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
        logger.warning(f"General channel not found or invalid")
        return

    try:
        teaser = article.english_summary[:100] + "..." if len(article.english_summary) > 100 else article.english_summary

        embed = discord.Embed(
            title=article.title,
            description=teaser,
            color=discord.Color.green(),
        )

        developer_avatar_url = await get_developer_avatar(bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        view = discord.ui.View()
        button = discord.ui.Button(
            label="⚽ Read Full Article",
            style=discord.ButtonStyle.link,
            url=thread.jump_url
        )
        view.add_item(button)

        message = await general_channel.send(embed=embed, view=view)
        bot.announcement_messages.add(message.id)
        logger.info(f"📣 Sent soccer announcement: {article.title[:50]}")

    except discord.HTTPException as e:
        logger.error(f"Failed to send soccer announcement: {e}")


# =============================================================================
# Gaming Announcement
# =============================================================================

async def send_gaming_announcement(
    bot: "OthmanBot",
    thread: discord.Thread,
    article: "GamingArticle"
) -> None:
    """
    Send gaming announcement embed to general chat channel.

    Args:
        bot: The OthmanBot instance
        thread: Forum thread that was created
        article: GamingArticle that was posted

    DESIGN: Identical format to news/soccer announcements for consistency
    Uses purple color to distinguish from news (blue) and soccer (green)
    Tracks message ID for reaction blocking
    """
    general_channel = bot.get_channel(bot.general_channel_id)
    if not general_channel or not isinstance(general_channel, discord.TextChannel):
        logger.warning(f"General channel not found or invalid")
        return

    try:
        teaser = article.english_summary[:100] + "..." if len(article.english_summary) > 100 else article.english_summary

        embed = discord.Embed(
            title=article.title,
            description=teaser,
            color=discord.Color.purple(),
        )

        developer_avatar_url = await get_developer_avatar(bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        view = discord.ui.View()
        button = discord.ui.Button(
            label="🎮 Read Full Article",
            style=discord.ButtonStyle.link,
            url=thread.jump_url
        )
        view.add_item(button)

        message = await general_channel.send(embed=embed, view=view)
        bot.announcement_messages.add(message.id)
        logger.info(f"📣 Sent gaming announcement: {article.title[:50]}")

    except discord.HTTPException as e:
        logger.error(f"Failed to send gaming announcement: {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "send_general_announcement",
    "send_soccer_announcement",
    "send_gaming_announcement",
]
