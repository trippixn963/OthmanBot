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
from src.services.soccer_scraper import SoccerScraper, SoccerArticle
from src.services.soccer_scheduler import SoccerScheduler
from src.services.gaming_scraper import GamingScraper, GamingArticle
from src.services.gaming_scheduler import GamingScheduler
from src.utils.retry import exponential_backoff
from src.data.team_tags import SOCCER_TEAM_TAG_IDS


class OthmanBot(commands.Bot):
    """Main Discord bot class for Othman News Bot."""

    def __init__(self) -> None:
        """Initialize the Othman bot with necessary intents and configuration."""
        # DESIGN: Minimal intents for automated posting and reaction management
        # guilds: For channel access and posting
        # reactions: For adding eyes emoji and cleaning up other reactions
        intents: discord.Intents = discord.Intents.default()
        intents.guilds = True
        intents.reactions = True

        super().__init__(
            command_prefix="!",  # Required but unused
            intents=intents,
            help_command=None,
        )

        # Load configuration from environment
        self.news_channel_id: Optional[int] = self._load_channel_id()
        self.soccer_channel_id: Optional[int] = self._load_soccer_channel_id()
        self.gaming_channel_id: Optional[int] = self._load_gaming_channel_id()

        # DESIGN: Track announcement message IDs for reaction management
        # Only eyes emoji (👀) allowed on announcement embeds
        # Set stores message IDs for efficient lookup in on_reaction_add
        self.announcement_messages: set[int] = set()

        # Initialize services
        self.news_scraper: Optional[NewsScraper] = None
        self.news_scheduler: Optional[NewsScheduler] = None
        self.soccer_scraper: Optional[SoccerScraper] = None
        self.soccer_scheduler: Optional[SoccerScheduler] = None
        self.gaming_scraper: Optional[GamingScraper] = None
        self.gaming_scheduler: Optional[GamingScheduler] = None

        # DESIGN: Background task for updating presence every minute
        # Shows live countdown to next post
        self.presence_task: Optional[asyncio.Task] = None

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

    def _load_soccer_channel_id(self) -> Optional[int]:
        """
        Load soccer channel ID from environment.

        Returns:
            Channel ID as int or None if not configured
        """
        channel_id_str: Optional[str] = os.getenv("SOCCER_CHANNEL_ID")
        if channel_id_str and channel_id_str.isdigit():
            return int(channel_id_str)
        return None

    def _load_gaming_channel_id(self) -> Optional[int]:
        """
        Load gaming channel ID from environment.

        Returns:
            Channel ID as int or None if not configured
        """
        channel_id_str: Optional[str] = os.getenv("GAMING_CHANNEL_ID")
        if channel_id_str and channel_id_str.isdigit():
            return int(channel_id_str)
        return None

    @property
    def general_channel_id(self) -> Optional[int]:
        """
        Get general channel ID from environment.

        Returns:
            Channel ID as int or None if not configured
        """
        channel_id_str: Optional[str] = os.getenv("GENERAL_CHANNEL_ID")
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
                (
                    "Soccer Channel",
                    str(self.soccer_channel_id) if self.soccer_channel_id else "Not Set",
                ),
                (
                    "Gaming Channel",
                    str(self.gaming_channel_id) if self.gaming_channel_id else "Not Set",
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
        # post_immediately=False ensures bot waits until next hour mark (e.g., 2:00, 3:00)
        # This maintains consistent hourly schedule even after restarts
        await self.news_scheduler.start(post_immediately=False)
        logger.success("🤖 Automated news posting started - bot is fully autonomous")

        # DESIGN: Initialize soccer scraper if soccer channel is configured
        # Soccer news posts every hour at :20 to SOCCER_CHANNEL_ID
        if self.soccer_channel_id:
            self.soccer_scraper = SoccerScraper()
            await self.soccer_scraper.__aenter__()

            # DESIGN: Initialize soccer scheduler with callback to post_soccer_news method
            # Scheduler will call this method every hour at :20 automatically
            self.soccer_scheduler = SoccerScheduler(self.post_soccer_news)

            # DESIGN: Start soccer scheduler - hourly at :20 past each hour
            # post_immediately=False to maintain consistent schedule (12:20, 1:20, 2:20, etc.)
            await self.soccer_scheduler.start(post_immediately=False)
            logger.success("⚽ Automated soccer news started - posting hourly at :20")
        else:
            logger.info("⚽ Soccer channel not configured - skipping soccer news automation")

        # DESIGN: Initialize gaming scraper if gaming channel is configured
        # Gaming news posts every hour at :40 to GAMING_CHANNEL_ID
        if self.gaming_channel_id:
            self.gaming_scraper = GamingScraper()
            await self.gaming_scraper.__aenter__()

            # DESIGN: Initialize gaming scheduler with callback to post_gaming_news method
            # Scheduler will call this method every hour at :40 automatically
            self.gaming_scheduler = GamingScheduler(self.post_gaming_news)

            # DESIGN: Start gaming scheduler - hourly at :40 past each hour
            # post_immediately=False to maintain consistent schedule (12:40, 1:40, 2:40, etc.)
            await self.gaming_scheduler.start(post_immediately=False)
            logger.success("🎮 Automated gaming news started - posting hourly at :40")
        else:
            logger.info("🎮 Gaming channel not configured - skipping gaming news automation")

        # Set bot presence
        await self.update_presence()

        # DESIGN: Start background task to update presence every minute
        # Shows live countdown that updates automatically
        # Timezone-agnostic relative time ("Next post in 45 minutes" → "Next post in 44 minutes")
        self.presence_task = asyncio.create_task(self._presence_update_loop())
        logger.info("🔄 Started presence update loop (updates every 60 seconds)")

    async def _presence_update_loop(self) -> None:
        """
        Background task that updates bot presence every minute.

        DESIGN: Shows live countdown to next post
        Updates every 60 seconds to keep time accurate
        Timezone-agnostic relative time for all users
        Runs continuously until bot shuts down
        """
        while True:
            try:
                await asyncio.sleep(60)  # Wait 60 seconds between updates
                await self.update_presence()
            except asyncio.CancelledError:
                logger.info("Presence update loop cancelled")
                break
            except Exception as e:
                logger.warning(f"Failed to update presence: {e}")
                # DESIGN: Continue loop even if one update fails
                # Don't let presence errors crash the background task

    async def update_presence(self, status_text: Optional[str] = None) -> None:
        """
        Update bot's Discord presence.

        Args:
            status_text: Custom status text, or None for default
        """
        if status_text is None:
            # DESIGN: Show whichever post is coming next (news, soccer, or gaming)
            # News posts at :00 (1:00, 2:00, 3:00, etc.)
            # Soccer posts at :20 (1:20, 2:20, 3:20, etc.)
            # Gaming posts at :40 (1:40, 2:40, 3:40, etc.)
            # Display the soonest upcoming post with appropriate emoji
            from datetime import datetime
            now = datetime.now()

            # Get next post times from all schedulers
            next_news = self.news_scheduler.get_next_post_time() if self.news_scheduler else None
            next_soccer = self.soccer_scheduler.get_next_post_time() if self.soccer_scheduler else None
            next_gaming = self.gaming_scheduler.get_next_post_time() if self.gaming_scheduler else None

            # Find which post is soonest
            soonest_post = None
            post_type = "news"  # Default to news

            # Collect all upcoming posts
            upcoming_posts = []
            if next_news:
                upcoming_posts.append((next_news, "news"))
            if next_soccer:
                upcoming_posts.append((next_soccer, "soccer"))
            if next_gaming:
                upcoming_posts.append((next_gaming, "gaming"))

            # Sort by time to find soonest
            if upcoming_posts:
                upcoming_posts.sort(key=lambda x: x[0])
                soonest_post, post_type = upcoming_posts[0]

            # Generate status text based on soonest post
            if soonest_post:
                minutes_until = int((soonest_post - now).total_seconds() / 60)
                emoji = "📰" if post_type == "news" else ("⚽" if post_type == "soccer" else "🎮")

                if minutes_until <= 0:
                    status_text = f"{emoji} Posting now..."
                elif minutes_until == 1:
                    status_text = f"{emoji} Post in 1 minute"
                elif minutes_until < 60:
                    status_text = f"{emoji} Post in {minutes_until} minutes"
                else:
                    status_text = f"{emoji} Posting hourly"
            else:
                status_text = "📰 Automated News"

        activity: discord.Activity = discord.Activity(
            type=discord.ActivityType.watching, name=status_text
        )
        await self.change_presence(activity=activity)

    @exponential_backoff(max_retries=3, base_delay=10)
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
            # Fetch latest articles (or backfill from older ones)
            logger.info("📰 Fetching latest news articles...")
            articles: list[NewsArticle] = await self.news_scraper.fetch_latest_news(
                max_articles=1  # hours_back defaults to 168 (7 days) for backfill
            )

            if not articles:
                logger.warning("No new articles found to post")
                return

            # DESIGN: Post ONLY ONE article per hour
            # Get the most recent article with media
            article = articles[0]

            # Get news channel
            channel = self.get_channel(self.news_channel_id)
            if not channel:
                logger.error(f"News channel {self.news_channel_id} not found")
                return

            # DESIGN: Support both text channels and forum channels
            # Forum channels create thread posts, text channels send regular messages
            if isinstance(channel, discord.ForumChannel):
                # Post to forum channel
                try:
                    await self._post_article_to_forum(channel, article)
                except Exception as e:
                    logger.error(f"Failed to post article '{article.title}': {e}")
                    return
            elif isinstance(channel, discord.TextChannel):
                # Post to text channel
                try:
                    await self._post_article(channel, article)
                except Exception as e:
                    logger.error(f"Failed to post article '{article.title}': {e}")
                    return
            else:
                logger.error(f"Channel {self.news_channel_id} is not a text or forum channel")
                return

            logger.success(f"✅ Posted 1 news article")

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
        Each article becomes a forum post (thread) with uploaded image file
        """
        # DESIGN: Download image and video, upload to Discord, then delete locally
        # User requirement: No media links, upload actual files
        import aiohttp
        import os
        from pathlib import Path

        image_file: Optional[discord.File] = None
        temp_image_path: Optional[str] = None
        video_file: Optional[discord.File] = None
        temp_video_path: Optional[str] = None

        # Create temp directory for media
        temp_dir: Path = Path("data/temp_media")
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Download image
        if article.image_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(article.image_url, timeout=10) as response:
                        if response.status == 200:
                            # Get file extension from URL or content type
                            ext: str = ".jpg"
                            if "." in article.image_url:
                                url_ext = article.image_url.split(".")[-1].split("?")[0].lower()
                                if url_ext in ["jpg", "jpeg", "png", "webp", "gif"]:
                                    ext = f".{url_ext}"

                            # Save to temp file
                            temp_image_path = str(temp_dir / f"temp_img_{hash(article.url)}{ext}")
                            content: bytes = await response.read()

                            with open(temp_image_path, "wb") as f:
                                f.write(content)

                            # Create Discord file object
                            image_file = discord.File(temp_image_path, filename=f"article{ext}")
                            logger.info(f"Downloaded image for article: {article.title[:30]}")
            except Exception as e:
                logger.warning(f"Failed to download image for '{article.title}': {e}")

        # DESIGN: Download video if it exists (direct video files only, not embeds)
        # Only download actual video files (.mp4, .webm, .mov), skip platform embeds
        if article.video_url:
            try:
                # Check if it's a direct video file (not an embed)
                is_direct_video = any(ext in article.video_url.lower() for ext in [".mp4", ".webm", ".mov"])

                if is_direct_video:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(article.video_url, timeout=30) as response:
                            if response.status == 200:
                                # Get file extension
                                ext: str = ".mp4"
                                if "." in article.video_url:
                                    url_ext = article.video_url.split(".")[-1].split("?")[0].lower()
                                    if url_ext in ["mp4", "webm", "mov"]:
                                        ext = f".{url_ext}"

                                # DESIGN: Discord has file size limits (8MB for regular, 25MB for Nitro)
                                # Check content length before downloading
                                content_length = response.headers.get("Content-Length")
                                if content_length and int(content_length) > 25 * 1024 * 1024:  # 25MB limit
                                    logger.warning(f"Video too large ({int(content_length)/1024/1024:.1f}MB) for '{article.title}', skipping")
                                else:
                                    # Save to temp file
                                    temp_video_path = str(temp_dir / f"temp_vid_{hash(article.url)}{ext}")
                                    content: bytes = await response.read()

                                    # Double check actual size
                                    if len(content) > 25 * 1024 * 1024:
                                        logger.warning(f"Video file size ({len(content)/1024/1024:.1f}MB) exceeds Discord limit for '{article.title}', skipping")
                                    else:
                                        with open(temp_video_path, "wb") as f:
                                            f.write(content)

                                        # Create Discord file object
                                        video_file = discord.File(temp_video_path, filename=f"video{ext}")
                                        logger.info(f"Downloaded video for article: {article.title[:30]} ({len(content)/1024/1024:.1f}MB)")
                else:
                    logger.info(f"Video is an embed (not downloadable): {article.video_url[:50]}")
            except Exception as e:
                logger.warning(f"Failed to download video for '{article.title}': {e}")

        # DESIGN: Format bilingual summaries with beautiful styling
        # Image will be uploaded as attachment instead of URL
        # Use Discord markdown for professional formatting

        # Get current date for thread title (MM-DD-YY format)
        from datetime import datetime
        post_date: str = datetime.now().strftime("%m-%d-%y")

        # DESIGN: Build footer FIRST to calculate remaining space for summaries
        # This ensures the URL is never truncated (which breaks the "Read Full Article" link)
        published_date_str: str = article.published_date.strftime("%B %d, %Y") if article.published_date else "N/A"

        footer: str = ""
        footer += f"📰 **Source:** {article.source_emoji} {article.source} • 🔗 **[Read Full Article](<{article.url}>)**\n"
        footer += f"📅 **Published:** {published_date_str}\n\n"
        footer += "-# ⚠️ This news article was automatically generated and posted by an automated bot. "
        footer += "The content is sourced from various news outlets and summarized using AI.\n\n"
        footer += "-# Bot developed by حَـــــنَّـــــا."

        # Calculate maximum space for summaries (Discord limit minus footer)
        # Reserve ~400 chars for key quote, headers, dividers, and safety margin
        max_summary_space: int = 2000 - len(footer) - 400

        # Truncate summaries if they're too long to fit
        arabic_summary: str = article.arabic_summary
        english_summary: str = article.english_summary

        # If combined summaries exceed space, truncate each proportionally
        combined_length: int = len(arabic_summary) + len(english_summary)
        if combined_length > max_summary_space:
            max_each: int = max_summary_space // 2
            if len(arabic_summary) > max_each:
                arabic_summary = arabic_summary[:max_each-3] + "..."
            if len(english_summary) > max_each:
                english_summary = english_summary[:max_each-3] + "..."

        # Build message with professional formatting
        message_content: str = ""

        # DESIGN: Key quote at the top for better engagement
        # Extract first sentence as highlight to hook readers immediately
        # If first sentence is too long (>250 chars), truncate with ellipsis
        first_sentence: str = english_summary.split('.')[0].strip()
        if len(first_sentence) > 250:
            first_sentence = first_sentence[:247].strip() + '...'
        else:
            first_sentence = first_sentence + '.'

        # DESIGN: Always show key quote if we have a valid first sentence
        # Changed from requiring < 200 chars to always showing (with truncation)
        if len(first_sentence) > 20:
            message_content += f"> 💬 *\"{first_sentence}\"*\n\n"
            message_content += "─────────────\n\n"

        # DESIGN: Arabic summary section with emoji flag header
        # Makes it clear which language is which
        message_content += f"🇸🇾 **Arabic Summary**\n{arabic_summary}\n\n"
        message_content += "─────────────\n\n"

        # DESIGN: English translation section with emoji flag header
        message_content += f"🇬🇧 **English Translation**\n{english_summary}\n\n"
        message_content += "─────────────\n\n"

        # Add the footer (with URL guaranteed to be complete)
        message_content += footer

        # Update thread name to include date
        thread_name = f"📅 {post_date} | {article.title}"
        if len(thread_name) > 100:
            thread_name = f"📅 {post_date} | {article.title[:80]}..."

        try:
            # DESIGN: Create forum thread with uploaded media files (image and video) and category tag
            # Media is attached as files, not URL links
            # Apply category tag if one was determined by AI
            files: list[discord.File] = []
            if image_file:
                files.append(image_file)
            if video_file:
                files.append(video_file)

            # DESIGN: Build list of tags to apply to the forum thread
            # If AI categorized the article, apply the corresponding Discord tag
            # Tags help organize forum by topic (military, politics, etc.)
            applied_tags: list[discord.ForumTag] = []
            if article.category_tag_id:
                # Find the tag object from channel's available tags
                for tag in channel.available_tags:
                    if tag.id == article.category_tag_id:
                        applied_tags.append(tag)
                        break

            # DESIGN: create_thread returns ThreadWithMessage, extract thread
            # ThreadWithMessage contains both the thread and initial message
            thread_with_msg = await channel.create_thread(
                name=thread_name,
                content=message_content,
                files=files,
                applied_tags=applied_tags,  # Apply category tag automatically
                auto_archive_duration=1440,  # Archive after 24 hours
            )
            thread: discord.Thread = thread_with_msg.thread

            tag_info: str = f" (Tag: {applied_tags[0].name})" if applied_tags else " (No tag)"
            media_info: str = f"Image: {'Yes' if image_file else 'No'}, Video: {'Yes' if video_file else 'No'}"
            logger.info(f"📰 Posted forum thread: {article.title} ({media_info}){tag_info}")

            # DESIGN: Mark article ID as posted to prevent duplicates
            # Critical: Add to cache immediately after successful post
            # Without this, bot will repost same article every hour!
            # CRITICAL: Use article ID instead of full URL for reliability
            # Article IDs are stable and unique, unlike URLs which can vary
            if self.news_scraper:
                article_id: str = self.news_scraper._extract_article_id(article.url)
                self.news_scraper.fetched_urls.add(article_id)
                self.news_scraper._save_posted_urls()  # Persist to disk
                logger.info(f"✅ Marked article ID as posted: {article_id} (URL: {article.url[:50]})")

            # DESIGN: Send announcement embed to general channel with link to forum post
            # This notifies users in main chat about new news posts
            logger.info(f"🔍 Checking general_channel_id: {self.general_channel_id}")
            if self.general_channel_id:
                await self._send_general_announcement(thread, article, applied_tags)
            else:
                logger.warning("❌ General channel ID not configured - skipping announcement")
        except discord.HTTPException as e:
            logger.error(f"Failed to create forum post for '{article.title}': {e}")
        finally:
            # DESIGN: Clean up temp media files after upload
            # Delete local files to save disk space
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.remove(temp_image_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp image {temp_image_path}: {e}")

            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp video {temp_video_path}: {e}")

    async def _send_general_announcement(
        self, thread: discord.Thread, article: NewsArticle, applied_tags: list[discord.ForumTag]
    ) -> None:
        """
        Send news announcement embed to general chat channel.

        Args:
            thread: Forum thread that was created
            article: NewsArticle that was posted
            applied_tags: Tags applied to the forum thread

        DESIGN: Send beautiful embed to general chat with link to forum post
        This notifies users about new news without cluttering the forum
        """
        logger.info(f"🔔 Attempting to send announcement to general channel (ID: {self.general_channel_id})")

        general_channel = self.get_channel(self.general_channel_id)
        if not general_channel:
            logger.warning(f"❌ General channel {self.general_channel_id} not found")
            return

        if not isinstance(general_channel, discord.TextChannel):
            logger.warning(f"❌ Channel {self.general_channel_id} is not a text channel (type: {type(general_channel).__name__})")
            return

        logger.info(f"✅ Found general channel: {general_channel.name}")

        try:
            # DESIGN: Create teaser embed with short preview and button to forum
            # Short description (first 100 chars) to give a preview
            # Button drives users to click through to forum thread
            teaser: str = article.english_summary[:100] + "..." if len(article.english_summary) > 100 else article.english_summary

            embed: discord.Embed = discord.Embed(
                title=article.title,  # No emoji in title
                description=teaser,
                color=discord.Color.blue(),
            )

            # DESIGN: Add developer footer with avatar (matches TahaBot/AzabBot format)
            # Fetch developer user for avatar (use fetch_user for API call, not cache-only get_user)
            developer_id_str: Optional[str] = os.getenv("DEVELOPER_ID")
            developer_avatar_url: str = self.user.display_avatar.url  # Fallback to bot avatar

            if developer_id_str and developer_id_str.isdigit():
                try:
                    developer = await self.fetch_user(int(developer_id_str))
                    if developer:
                        developer_avatar_url = developer.display_avatar.url
                        logger.info(f"✅ Fetched developer avatar for footer: {developer.name}")
                except Exception as e:
                    logger.warning(f"Failed to fetch developer user {developer_id_str}: {e}")

            embed.set_footer(
                text="Developed By: حَـــــنَّـــــا",
                icon_url=developer_avatar_url
            )

            # Add thumbnail if article has image
            if article.image_url:
                embed.set_thumbnail(url=article.image_url)

            # DESIGN: Create "Read Full Article" button that links to forum thread
            # Button uses discord.ui.View and discord.ui.Button with URL
            view = discord.ui.View()
            button = discord.ui.Button(
                label="📰 Read Full Article",
                style=discord.ButtonStyle.link,
                url=thread.jump_url
            )
            view.add_item(button)

            # Send embed with button (no reactions)
            message: discord.Message = await general_channel.send(embed=embed, view=view)

            # DESIGN: Track message ID for reaction blocking
            # Block ALL reactions on announcement embeds
            self.announcement_messages.add(message.id)

            logger.info(f"📣 Sent announcement to general chat for: {article.title[:50]}")

        except discord.HTTPException as e:
            logger.error(f"Failed to send general announcement for '{article.title}': {e}")

    async def _send_soccer_announcement(
        self, thread: discord.Thread, article: "SoccerArticle", applied_tags: list[discord.Object]
    ) -> None:
        """
        Send soccer announcement embed to general chat channel.

        Args:
            thread: Forum thread that was created
            article: SoccerArticle that was posted
            applied_tags: Tags applied to the forum thread (team tags)

        DESIGN: Identical to news announcement for consistency
        Same embed format, same button style, same notification flow
        """
        logger.info(f"🔔 Attempting to send soccer announcement to general channel (ID: {self.general_channel_id})")

        general_channel = self.get_channel(self.general_channel_id)
        if not general_channel:
            logger.warning(f"❌ General channel {self.general_channel_id} not found")
            return

        if not isinstance(general_channel, discord.TextChannel):
            logger.warning(f"❌ Channel {self.general_channel_id} is not a text channel (type: {type(general_channel).__name__})")
            return

        logger.info(f"✅ Found general channel: {general_channel.name}")

        try:
            # DESIGN: Create teaser embed with short preview and button to forum
            # Identical format to news notifications
            teaser: str = article.english_summary[:100] + "..." if len(article.english_summary) > 100 else article.english_summary

            embed: discord.Embed = discord.Embed(
                title=article.title,  # No emoji in title
                description=teaser,
                color=discord.Color.green(),  # Green for soccer (vs blue for news)
            )

            # DESIGN: Add developer footer with avatar (matches news format)
            developer_id_str: Optional[str] = os.getenv("DEVELOPER_ID")
            developer_avatar_url: str = self.user.display_avatar.url  # Fallback to bot avatar

            if developer_id_str and developer_id_str.isdigit():
                try:
                    developer = await self.fetch_user(int(developer_id_str))
                    if developer:
                        developer_avatar_url = developer.display_avatar.url
                        logger.info(f"✅ Fetched developer avatar for soccer footer: {developer.name}")
                except Exception as e:
                    logger.warning(f"Failed to fetch developer user {developer_id_str}: {e}")

            embed.set_footer(
                text="Developed By: حَـــــنَّـــــا",
                icon_url=developer_avatar_url
            )

            # Add thumbnail if article has image
            if article.image_url:
                embed.set_thumbnail(url=article.image_url)

            # DESIGN: Create "Read Full Article" button that links to forum thread
            # Identical button style to news notifications
            view = discord.ui.View()
            button = discord.ui.Button(
                label="⚽ Read Full Article",  # Soccer emoji instead of news emoji
                style=discord.ButtonStyle.link,
                url=thread.jump_url
            )
            view.add_item(button)

            # Send embed with button (no reactions)
            message: discord.Message = await general_channel.send(embed=embed, view=view)

            # DESIGN: Track message ID for reaction blocking
            # Block ALL reactions on announcement embeds (same as news)
            self.announcement_messages.add(message.id)

            logger.info(f"📣 Sent soccer announcement to general chat for: {article.title[:50]}")

        except discord.HTTPException as e:
            logger.error(f"Failed to send soccer announcement for '{article.title}': {e}")

    async def _send_gaming_announcement(
        self, thread: discord.Thread, article: "GamingArticle"
    ) -> None:
        """
        Send gaming announcement embed to general chat channel.

        Args:
            thread: Forum thread that was created
            article: GamingArticle that was posted

        DESIGN: Identical to news/soccer announcement for consistency
        Same embed format, same button style, same notification flow
        Uses purple color to distinguish gaming from news (blue) and soccer (green)
        """
        logger.info(f"🔔 Attempting to send gaming announcement to general channel (ID: {self.general_channel_id})")

        general_channel = self.get_channel(self.general_channel_id)
        if not general_channel:
            logger.warning(f"❌ General channel {self.general_channel_id} not found")
            return

        if not isinstance(general_channel, discord.TextChannel):
            logger.warning(f"❌ Channel {self.general_channel_id} is not a text channel (type: {type(general_channel).__name__})")
            return

        logger.info(f"✅ Found general channel: {general_channel.name}")

        try:
            # DESIGN: Create teaser embed with short preview and button to forum
            # Identical format to news/soccer notifications
            teaser: str = article.english_summary[:100] + "..." if len(article.english_summary) > 100 else article.english_summary

            embed: discord.Embed = discord.Embed(
                title=article.title,  # No emoji in title
                description=teaser,
                color=discord.Color.purple(),  # Purple for gaming (vs blue for news, green for soccer)
            )

            # DESIGN: Add developer footer with avatar (matches news/soccer format)
            developer_id_str: Optional[str] = os.getenv("DEVELOPER_ID")
            developer_avatar_url: str = self.user.display_avatar.url  # Fallback to bot avatar

            if developer_id_str and developer_id_str.isdigit():
                try:
                    developer = await self.fetch_user(int(developer_id_str))
                    if developer:
                        developer_avatar_url = developer.display_avatar.url
                        logger.info(f"✅ Fetched developer avatar for gaming footer: {developer.name}")
                except Exception as e:
                    logger.warning(f"Failed to fetch developer user {developer_id_str}: {e}")

            embed.set_footer(
                text="Developed By: حَـــــنَّـــــا",
                icon_url=developer_avatar_url
            )

            # Add thumbnail if article has image
            if article.image_url:
                embed.set_thumbnail(url=article.image_url)

            # DESIGN: Create "Read Full Article" button that links to forum thread
            # Identical button style to news/soccer notifications
            view = discord.ui.View()
            button = discord.ui.Button(
                label="🎮 Read Full Article",  # Gaming emoji instead of news/soccer emoji
                style=discord.ButtonStyle.link,
                url=thread.jump_url
            )
            view.add_item(button)

            # Send embed with button (no reactions)
            message: discord.Message = await general_channel.send(embed=embed, view=view)

            # DESIGN: Track message ID for reaction blocking
            # Block ALL reactions on announcement embeds (same as news/soccer)
            self.announcement_messages.add(message.id)

            logger.info(f"📣 Sent gaming announcement to general chat for: {article.title[:50]}")

        except discord.HTTPException as e:
            logger.error(f"Failed to send gaming announcement for '{article.title}': {e}")

    @exponential_backoff(max_retries=3, base_delay=10)
    async def post_soccer_news(self) -> None:
        """
        Post latest soccer news articles to the soccer channel.

        DESIGN: Called by soccer scheduler every 3 hours automatically
        Fetches soccer news, formats embeds, creates forum posts
        Handles all errors gracefully to keep scheduler running
        """
        if not self.soccer_channel_id:
            logger.error("SOCCER_CHANNEL_ID not configured - cannot post soccer news")
            return

        if not self.soccer_scraper:
            logger.error("Soccer scraper not initialized")
            return

        try:
            # Fetch latest soccer articles (or backfill from older ones)
            logger.info("⚽ Fetching latest soccer news articles...")
            articles: list[SoccerArticle] = await self.soccer_scraper.fetch_latest_soccer_news(
                max_articles=1, hours_back=24  # Look back 24 hours for soccer news
            )

            if not articles:
                logger.warning("No new soccer articles found to post")
                return

            # DESIGN: Post ONLY ONE article per 3-hour interval
            # Get the most recent article with media
            article = articles[0]

            # Get soccer channel
            channel = self.get_channel(self.soccer_channel_id)
            if not channel:
                logger.error(f"Soccer channel {self.soccer_channel_id} not found")
                return

            # DESIGN: Support both text channels and forum channels
            # Forum channels create thread posts, text channels send regular messages
            if isinstance(channel, discord.ForumChannel):
                # Post to forum channel
                try:
                    await self._post_soccer_article_to_forum(channel, article)
                except Exception as e:
                    logger.error(f"Failed to post soccer article '{article.title}': {e}")
                    return
            elif isinstance(channel, discord.TextChannel):
                # Post to text channel
                try:
                    await self._post_soccer_article(channel, article)
                except Exception as e:
                    logger.error(f"Failed to post soccer article '{article.title}': {e}")
                    return
            else:
                logger.error(f"Soccer channel {self.soccer_channel_id} is not a text or forum channel")
                return

            logger.success(f"✅ Posted 1 soccer article")

        except Exception as e:
            logger.error(f"Failed to post soccer news: {e}")
            # DESIGN: Don't raise exception - let scheduler continue

    async def _post_soccer_article(
        self, channel: discord.TextChannel, article: SoccerArticle
    ) -> None:
        """
        Post a single soccer news article with embed.

        Args:
            channel: Discord channel to post in
            article: SoccerArticle object to post
        """
        # Create embed
        embed: discord.Embed = discord.Embed(
            title=article.title,
            url=article.url,
            description=article.summary[:500] + "..." if len(article.summary) > 500 else article.summary,
            color=discord.Color.green(),  # Green for soccer
            timestamp=article.published_date,
        )

        # Add image if available
        if article.image_url:
            embed.set_image(url=article.image_url)

        # Add source in footer
        embed.set_footer(
            text=f"{article.source_emoji} {article.source}",
            icon_url=self.user.avatar.url if self.user.avatar else None,
        )

        # Post message
        await channel.send(embed=embed)
        logger.info(f"⚽ Posted soccer: {article.title}")

    async def _post_soccer_article_to_forum(
        self, channel: discord.ForumChannel, article: SoccerArticle
    ) -> None:
        """
        Post a single soccer news article to a forum channel.

        Args:
            channel: Discord forum channel to post in
            article: SoccerArticle object to post
        """
        # DESIGN: Download image, upload to Discord, then delete locally
        import aiohttp
        from pathlib import Path

        image_file: Optional[discord.File] = None
        temp_image_path: Optional[str] = None

        # Create temp directory for media
        temp_dir: Path = Path("data/temp_media")
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Download image
        if article.image_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(article.image_url, timeout=10) as response:
                        if response.status == 200:
                            ext: str = ".jpg"
                            if "." in article.image_url:
                                url_ext = article.image_url.split(".")[-1].split("?")[0].lower()
                                if url_ext in ["jpg", "jpeg", "png", "webp", "gif"]:
                                    ext = f".{url_ext}"

                            temp_image_path = str(temp_dir / f"temp_soccer_{hash(article.url)}{ext}")
                            content: bytes = await response.read()

                            with open(temp_image_path, "wb") as f:
                                f.write(content)

                            image_file = discord.File(temp_image_path, filename=f"soccer{ext}")
                            logger.info(f"⚽ Downloaded image for soccer article: {article.title[:30]}")
            except Exception as e:
                logger.warning(f"Failed to download image for '{article.title}': {e}")

        try:
            # DESIGN: Format bilingual summaries with beautiful styling (EXACT same as news)
            # Image will be uploaded as attachment instead of URL
            # Use Discord markdown for professional formatting

            # DESIGN: Build footer FIRST to calculate remaining space for summaries
            # This ensures the URL is never truncated (which breaks the "Read Full Article" link)
            published_date_str: str = article.published_date.strftime("%B %d, %Y") if article.published_date else "N/A"

            footer: str = ""
            footer += f"📰 **Source:** {article.source_emoji} {article.source} • 🔗 **[Read Full Article](<{article.url}>)**\n"
            footer += f"📅 **Published:** {published_date_str}\n\n"
            footer += "-# ⚠️ This news article was automatically generated and posted by an automated bot. "
            footer += "The content is sourced from various news outlets and summarized using AI.\n\n"
            footer += "-# Bot developed by حَـــــنَّـــــا."

            # Calculate maximum space for summaries (Discord limit minus footer)
            # Reserve ~100 chars for headers, dividers, and safety margin
            max_summary_space: int = 2000 - len(footer) - 400

            # Truncate summaries if they're too long to fit
            arabic_summary: str = article.arabic_summary
            english_summary: str = article.english_summary

            # If combined summaries exceed space, truncate each proportionally
            combined_length: int = len(arabic_summary) + len(english_summary)
            if combined_length > max_summary_space:
                max_each: int = max_summary_space // 2
                if len(arabic_summary) > max_each:
                    arabic_summary = arabic_summary[:max_each-3] + "..."
                if len(english_summary) > max_each:
                    english_summary = english_summary[:max_each-3] + "..."

            # Build message with professional formatting
            message_content: str = ""

            # DESIGN: Key quote at the top for better engagement
            # Extract first sentence as highlight to hook readers immediately
            # If first sentence is too long (>250 chars), truncate with ellipsis
            first_sentence: str = english_summary.split('.')[0].strip()
            if len(first_sentence) > 250:
                first_sentence = first_sentence[:247].strip() + '...'
            else:
                first_sentence = first_sentence + '.'

            # DESIGN: Always show key quote if we have a valid first sentence
            # Changed from requiring < 200 chars to always showing (with truncation)
            if len(first_sentence) > 20:
                message_content += f"> 💬 *\"{first_sentence}\"*\n\n"
                message_content += "─────────────\n\n"

            # DESIGN: Arabic summary section with emoji flag header
            # Makes it clear which language is which
            message_content += f"🇸🇾 **Arabic Summary**\n{arabic_summary}\n\n"
            message_content += "─────────────\n\n"

            # DESIGN: English translation section with emoji flag header
            message_content += f"🇬🇧 **English Translation**\n{english_summary}\n\n"
            message_content += "─────────────\n\n"

            # Add the footer (with URL that must not be truncated)
            message_content += footer

            full_content: str = message_content

            # DESIGN: Get team tag ID from AI-detected team name
            # Look up Discord forum tag ID for the detected team
            # Apply tag to forum thread for automatic categorization
            applied_tags: list[discord.Object] = []
            if article.team_tag and article.team_tag in SOCCER_TEAM_TAG_IDS:
                tag_id: int = SOCCER_TEAM_TAG_IDS[article.team_tag]
                applied_tags.append(discord.Object(id=tag_id))
                logger.info(f"⚽ Applying team tag: {article.team_tag} (ID: {tag_id})")
            else:
                logger.warning(f"⚽ No valid team tag for article: {article.team_tag}")

            # Create forum thread with image and team tag
            files_to_upload: list[discord.File] = [image_file] if image_file else []

            # DESIGN: Format thread name with date emoji to match news format
            # Example: "📅 11-19-25 | Manchester United Transfer News"
            from datetime import datetime
            post_date: str = datetime.now().strftime("%m-%d-%y")
            thread_name: str = f"📅 {post_date} | {article.title}"
            if len(thread_name) > 100:
                thread_name = f"📅 {post_date} | {article.title[:80]}..."

            thread: discord.Thread
            message: discord.Message

            thread, message = await channel.create_thread(
                name=thread_name,
                content=full_content,
                files=files_to_upload,
                applied_tags=applied_tags,
            )

            # DESIGN: Mark article ID as posted immediately after forum thread creation
            # Prevents duplicate posts on next hourly run
            # CRITICAL: Use article ID instead of full URL for reliability
            article_id: str = self.soccer_scraper._extract_article_id(article.url)
            self.soccer_scraper.fetched_urls.add(article_id)
            self.soccer_scraper._save_posted_urls()
            logger.info(f"⚽ Marked soccer article ID as posted: {article_id} (URL: {article.url[:50]})")

            logger.info(f"⚽ Posted soccer forum thread: {article.title}")

            # DESIGN: Send announcement embed to general channel with link to forum post
            # Same notification system as news posts for consistency
            logger.info(f"🔍 Checking general_channel_id for soccer announcement: {self.general_channel_id}")
            if self.general_channel_id:
                await self._send_soccer_announcement(thread, article, applied_tags)
            else:
                logger.warning("❌ General channel ID not configured - skipping soccer announcement")

        finally:
            # Clean up temp image file
            if temp_image_path and Path(temp_image_path).exists():
                try:
                    Path(temp_image_path).unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp soccer image: {e}")

    @exponential_backoff(max_retries=3, base_delay=10)
    async def post_gaming_news(self) -> None:
        """
        Post latest gaming news articles to the gaming channel.

        DESIGN: Called by gaming scheduler every hour automatically
        Fetches gaming news, formats embeds, creates forum posts
        Handles all errors gracefully to keep scheduler running
        """
        if not self.gaming_channel_id:
            logger.error("GAMING_CHANNEL_ID not configured - cannot post gaming news")
            return

        if not self.gaming_scraper:
            logger.error("Gaming scraper not initialized")
            return

        try:
            # Fetch latest gaming articles (or backfill from older ones)
            logger.info("🎮 Fetching latest gaming news articles...")
            articles: list[GamingArticle] = await self.gaming_scraper.fetch_latest_gaming_news(
                max_articles=1, hours_back=24  # Look back 24 hours for gaming news
            )

            if not articles:
                logger.warning("No new gaming articles found to post")
                return

            # DESIGN: Post ONLY ONE article per hour
            # Get the most recent article with media
            article = articles[0]

            # Get gaming channel
            channel = self.get_channel(self.gaming_channel_id)
            if not channel:
                logger.error(f"Gaming channel {self.gaming_channel_id} not found")
                return

            # DESIGN: Support both text channels and forum channels
            # Forum channels create thread posts, text channels send regular messages
            if isinstance(channel, discord.ForumChannel):
                # Post to forum channel
                try:
                    await self._post_gaming_article_to_forum(channel, article)
                except Exception as e:
                    logger.error(f"Failed to post gaming article '{article.title}': {e}")
                    return
            elif isinstance(channel, discord.TextChannel):
                # Post to text channel
                try:
                    await self._post_gaming_article(channel, article)
                except Exception as e:
                    logger.error(f"Failed to post gaming article '{article.title}': {e}")
                    return
            else:
                logger.error(f"Gaming channel {self.gaming_channel_id} is not a text or forum channel")
                return

            logger.success(f"✅ Posted 1 gaming article")

        except Exception as e:
            logger.error(f"Failed to post gaming news: {e}")
            # DESIGN: Don't raise exception - let scheduler continue

    async def _post_gaming_article(
        self, channel: discord.TextChannel, article: GamingArticle
    ) -> None:
        """
        Post a single gaming news article with embed.

        Args:
            channel: Discord channel to post in
            article: GamingArticle object to post
        """
        # Create embed
        embed: discord.Embed = discord.Embed(
            title=article.title,
            url=article.url,
            description=article.summary[:500] + "..." if len(article.summary) > 500 else article.summary,
            color=discord.Color.purple(),  # Purple for gaming
            timestamp=article.published_date,
        )

        # Add image if available
        if article.image_url:
            embed.set_image(url=article.image_url)

        # Add source in footer
        embed.set_footer(
            text=f"{article.source_emoji} {article.source}",
            icon_url=self.user.avatar.url if self.user.avatar else None,
        )

        # Post message
        await channel.send(embed=embed)
        logger.info(f"🎮 Posted gaming: {article.title}")

    async def _post_gaming_article_to_forum(
        self, channel: discord.ForumChannel, article: GamingArticle
    ) -> None:
        """
        Post a single gaming news article to a forum channel.

        Args:
            channel: Discord forum channel to post in
            article: GamingArticle object to post
        """
        # DESIGN: Download image, upload to Discord, then delete locally
        import aiohttp
        from pathlib import Path

        image_file: Optional[discord.File] = None
        temp_image_path: Optional[str] = None

        # Create temp directory for media
        temp_dir: Path = Path("data/temp_media")
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Download image
        if article.image_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(article.image_url, timeout=10) as response:
                        if response.status == 200:
                            ext: str = ".jpg"
                            if "." in article.image_url:
                                url_ext = article.image_url.split(".")[-1].split("?")[0].lower()
                                if url_ext in ["jpg", "jpeg", "png", "webp", "gif"]:
                                    ext = f".{url_ext}"

                            temp_image_path = str(temp_dir / f"temp_gaming_{hash(article.url)}{ext}")
                            content: bytes = await response.read()

                            with open(temp_image_path, "wb") as f:
                                f.write(content)

                            image_file = discord.File(temp_image_path, filename=f"gaming{ext}")
                            logger.info(f"🎮 Downloaded image for gaming article: {article.title[:30]}")
            except Exception as e:
                logger.warning(f"Failed to download image for '{article.title}': {e}")

        try:
            # DESIGN: Format bilingual summaries with beautiful styling (EXACT same as news)
            # Image will be uploaded as attachment instead of URL
            # Use Discord markdown for professional formatting

            # DESIGN: Build footer FIRST to calculate remaining space for summaries
            # This ensures the URL is never truncated (which breaks the "Read Full Article" link)
            published_date_str: str = article.published_date.strftime("%B %d, %Y") if article.published_date else "N/A"

            footer: str = ""
            footer += f"📰 **Source:** {article.source_emoji} {article.source} • 🔗 **[Read Full Article](<{article.url}>)**\n"
            footer += f"📅 **Published:** {published_date_str}\n\n"
            footer += "-# ⚠️ This news article was automatically generated and posted by an automated bot. "
            footer += "The content is sourced from various news outlets and summarized using AI.\n\n"
            footer += "-# Bot developed by حَـــــنَّـــــا."

            # Calculate maximum space for summaries (Discord limit minus footer)
            # Reserve ~400 chars for key quote, headers, dividers, and safety margin
            max_summary_space: int = 2000 - len(footer) - 400

            # Truncate summaries if they're too long to fit
            arabic_summary: str = article.arabic_summary
            english_summary: str = article.english_summary

            # If combined summaries exceed space, truncate each proportionally
            combined_length: int = len(arabic_summary) + len(english_summary)
            if combined_length > max_summary_space:
                max_each: int = max_summary_space // 2
                if len(arabic_summary) > max_each:
                    arabic_summary = arabic_summary[:max_each-3] + "..."
                if len(english_summary) > max_each:
                    english_summary = english_summary[:max_each-3] + "..."

            # Build message with professional formatting
            message_content: str = ""

            # DESIGN: Key quote at the top for better engagement
            # Extract first sentence as highlight to hook readers immediately
            # If first sentence is too long (>250 chars), truncate with ellipsis
            first_sentence: str = english_summary.split('.')[0].strip()
            if len(first_sentence) > 250:
                first_sentence = first_sentence[:247].strip() + '...'
            else:
                first_sentence = first_sentence + '.'

            # DESIGN: Always show key quote if we have a valid first sentence
            # Changed from requiring < 200 chars to always showing (with truncation)
            if len(first_sentence) > 20:
                message_content += f"> 💬 *\"{first_sentence}\"*\n\n"
                message_content += "─────────────\n\n"

            # DESIGN: Arabic summary section with emoji flag header
            # Makes it clear which language is which
            message_content += f"🇸🇾 **Arabic Summary**\n{arabic_summary}\n\n"
            message_content += "─────────────\n\n"

            # DESIGN: English translation section with emoji flag header
            message_content += f"🇬🇧 **English Translation**\n{english_summary}\n\n"
            message_content += "─────────────\n\n"

            # Add the footer (with URL guaranteed to be complete)
            message_content += footer

            full_content: str = message_content

            # Create forum thread with image (no tags for gaming - simpler than soccer)
            files_to_upload: list[discord.File] = [image_file] if image_file else []

            # DESIGN: Format thread name with date emoji to match news format
            # Example: "📅 11-19-25 | PS5 Pro Launch Details"
            from datetime import datetime
            post_date: str = datetime.now().strftime("%m-%d-%y")
            thread_name: str = f"📅 {post_date} | {article.title}"
            if len(thread_name) > 100:
                thread_name = f"📅 {post_date} | {article.title[:80]}..."

            thread: discord.Thread
            message: discord.Message

            thread, message = await channel.create_thread(
                name=thread_name,
                content=full_content,
                files=files_to_upload,
            )

            # DESIGN: Mark article ID as posted immediately after forum thread creation
            # Prevents duplicate posts on next hourly run
            # CRITICAL: Use article ID instead of full URL for reliability
            article_id: str = self.gaming_scraper._extract_article_id(article.url)
            self.gaming_scraper.fetched_urls.add(article_id)
            self.gaming_scraper._save_posted_urls()
            logger.info(f"🎮 Marked gaming article ID as posted: {article_id} (URL: {article.url[:50]})")

            logger.info(f"🎮 Posted gaming forum thread: {article.title}")

            # DESIGN: Send announcement embed to general channel with link to forum post
            # Same notification system as news posts for consistency
            logger.info(f"🔍 Checking general_channel_id for gaming announcement: {self.general_channel_id}")
            if self.general_channel_id:
                await self._send_gaming_announcement(thread, article)
            else:
                logger.warning("❌ General channel ID not configured - skipping gaming announcement")

        finally:
            # Clean up temp image file
            if temp_image_path and Path(temp_image_path).exists():
                try:
                    Path(temp_image_path).unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp gaming image: {e}")

    async def on_reaction_add(
        self, reaction: discord.Reaction, user: discord.User
    ) -> None:
        """
        Event handler for when a reaction is added to a message.

        DESIGN: Block ALL reactions on announcement embeds
        Remove any reactions from users to keep announcements clean
        """
        # DESIGN: Ignore bot's own reactions (for safety)
        if user.bot:
            return

        # DESIGN: Check if this is an announcement message
        # Only enforce reaction blocking on tracked announcement messages
        if reaction.message.id not in self.announcement_messages:
            return

        # DESIGN: Remove ALL reactions on announcement embeds
        # No reactions allowed on news notifications
        try:
            await reaction.remove(user)
            logger.info(
                f"🗑️ Removed reaction {reaction.emoji} from {user.name} on announcement (all reactions blocked)"
            )
        except discord.HTTPException as e:
                logger.warning(f"Failed to remove reaction: {e}")

    async def close(self) -> None:
        """
        Cleanup when bot is shutting down.

        DESIGN: Properly close all services and sessions
        Prevents resource leaks and ensures state is saved
        """
        logger.info("Shutting down Othman Bot...")

        # Stop presence update loop
        if self.presence_task and not self.presence_task.done():
            self.presence_task.cancel()
            try:
                await self.presence_task
            except asyncio.CancelledError:
                pass

        # Stop news scheduler
        if self.news_scheduler and self.news_scheduler.is_running:
            await self.news_scheduler.stop()

        # Close news scraper session
        if self.news_scraper:
            await self.news_scraper.__aexit__(None, None, None)

        # Stop soccer scheduler
        if self.soccer_scheduler and self.soccer_scheduler.is_running:
            await self.soccer_scheduler.stop()

        # Close soccer scraper session
        if self.soccer_scraper:
            await self.soccer_scraper.__aexit__(None, None, None)

        # Call parent close
        await super().close()

        logger.success("Bot shutdown complete")


# DESIGN: Export bot class for use in main.py
# Allows clean import: from src.bot import OthmanBot
__all__ = ["OthmanBot"]
