"""
Othman Discord Bot - News Poster Module
========================================

News article posting to forum channels.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import aiohttp
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.presence import update_presence
from src.posting.poster import download_image, download_video, cleanup_temp_file, build_forum_content
from src.posting.announcements import send_general_announcement
from src.services import Article as NewsArticle
from src.utils.retry import exponential_backoff

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# News Posting
# =============================================================================

@exponential_backoff(max_retries=3, base_delay=10)
async def post_news(bot: "OthmanBot") -> None:
    """
    Post latest news articles to the news channel.

    Args:
        bot: The OthmanBot instance

    DESIGN: Called by scheduler every hour automatically
    Fetches news, formats embeds, creates forum posts
    Handles all errors gracefully to keep scheduler running
    """
    if not bot.news_channel_id:
        logger.error("📰 NEWS_CHANNEL_ID Not Configured")
        return

    if not bot.news_scraper:
        logger.error("📰 News Scraper Not Initialized")
        return

    try:
        logger.info("📰 Fetching Latest News Articles")
        articles = await bot.news_scraper.fetch_latest_news(max_articles=1)

        if not articles:
            logger.warning("📰 No New Articles Found To Post")
            return

        article = articles[0]
        channel = bot.get_channel(bot.news_channel_id)
        if not channel:
            logger.error("📰 News Channel Not Found", [
                ("Channel ID", str(bot.news_channel_id)),
            ])
            return

        if isinstance(channel, discord.ForumChannel):
            await post_article_to_forum(bot, channel, article)
        else:
            logger.error("📰 Channel Is Not A Forum Channel", [
                ("Channel ID", str(bot.news_channel_id)),
            ])
            return

        logger.success("📰 Posted News Article", [
            ("Count", "1"),
        ])
        await update_presence(bot)

    except discord.HTTPException as e:
        logger.error("📰 Discord API Error Posting News", [
            ("Status", str(e.status)),
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "News Posting Error (Discord API)",
                    f"Status: {e.status}, Error: {str(e)}"
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])
    except aiohttp.ClientError as e:
        logger.error("📰 Network Error Fetching News", [
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "News Posting Error (Network)",
                    str(e)
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])
    except (ValueError, KeyError, TypeError) as e:
        logger.error("📰 Data Error Processing News", [
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "News Posting Error (Data Processing)",
                    str(e)
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])


# =============================================================================
# Forum Posting
# =============================================================================

async def post_article_to_forum(
    bot: "OthmanBot",
    channel: discord.ForumChannel,
    article: NewsArticle
) -> None:
    """
    Post a news article to a forum channel.

    Args:
        bot: The OthmanBot instance
        channel: Forum channel to post in
        article: NewsArticle to post

    DESIGN: Download media files and upload to Discord (not URLs)
    Creates forum thread with bilingual summaries and category tags
    Marks article as posted to prevent duplicates
    """
    image_file = None
    temp_image_path = None
    video_file = None
    temp_video_path = None

    # Download media
    if article.image_url:
        image_file, temp_image_path = await download_image(
            article.image_url, "article", hash(article.url)
        )
        if image_file:
            logger.info("📰 Downloaded Image", [
                ("Title", article.title[:30]),
            ])

    if article.video_url:
        video_file, temp_video_path = await download_video(
            article.video_url, "video", hash(article.url)
        )

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
        post_date = datetime.now(NY_TZ).strftime("%m-%d-%y")
        thread_name = f"📅 {post_date} | {article.title}"
        if len(thread_name) > 100:
            thread_name = f"📅 {post_date} | {article.title[:80]}..."

        # Prepare files
        files = []
        if image_file:
            files.append(image_file)
        if video_file:
            files.append(video_file)

        # Get tags
        applied_tags = []
        if article.category_tag_id:
            for tag in channel.available_tags:
                if tag.id == article.category_tag_id:
                    applied_tags.append(tag)
                    break

        # Create thread
        thread_with_msg = await channel.create_thread(
            name=thread_name,
            content=message_content,
            files=files,
            applied_tags=applied_tags,
            auto_archive_duration=1440,
        )
        thread = thread_with_msg.thread

        # Mark as posted (saves to database)
        if bot.news_scraper:
            bot.news_scraper.add_posted_url(article.url)
            logger.info("📰 Marked Article As Posted", [
                ("Article ID", bot.news_scraper._extract_article_id(article.url)),
            ])

        logger.info("📰 Posted Forum Thread", [
            ("Title", article.title[:50]),
            ("Image", "Yes" if image_file else "No"),
            ("Video", "Yes" if video_file else "No"),
            ("Tag", applied_tags[0].name if applied_tags else "None"),
        ])

        # Log to webhook
        if hasattr(bot, 'interaction_logger') and bot.interaction_logger:
            thread_link = f"https://discord.com/channels/{thread.guild.id}/{thread.id}" if thread.guild else None
            await bot.interaction_logger.log_news_posted(
                "news", article.title, channel.name, article.source, thread_link
            )

        # Send announcement
        if bot.general_channel_id:
            await send_general_announcement(bot, thread, article, applied_tags)

    except discord.HTTPException as e:
        logger.error("📰 Failed To Create Forum Post", [
            ("Error", str(e)),
        ])
        # Log to webhook
        try:
            if hasattr(bot, 'webhook_alerts') and bot.webhook_alerts:
                await bot.webhook_alerts.send_error_alert(
                    "News Forum Post Failed",
                    f"Article: {article.title[:50]}, Error: {str(e)}"
                )
        except Exception as webhook_err:
            logger.debug("Webhook alert failed", [("Error", str(webhook_err))])
    finally:
        cleanup_temp_file(temp_image_path)
        cleanup_temp_file(temp_video_path)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["post_news", "post_article_to_forum"]
