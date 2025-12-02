"""
Othman Discord Bot - Gaming Poster Module
==========================================

Gaming news article posting to forum channels.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.posting.poster import download_image, cleanup_temp_file
from src.posting.announcements import send_gaming_announcement
from src.services import GamingArticle
from src.utils.retry import exponential_backoff

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Gaming News Posting
# =============================================================================

@exponential_backoff(max_retries=3, base_delay=10)
async def post_gaming_news(bot: "OthmanBot") -> None:
    """
    Post latest gaming news articles to the gaming channel.

    Args:
        bot: The OthmanBot instance

    DESIGN: Called by scheduler every hour automatically
    Fetches gaming news, formats embeds, creates forum posts
    Handles all errors gracefully to keep scheduler running
    """
    if not bot.gaming_channel_id:
        logger.error("GAMING_CHANNEL_ID not configured")
        return

    if not bot.gaming_scraper:
        logger.error("Gaming scraper not initialized")
        return

    try:
        logger.info("🎮 Fetching latest gaming news articles...")
        articles = await bot.gaming_scraper.fetch_latest_gaming_news(
            max_articles=1, hours_back=24
        )

        if not articles:
            logger.warning("No new gaming articles found to post")
            return

        article = articles[0]
        channel = bot.get_channel(bot.gaming_channel_id)
        if not channel:
            logger.error(f"Gaming channel {bot.gaming_channel_id} not found")
            return

        if isinstance(channel, discord.ForumChannel):
            await post_gaming_article_to_forum(bot, channel, article)
        else:
            logger.error(f"Channel {bot.gaming_channel_id} is not a forum channel")
            return

        logger.success(f"✅ Posted 1 gaming article")

    except Exception as e:
        logger.error(f"Failed to post gaming news: {e}")


# =============================================================================
# Forum Posting
# =============================================================================

async def post_gaming_article_to_forum(
    bot: "OthmanBot",
    channel: discord.ForumChannel,
    article: GamingArticle
) -> None:
    """
    Post a gaming article to a forum channel.

    Args:
        bot: The OthmanBot instance
        channel: Forum channel to post in
        article: GamingArticle to post

    DESIGN: Download image and upload to Discord (not URL)
    Creates forum thread with bilingual summaries
    Marks article as posted to prevent duplicates
    """
    image_file = None
    temp_image_path = None

    # Download image
    if article.image_url:
        image_file, temp_image_path = await download_image(
            article.image_url, "gaming", hash(article.url)
        )
        if image_file:
            logger.info(f"🎮 Downloaded image for: {article.title[:30]}")

    try:
        # Build message content
        message_content = _build_forum_content(article)

        # Format thread name
        post_date = datetime.now().strftime("%m-%d-%y")
        thread_name = f"📅 {post_date} | {article.title}"
        if len(thread_name) > 100:
            thread_name = f"📅 {post_date} | {article.title[:80]}..."

        # Prepare files
        files = [image_file] if image_file else []

        # Create thread
        thread, _ = await channel.create_thread(
            name=thread_name,
            content=message_content,
            files=files,
        )

        # Mark as posted
        article_id = bot.gaming_scraper._extract_article_id(article.url)
        bot.gaming_scraper.fetched_urls.add(article_id)
        bot.gaming_scraper._save_posted_urls()
        logger.info(f"🎮 Marked gaming article ID as posted: {article_id}")
        logger.info(f"🎮 Posted gaming forum thread: {article.title}")

        # Send announcement
        if bot.general_channel_id:
            await send_gaming_announcement(bot, thread, article)

    finally:
        cleanup_temp_file(temp_image_path)


# =============================================================================
# Content Building
# =============================================================================

def _build_forum_content(article: GamingArticle) -> str:
    """
    Build forum post content with bilingual summaries.

    Args:
        article: GamingArticle to format

    Returns:
        Formatted message content

    DESIGN: Build footer first to calculate remaining space for summaries
    Ensures URL is never truncated (breaks "Read Full Article" link)
    Key quote at top for engagement, then Arabic/English summaries
    """
    published_date_str = article.published_date.strftime("%B %d, %Y") if article.published_date else "N/A"

    footer = ""
    footer += f"📰 **Source:** {article.source_emoji} {article.source} • 🔗 **[Read Full Article](<{article.url}>)**\n"
    footer += f"📅 **Published:** {published_date_str}\n\n"
    footer += "-# ⚠️ This news article was automatically generated and posted by an automated bot. "
    footer += "The content is sourced from various news outlets and summarized using AI.\n\n"
    footer += "-# Bot developed by حَـــــنَّـــــا."

    max_summary_space = 2000 - len(footer) - 400

    arabic_summary = article.arabic_summary
    english_summary = article.english_summary

    combined_length = len(arabic_summary) + len(english_summary)
    if combined_length > max_summary_space:
        max_each = max_summary_space // 2
        if len(arabic_summary) > max_each:
            arabic_summary = arabic_summary[:max_each-3] + "..."
        if len(english_summary) > max_each:
            english_summary = english_summary[:max_each-3] + "..."

    message_content = ""

    first_sentence = english_summary.split('.')[0].strip()
    if len(first_sentence) > 250:
        first_sentence = first_sentence[:247].strip() + '...'
    else:
        first_sentence = first_sentence + '.'

    if len(first_sentence) > 20:
        message_content += f"> 💬 *\"{first_sentence}\"*\n\n"
        message_content += "─────────────\n\n"

    message_content += f"🇸🇾 **Arabic Summary**\n{arabic_summary}\n\n"
    message_content += "─────────────\n\n"
    message_content += f"🇬🇧 **English Translation**\n{english_summary}\n\n"
    message_content += "─────────────\n\n"

    message_content += footer

    return message_content


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["post_gaming_news", "post_gaming_article_to_forum"]
