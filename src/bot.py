"""
Othman Discord Bot - Main Bot Class
===================================

Main Discord client implementation for automated news posting.

Features:
- Fully automated hourly news posting
- News scraper integration
- No commands - pure automation
- News posting with embeds and threads

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import asyncio
from typing import Optional

import discord
from discord.ext import commands

from src.core.logger import logger
from src.services.news_scraper import NewsScraper, NewsArticle
from src.services.news_scheduler import NewsScheduler


class OthmanBot(commands.Bot):
    """Main Discord bot class for Othman News Bot."""

    def __init__(self) -> None:
        """Initialize the Othman bot with necessary intents and configuration."""
        # DESIGN: Minimal intents for automated posting only
        # No need for message content or member intents
        intents: discord.Intents = discord.Intents.default()
        intents.guilds = True

        super().__init__(
            command_prefix="!",  # Required but unused
            intents=intents,
            help_command=None,
        )

        # Load configuration from environment
        self.news_channel_id: Optional[int] = self._load_channel_id()

        # Initialize services
        self.news_scraper: Optional[NewsScraper] = None
        self.news_scheduler: Optional[NewsScheduler] = None

    def _load_channel_id(self) -> Optional[int]:
        """
        Load news channel ID from environment.

        Returns:
            Channel ID as int or None if not configured
        """
        channel_id_str: Optional[str] = os.getenv("NEWS_CHANNEL_ID")
        if channel_id_str and channel_id_str.isdigit():
            return int(channel_id_str)
        return None

    async def setup_hook(self) -> None:
        """
        Setup hook called when bot is starting.

        DESIGN: No commands to sync - purely automated bot
        This runs once when bot starts, before on_ready
        """
        logger.info("Bot setup complete - no commands to register (fully automated)")

    async def on_ready(self) -> None:
        """
        Event handler called when bot is ready.

        DESIGN: Initialize services and start automation immediately
        Bot automatically begins posting news on startup
        """
        logger.tree(
            f"Bot Ready: {self.user.name}",
            [
                ("Bot ID", str(self.user.id)),
                ("Guilds", str(len(self.guilds))),
                ("Mode", "Fully Automated"),
                (
                    "News Channel",
                    str(self.news_channel_id) if self.news_channel_id else "Not Set",
                ),
            ],
            emoji="✅",
        )

        # DESIGN: Initialize news scraper with async context manager
        # Ensures proper cleanup of aiohttp sessions
        self.news_scraper = NewsScraper()
        await self.news_scraper.__aenter__()

        # DESIGN: Initialize scheduler with callback to post_news method
        # Scheduler will call this method every hour automatically
        self.news_scheduler = NewsScheduler(self.post_news)

        # DESIGN: Always start scheduler on bot ready
        # Bot is 100% automated - no manual control needed
        # post_immediately=True for testing - will post right away then continue hourly
        await self.news_scheduler.start(post_immediately=True)
        logger.success("🤖 Automated news posting started - bot is fully autonomous")

        # Set bot presence
        await self.update_presence()

    async def update_presence(self, status_text: Optional[str] = None) -> None:
        """
        Update bot's Discord presence.

        Args:
            status_text: Custom status text, or None for default
        """
        if status_text is None:
            # DESIGN: Show next post time in bot presence
            # Users can see when next news update is coming
            if self.news_scheduler:
                next_post = self.news_scheduler.get_next_post_time()
                if next_post:
                    status_text = f"Next post: {next_post.strftime('%I:%M %p')}"
                else:
                    status_text = "📰 Automated News"
            else:
                status_text = "📰 Automated News"

        activity: discord.Activity = discord.Activity(
            type=discord.ActivityType.watching, name=status_text
        )
        await self.change_presence(activity=activity)

    async def post_news(self) -> None:
        """
        Post latest news articles to the news channel.

        DESIGN: Called by scheduler every hour automatically
        Fetches news, formats embeds, creates threads
        Handles all errors gracefully to keep scheduler running
        """
        if not self.news_channel_id:
            logger.error("NEWS_CHANNEL_ID not configured - cannot post news")
            return

        if not self.news_scraper:
            logger.error("News scraper not initialized")
            return

        try:
            # Fetch latest articles
            logger.info("📰 Fetching latest news articles...")
            articles: list[NewsArticle] = await self.news_scraper.fetch_latest_news(
                max_articles=3, hours_back=24
            )

            if not articles:
                logger.warning("No new articles found to post")
                return

            # Get news channel
            channel = self.get_channel(self.news_channel_id)
            if not channel:
                logger.error(f"News channel {self.news_channel_id} not found")
                return

            # DESIGN: Support both text channels and forum channels
            # Forum channels create thread posts, text channels send regular messages
            if isinstance(channel, discord.ForumChannel):
                # Post to forum channel
                for article in articles:
                    try:
                        await self._post_article_to_forum(channel, article)
                        # DESIGN: Small delay between posts to avoid rate limiting
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.error(f"Failed to post article '{article.title}': {e}")
                        continue
            elif isinstance(channel, discord.TextChannel):
                # Post to text channel
                for article in articles:
                    try:
                        await self._post_article(channel, article)
                        # DESIGN: Small delay between posts to avoid rate limiting
                        # Discord allows 5 messages per 5 seconds per channel
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.error(f"Failed to post article '{article.title}': {e}")
                        continue
            else:
                logger.error(f"Channel {self.news_channel_id} is not a text or forum channel")
                return

            logger.success(f"✅ Posted {len(articles)} news articles")

            # Update presence with new next post time
            await self.update_presence()

        except Exception as e:
            logger.error(f"Failed to post news: {e}")
            # DESIGN: Don't raise exception - let scheduler continue

    async def _post_article(
        self, channel: discord.TextChannel, article: NewsArticle
    ) -> None:
        """
        Post a single news article with embed and thread.

        Args:
            channel: Discord channel to post in
            article: NewsArticle object to post

        DESIGN: Creates beautiful embed with image, then creates thread for discussion
        Thread keeps channel clean while allowing per-article discussions
        """
        # Create embed
        embed: discord.Embed = discord.Embed(
            title=article.title,
            url=article.url,
            description=(
                article.summary[:500] + "..."
                if len(article.summary) > 500
                else article.summary
            ),
            color=discord.Color.blue(),
            timestamp=article.published_date,
        )

        # DESIGN: Add image if available
        # Images make embeds more engaging and professional
        if article.image_url:
            embed.set_image(url=article.image_url)

        # Add source in footer
        embed.set_footer(
            text=f"{article.source_emoji} {article.source}",
            icon_url=self.user.avatar.url if self.user.avatar else None,
        )

        # Post message
        message: discord.Message = await channel.send(embed=embed)

        # DESIGN: Create thread for discussion
        # Thread name limited to 100 characters (Discord limit)
        thread_name: str = (
            article.title[:97] + "..." if len(article.title) > 100 else article.title
        )

        try:
            thread: discord.Thread = await message.create_thread(
                name=thread_name,
                auto_archive_duration=1440,  # Archive after 24 hours
            )
            logger.info(f"📰 Posted: {article.title} (Thread: {thread.name})")
        except discord.HTTPException as e:
            logger.warning(f"Failed to create thread for '{article.title}': {e}")
            logger.info(f"📰 Posted: {article.title} (No thread)")

    async def _post_article_to_forum(
        self, channel: discord.ForumChannel, article: NewsArticle
    ) -> None:
        """
        Post a single news article to a forum channel.

        Args:
            channel: Discord forum channel to post in
            article: NewsArticle object to post

        DESIGN: Forum channels require thread creation with initial message
        Each article becomes a forum post (thread) with embed as first message
        """
        # DESIGN: Forum posts require thread name limited to 100 characters
        thread_name: str = (
            article.title[:97] + "..." if len(article.title) > 100 else article.title
        )

        # DESIGN: Post bilingual AI summaries with image embed
        # Arabic summary first (primary), then English
        # Much cleaner than truncated raw text

        # Create embed with image
        embed: discord.Embed = discord.Embed(
            color=discord.Color.blue(),
            timestamp=article.published_date,
        )

        # DESIGN: Add image if available
        # Images make posts more engaging and professional
        if article.image_url:
            embed.set_image(url=article.image_url)

        # Add source in footer
        embed.set_footer(
            text=f"{article.source_emoji} {article.source}",
            icon_url=self.user.avatar.url if self.user.avatar else None,
        )

        # DESIGN: Format bilingual summaries
        # Arabic first, then English
        # Each summary is 3-4 sentences from AI
        message_content: str = f"**{article.title}**\n\n"
        message_content += f"🇸🇾 **ملخص بالعربية:**\n{article.arabic_summary}\n\n"
        message_content += f"🇺🇸 **English Summary:**\n{article.english_summary}"

        # Ensure we don't exceed Discord's 2000 char limit
        if len(message_content) > 1990:
            message_content = message_content[:1990] + "..."

        try:
            # DESIGN: Create forum thread with bilingual summaries + image embed
            # Forum channels don't support sending messages directly - must create thread
            thread: discord.Thread = await channel.create_thread(
                name=thread_name,
                content=message_content,
                embed=embed,
                auto_archive_duration=1440,  # Archive after 24 hours
            )
            logger.info(f"📰 Posted forum thread: {article.title}")
        except discord.HTTPException as e:
            logger.error(f"Failed to create forum post for '{article.title}': {e}")

    async def close(self) -> None:
        """
        Cleanup when bot is shutting down.

        DESIGN: Properly close all services and sessions
        Prevents resource leaks and ensures state is saved
        """
        logger.info("Shutting down Othman Bot...")

        # Stop scheduler
        if self.news_scheduler and self.news_scheduler.is_running:
            await self.news_scheduler.stop()

        # Close news scraper session
        if self.news_scraper:
            await self.news_scraper.__aexit__(None, None, None)

        # Call parent close
        await super().close()

        logger.success("Bot shutdown complete")


# DESIGN: Export bot class for use in main.py
# Allows clean import: from src.bot import OthmanBot
__all__ = ["OthmanBot"]
