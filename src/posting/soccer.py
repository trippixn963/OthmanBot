"""
Othman Discord Bot - Soccer Poster Module
==========================================

Soccer news article posting to forum channels.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.posting.poster import download_image, cleanup_temp_file, build_forum_content
from src.posting.announcements import send_soccer_announcement
from src.services import Article as SoccerArticle
from src.core.config import SOCCER_TEAM_TAG_IDS
from src.utils.retry import exponential_backoff

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Soccer News Posting
# =============================================================================

@exponential_backoff(max_retries=3, base_delay=10)
async def post_soccer_news(bot: "OthmanBot") -> None:
    """
    Post latest soccer news articles to the soccer channel.

    Args:
        bot: The OthmanBot instance

    DESIGN: Called by scheduler every 3 hours automatically
    Fetches soccer news, formats embeds, creates forum posts
    Handles all errors gracefully to keep scheduler running
    """
    if not bot.soccer_channel_id:
        logger.error("⚽ SOCCER_CHANNEL_ID Not Configured")
        return

    if not bot.soccer_scraper:
        logger.error("⚽ Soccer Scraper Not Initialized")
        return

    try:
        logger.info("⚽ Fetching Latest Soccer News Articles")
        articles = await bot.soccer_scraper.fetch_latest_soccer_news(
            max_articles=1, hours_back=24
        )

        if not articles:
            logger.warning("⚽ No New Soccer Articles Found To Post")
            return

        article = articles[0]
        channel = bot.get_channel(bot.soccer_channel_id)
        if not channel:
            logger.error("⚽ Soccer Channel Not Found", [
                ("Channel ID", str(bot.soccer_channel_id)),
            ])
            return

        if isinstance(channel, discord.ForumChannel):
            await post_soccer_article_to_forum(bot, channel, article)
        else:
            logger.error("⚽ Channel Is Not A Forum Channel", [
                ("Channel ID", str(bot.soccer_channel_id)),
            ])
            return

        logger.success("⚽ Posted Soccer Article", [
            ("Count", "1"),
        ])

    except Exception as e:
        logger.error("⚽ Failed To Post Soccer News", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "Soccer News Posting Error",
                    f"{type(e).__name__}: {str(e)}"
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])


# =============================================================================
# Forum Posting
# =============================================================================

async def post_soccer_article_to_forum(
    bot: "OthmanBot",
    channel: discord.ForumChannel,
    article: SoccerArticle
) -> None:
    """
    Post a soccer article to a forum channel.

    Args:
        bot: The OthmanBot instance
        channel: Forum channel to post in
        article: SoccerArticle to post

    DESIGN: Download image and upload to Discord (not URL)
    Creates forum thread with bilingual summaries and team tags
    Marks article as posted to prevent duplicates
    """
    image_file = None
    temp_image_path = None

    # Download image
    if article.image_url:
        image_file, temp_image_path = await download_image(
            article.image_url, "soccer", hash(article.url)
        )
        if image_file:
            logger.info("⚽ Downloaded Image", [
                ("Title", article.title[:30]),
            ])

    try:
        # Build message content
        message_content = build_forum_content(
            source=article.source,
            source_emoji=article.source_emoji,
            url=article.url,
            published_date=article.published_date,
            arabic_summary=article.arabic_summary,
            english_summary=article.english_summary,
        )

        # Format thread name
        post_date = datetime.now().strftime("%m-%d-%y")
        thread_name = f"📅 {post_date} | {article.title}"
        if len(thread_name) > 100:
            thread_name = f"📅 {post_date} | {article.title[:80]}..."

        # Get team tags
        applied_tags = []
        if article.team_tag and article.team_tag in SOCCER_TEAM_TAG_IDS:
            tag_id = SOCCER_TEAM_TAG_IDS[article.team_tag]
            applied_tags.append(discord.Object(id=tag_id))
            logger.info("⚽ Applying Team Tag", [
                ("Team", article.team_tag),
                ("Tag ID", str(tag_id)),
            ])

        # Prepare files
        files = [image_file] if image_file else []

        # Create thread
        thread, _ = await channel.create_thread(
            name=thread_name,
            content=message_content,
            files=files,
            applied_tags=applied_tags,
        )

        # Mark as posted (saves to database)
        bot.soccer_scraper.add_posted_url(article.url)
        logger.info("⚽ Marked Soccer Article As Posted", [
            ("Article ID", bot.soccer_scraper._extract_article_id(article.url)),
        ])
        logger.info("⚽ Posted Soccer Forum Thread", [
            ("Title", article.title[:50]),
        ])

        # Log to webhook
        if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
            thread_link = f"https://discord.com/channels/{thread.guild.id}/{thread.id}" if thread.guild else None
            await bot.interaction_logger.log_news_posted(
                "soccer", article.title, channel.name, article.source, thread_link
            )

        # Send announcement
        if bot.general_channel_id:
            await send_soccer_announcement(bot, thread, article, applied_tags)

    except discord.HTTPException as e:
        logger.error("⚽ Failed To Create Soccer Forum Post", [
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "Soccer Forum Post Failed",
                    f"Article: {article.title[:50]}, Error: {str(e)}"
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])
    finally:
        cleanup_temp_file(temp_image_path)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["post_soccer_news", "post_soccer_article_to_forum"]
