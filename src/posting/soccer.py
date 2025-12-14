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
from src.posting.poster import download_image, cleanup_temp_file
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
        message_content = _build_forum_content(article)

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

        # Mark as posted
        article_id = bot.soccer_scraper._extract_article_id(article.url)
        bot.soccer_scraper.fetched_urls.add(article_id)
        bot.soccer_scraper._save_posted_urls()
        logger.info("⚽ Marked Soccer Article As Posted", [
            ("Article ID", article_id),
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
# Content Building
# =============================================================================

def _build_forum_content(article: SoccerArticle) -> str:
    """
    Build forum post content with bilingual summaries.

    Args:
        article: SoccerArticle to format

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

    # Add null checks
    arabic_summary = article.arabic_summary or "الملخص غير متوفر"
    english_summary = article.english_summary or "Summary not available"

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

__all__ = ["post_soccer_news", "post_soccer_article_to_forum"]
