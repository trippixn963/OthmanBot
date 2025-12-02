"""
Othman Discord Bot - News Poster Module
========================================

News article posting to forum channels.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.presence import update_presence
from src.posting.poster import download_image, download_video, cleanup_temp_file
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
        logger.error("NEWS_CHANNEL_ID not configured")
        return

    if not bot.news_scraper:
        logger.error("News scraper not initialized")
        return

    try:
        logger.info("📰 Fetching latest news articles...")
        articles = await bot.news_scraper.fetch_latest_news(max_articles=1)

        if not articles:
            logger.warning("No new articles found to post")
            return

        article = articles[0]
        channel = bot.get_channel(bot.news_channel_id)
        if not channel:
            logger.error(f"News channel {bot.news_channel_id} not found")
            return

        if isinstance(channel, discord.ForumChannel):
            await post_article_to_forum(bot, channel, article)
        else:
            logger.error(f"Channel {bot.news_channel_id} is not a forum channel")
            return

        logger.success(f"✅ Posted 1 news article")
        await update_presence(bot)

    except Exception as e:
        logger.error(f"Failed to post news: {e}")


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
            logger.info(f"Downloaded image for: {article.title[:30]}")

    if article.video_url:
        video_file, temp_video_path = await download_video(
            article.video_url, "video", hash(article.url)
        )

    try:
        # Build message content
        message_content = _build_forum_content(article)

        # Format thread name
        post_date = datetime.now().strftime("%m-%d-%y")
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

        # Mark as posted
        if bot.news_scraper:
            article_id = bot.news_scraper._extract_article_id(article.url)
            bot.news_scraper.fetched_urls.add(article_id)
            bot.news_scraper._save_posted_urls()
            logger.info(f"✅ Marked article ID as posted: {article_id}")

        tag_info = f" (Tag: {applied_tags[0].name})" if applied_tags else ""
        media_info = f"Image: {'Yes' if image_file else 'No'}, Video: {'Yes' if video_file else 'No'}"
        logger.info(f"📰 Posted forum thread: {article.title} ({media_info}){tag_info}")

        # Send announcement
        if bot.general_channel_id:
            await send_general_announcement(bot, thread, article, applied_tags)

    except discord.HTTPException as e:
        logger.error(f"Failed to create forum post: {e}")
    finally:
        cleanup_temp_file(temp_image_path)
        cleanup_temp_file(temp_video_path)


# =============================================================================
# Content Building
# =============================================================================

def _build_forum_content(article: NewsArticle) -> str:
    """
    Build forum post content with bilingual summaries.

    Args:
        article: NewsArticle to format

    Returns:
        Formatted message content

    DESIGN: Build footer first to calculate remaining space for summaries
    Ensures URL is never truncated (breaks "Read Full Article" link)
    Key quote at top for engagement, then Arabic/English summaries
    """
    # Build footer first to calculate space
    published_date_str = article.published_date.strftime("%B %d, %Y") if article.published_date else "N/A"

    footer = ""
    footer += f"📰 **Source:** {article.source_emoji} {article.source} • 🔗 **[Read Full Article](<{article.url}>)**\n"
    footer += f"📅 **Published:** {published_date_str}\n\n"
    footer += "-# ⚠️ This news article was automatically generated and posted by an automated bot. "
    footer += "The content is sourced from various news outlets and summarized using AI.\n\n"
    footer += "-# Bot developed by حَـــــنَّـــــا."

    # Calculate space for summaries
    max_summary_space = 2000 - len(footer) - 400

    # Truncate if needed
    arabic_summary = article.arabic_summary
    english_summary = article.english_summary

    combined_length = len(arabic_summary) + len(english_summary)
    if combined_length > max_summary_space:
        max_each = max_summary_space // 2
        if len(arabic_summary) > max_each:
            arabic_summary = arabic_summary[:max_each-3] + "..."
        if len(english_summary) > max_each:
            english_summary = english_summary[:max_each-3] + "..."

    # Build content
    message_content = ""

    # Key quote
    first_sentence = english_summary.split('.')[0].strip()
    if len(first_sentence) > 250:
        first_sentence = first_sentence[:247].strip() + '...'
    else:
        first_sentence = first_sentence + '.'

    if len(first_sentence) > 20:
        message_content += f"> 💬 *\"{first_sentence}\"*\n\n"
        message_content += "─────────────\n\n"

    # Summaries
    message_content += f"🇸🇾 **Arabic Summary**\n{arabic_summary}\n\n"
    message_content += "─────────────\n\n"
    message_content += f"🇬🇧 **English Translation**\n{english_summary}\n\n"
    message_content += "─────────────\n\n"

    message_content += footer

    return message_content


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["post_news", "post_article_to_forum"]
