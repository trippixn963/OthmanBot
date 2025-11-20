"""
Othman Discord Bot - Gaming Scraper Service
===========================================

Fetches gaming news from GameSpot RSS feeds with rotation.

Sources:
- GameSpot News - All gaming news
- GameSpot Game News - Game-specific news
- GameSpot Reviews - Game reviews

Features:
- RSS feed rotation between multiple GameSpot feeds
- Image extraction from articles
- AI-powered title generation
- Bilingual summaries (Arabic + English)
- Duplicate detection
- Gaming-focused content

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import json
import asyncio
import random
import feedparser
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from openai import OpenAI

from src.core.logger import logger
from src.utils import AICache


@dataclass
class GamingArticle:
    """Represents a gaming news article with all necessary information."""

    title: str
    url: str
    summary: str
    full_content: str  # Full article text extracted from page
    arabic_summary: str  # AI-generated Arabic summary
    english_summary: str  # AI-generated English summary
    image_url: Optional[str]
    published_date: datetime = None
    source: str = ""
    source_emoji: str = ""
    game_category: Optional[str] = None  # AI-detected game/platform tag for categorization


class GamingScraper:
    """Scrapes gaming news from GameSpot with feed rotation."""

    # DESIGN: Three GameSpot RSS feeds with rotation
    # User-specified feeds: Game News, New Game Releases, Game Reviews
    # Rotation provides variety in gaming content each hour
    GAMING_FEEDS: list[dict[str, str]] = [
        {
            "key": "gamespot_game_news",
            "name": "GameSpot",
            "emoji": "🎮",
            "rss_url": "https://www.gamespot.com/feeds/game-news/",
            "language": "English",
        },
        {
            "key": "gamespot_new_games",
            "name": "GameSpot",
            "emoji": "🆕",
            "rss_url": "https://www.gamespot.com/feeds/new-games/",
            "language": "English",
        },
        {
            "key": "gamespot_reviews",
            "name": "GameSpot",
            "emoji": "⭐",
            "rss_url": "https://www.gamespot.com/feeds/reviews/",
            "language": "English",
        },
    ]

    # DESIGN: Keep track of which feed to use next for rotation
    _current_feed_index: int = 0

    # DESIGN: Gaming categories for AI-powered tagging
    # Maps game/platform names to their exact string for tag matching
    # AI will analyze article content and return ONE of these categories
    # Fallback to "General Gaming" for multi-platform or general gaming news
    GAME_CATEGORIES: list[str] = [
        "PlayStation",
        "Xbox",
        "Nintendo",
        "PC Gaming",
        "Mobile Gaming",
        "Esports",
        "Game Reviews",
        "Game Trailers",
        "Gaming Hardware",
        "Indie Games",
        "AAA Titles",
        "Gaming Industry",
        "Game Updates",
        "Gaming Events",
        "General Gaming",
    ]

    def __init__(self) -> None:
        """Initialize the gaming scraper."""
        self.session: Optional[aiohttp.ClientSession] = None

        # DESIGN: Track fetched URLs to avoid duplicate posts
        # Stored as set for O(1) lookup performance
        # PERSISTED to JSON file to survive bot restarts
        self.fetched_urls: set[str] = set()
        self.max_cached_urls: int = 1000
        self.posted_urls_file: Path = Path("data/posted_gaming_urls.json")
        self.posted_urls_file.parent.mkdir(exist_ok=True)

        # DESIGN: Load previously posted URLs on startup
        # Prevents re-posting same articles after bot restart
        self._load_posted_urls()

        # DESIGN: Initialize OpenAI client for title generation and summaries
        # Uses API key from environment variables
        api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        self.openai_client: Optional[OpenAI] = OpenAI(api_key=api_key) if api_key else None

        # DESIGN: Initialize AI response cache to reduce OpenAI API costs
        # Caches titles and summaries for previously seen articles
        # Especially useful during backfill operations (7-day lookback)
        self.ai_cache: AICache = AICache("data/gaming_ai_cache.json")

    async def __aenter__(self) -> "GamingScraper":
        """Async context manager entry."""
        # DESIGN: Use browser-like headers to avoid 403 Forbidden errors
        # IGN blocks requests without proper User-Agent
        headers: dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        self.session = aiohttp.ClientSession(headers=headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self.session:
            await self.session.close()

    @staticmethod
    def _extract_article_id(url: str) -> str:
        """
        Extract unique article ID from URL for deduplication.

        DESIGN: Use article ID instead of full URL to prevent duplicate posts
        Problem: Full URLs can be truncated, have different encodings, or vary in format
        Solution: Extract the numeric article ID which is stable and unique
        Example: https://www.ign.com/articles/game-title-12345 → "12345"

        Args:
            url: Article URL

        Returns:
            Article ID extracted from URL, or full URL if extraction fails
        """
        import re
        # DESIGN: Match article ID pattern: /NUMBERS/ or /NUMBERS? or -NUMBERS-
        # IGN URLs typically use format: /articles/slug-12345
        match = re.search(r'/(\d+)', url)
        if not match:
            # Try pattern with dash separator (e.g., article-12345-title)
            match = re.search(r'-(\d+)-', url)
        if match:
            return match.group(1)
        # Fallback to full URL if no ID found
        return url

    def _load_posted_urls(self) -> None:
        """
        Load previously posted article IDs from JSON file.

        DESIGN: Convert all entries to article IDs for reliable deduplication
        Backward compatible: converts old URL entries to article IDs
        Article IDs are more reliable than full URLs for preventing duplicates
        Gracefully handles missing or corrupt file
        """
        try:
            if self.posted_urls_file.exists():
                with open(self.posted_urls_file, "r", encoding="utf-8") as f:
                    data: dict[str, list[str]] = json.load(f)
                    url_list: list[str] = data.get("posted_urls", [])
                    # DESIGN: Convert all entries (URLs or IDs) to article IDs
                    # Backward compatible with old URL-based cache
                    self.fetched_urls = set(self._extract_article_id(url) for url in url_list)
                    logger.info(f"🎮 Loaded {len(self.fetched_urls)} posted gaming article IDs from cache")
            else:
                logger.info("No posted gaming article IDs cache found - starting fresh")
        except Exception as e:
            logger.warning(f"Failed to load posted gaming article IDs: {e}")
            self.fetched_urls = set()

    def _save_posted_urls(self) -> None:
        """
        Save posted article IDs to JSON file.

        DESIGN: Persist article IDs to disk after each post
        Ensures duplicate prevention survives bot restarts
        Saves ALL article IDs (no limit) to prevent losing recently posted IDs
        """
        try:
            # DESIGN: Save ALL article IDs in the set to avoid random subset bug
            # Sort for consistency
            ids_to_save: list[str] = sorted(list(self.fetched_urls))

            with open(self.posted_urls_file, "w", encoding="utf-8") as f:
                json.dump({"posted_urls": ids_to_save}, f, indent=2, ensure_ascii=False)

            logger.info(f"🎮 Saved {len(ids_to_save)} posted gaming article IDs to cache")
        except Exception as e:
            logger.warning(f"Failed to save posted gaming article IDs: {e}")

    async def fetch_latest_gaming_news(
        self, max_articles: int = 5, hours_back: int = 168
    ) -> List[GamingArticle]:
        """
        Fetch latest gaming news with priority-based feed selection.

        PRIORITY STRATEGY:
        1. Check Reviews feed → ONLY latest article, skip if already posted
        2. Check New Releases feed → ONLY latest article, skip if already posted
        3. Fallback to Game News feed → check all articles with backfill support

        Args:
            max_articles: Maximum number of articles to return
            hours_back: How far back to search (default: 168 hours = 7 days)

        Returns:
            List of GamingArticle objects

        DESIGN: Priority-based selection ensures fresh reviews/releases take precedence
        Game News acts as reliable fallback with full backfill capability
        """
        cutoff_time: datetime = datetime.now() - timedelta(hours=hours_back)

        # DESIGN: Define feed priority order
        # Reviews and New Releases: latest-only (no backfill)
        # Game News: full backfill support
        reviews_feed: dict[str, str] = self.GAMING_FEEDS[2]  # gamespot_reviews
        releases_feed: dict[str, str] = self.GAMING_FEEDS[1]  # gamespot_new_games
        news_feed: dict[str, str] = self.GAMING_FEEDS[0]  # gamespot_game_news

        # PRIORITY 1: Check Reviews feed - ONLY latest article
        logger.info(f"🎮 Checking priority 1: {reviews_feed['name']} (latest only)")
        try:
            reviews: list[GamingArticle] = await self._fetch_from_source(
                reviews_feed["key"], reviews_feed, cutoff_time, 1  # Only fetch 1
            )
            if reviews:
                article_id: str = self._extract_article_id(reviews[0].url)
                if article_id not in self.fetched_urls:
                    logger.success(f"⭐ Found NEW review: {reviews[0].title[:50]}")
                    return reviews[:max_articles]
                else:
                    logger.info("⏭️ Reviews: Latest already posted, checking releases...")
        except Exception as e:
            logger.warning(f"Failed to fetch reviews: {str(e)[:100]}")

        # PRIORITY 2: Check New Releases feed - ONLY latest article
        logger.info(f"🎮 Checking priority 2: {releases_feed['name']} (latest only)")
        try:
            releases: list[GamingArticle] = await self._fetch_from_source(
                releases_feed["key"], releases_feed, cutoff_time, 1  # Only fetch 1
            )
            if releases:
                article_id: str = self._extract_article_id(releases[0].url)
                if article_id not in self.fetched_urls:
                    logger.success(f"🆕 Found NEW release: {releases[0].title[:50]}")
                    return releases[:max_articles]
                else:
                    logger.info("⏭️ Releases: Latest already posted, falling back to news...")
        except Exception as e:
            logger.warning(f"Failed to fetch releases: {str(e)[:100]}")

        # PRIORITY 3: Fallback to Game News with full backfill support
        logger.info(f"🎮 Fallback: {news_feed['name']} (with backfill)")
        try:
            news_articles: list[GamingArticle] = await self._fetch_from_source(
                news_feed["key"], news_feed, cutoff_time, max_articles * 10  # Fetch more for backfill
            )

            if not news_articles:
                logger.warning("⚠️ No gaming articles found in any feed")
                return []

            # DESIGN: Sort by published date (newest first)
            news_articles.sort(key=lambda x: x.published_date, reverse=True)

            # DESIGN: Separate new articles from old articles
            new_articles: list[GamingArticle] = []
            old_articles: list[GamingArticle] = []
            seen_ids: set[str] = set()

            for article in news_articles:
                article_id: str = self._extract_article_id(article.url)

                if article_id in seen_ids:
                    continue  # Skip duplicates

                seen_ids.add(article_id)

                if article_id not in self.fetched_urls:
                    new_articles.append(article)
                else:
                    old_articles.append(article)

            # DESIGN: Backfill logic - prefer new, fallback to old
            if new_articles:
                logger.success(f"✅ Found {len(new_articles)} NEW unposted news articles")
                return new_articles[:max_articles]
            elif old_articles:
                # DESIGN: Reverse sort old articles to get OLDEST first for backfill
                old_articles.sort(key=lambda x: x.published_date)  # Oldest first
                logger.info(f"⏪ No new news - backfilling from {len(old_articles)} older articles")
                return old_articles[:max_articles]
            else:
                logger.warning("⚠️ All news articles already posted")
                return []

        except Exception as e:
            logger.warning(f"Failed to fetch game news: {str(e)[:100]}")
            return []

    async def _fetch_from_source(
        self,
        source_key: str,
        source_info: dict[str, str],
        cutoff_time: datetime,
        max_articles: int,
    ) -> List[GamingArticle]:
        """
        Fetch articles from IGN RSS feed.

        Args:
            source_key: Source identifier
            source_info: Source configuration dict
            cutoff_time: Only fetch articles newer than this
            max_articles: Maximum articles to fetch

        Returns:
            List of GamingArticle objects from this source
        """
        articles: list[GamingArticle] = []

        # DESIGN: Use feedparser for reliable RSS parsing
        feed: feedparser.FeedParserDict = feedparser.parse(source_info["rss_url"])

        if not feed.entries:
            logger.warning(f"No entries found in {source_info['name']} feed")
            return articles

        for entry in feed.entries[: max_articles * 2]:  # Fetch extra for filtering
            try:

                # DESIGN: Parse published date with multiple fallback formats
                published_date: Optional[datetime] = self._parse_date(entry)
                if not published_date or published_date < cutoff_time:
                    continue

                # DESIGN: Extract image from multiple possible locations
                image_url: Optional[str] = await self._extract_image(entry)

                # DESIGN: Get summary text, fallback to description or truncated content
                summary: str = (
                    entry.get("summary", "")
                    or entry.get("description", "")
                    or entry.get("content", [{}])[0].get("value", "")
                )
                # Clean HTML tags from summary
                summary = BeautifulSoup(summary, "html.parser").get_text()
                summary = summary[:500] + "..." if len(summary) > 500 else summary

                # DESIGN: Extract full article content and image from the URL
                full_content: str
                scraped_image: Optional[str]
                full_content, scraped_image = await self._extract_full_content(
                    entry.get("link", ""), source_key
                )

                # DESIGN: Prefer scraped image from article page over RSS feed image
                if not image_url and scraped_image:
                    image_url = scraped_image

                # DESIGN: Skip articles with fetch errors
                error_messages: list[str] = [
                    "Article fetch timed out",
                    "Could not fetch article content",
                    "Could not extract article text",
                    "Content extraction failed",
                    "Content unavailable"
                ]
                if any(error_msg in full_content for error_msg in error_messages):
                    continue

                # DESIGN: Skip articles without images
                # NEVER post articles without media
                if not image_url:
                    continue

                # DESIGN: Extract article ID for cache key
                # Use article ID from URL for all AI caching operations
                article_id: str = self._extract_article_id(entry.get("link", ""))
                original_title: str = entry.get("title", "Untitled")

                # DESIGN: Check AI cache for title before generating
                # Cache saves money on OpenAI API calls, especially during backfill
                cached_title = self.ai_cache.get_title(article_id)
                if cached_title:
                    ai_title: str = cached_title["english_title"]
                    logger.info(f"💾 Cache hit: Using cached title for article {article_id}")
                else:
                    # DESIGN: Generate AI-powered 3-5 word English title
                    # Replaces original title (may be too long) with clean English title
                    # Uses OpenAI GPT-3.5-turbo to understand article and create concise title
                    ai_title: str = self._generate_ai_title(original_title, full_content)
                    self.ai_cache.cache_title(article_id, original_title, ai_title)
                    logger.info(f"🔄 Cache miss: Generated and cached title for article {article_id}")

                # DESIGN: Check AI cache for summaries before generating
                # Summaries are expensive (long content = more tokens), cache saves significant cost
                cached_summary = self.ai_cache.get_summary(article_id)
                if cached_summary:
                    arabic_summary: str = cached_summary["arabic_summary"]
                    english_summary: str = cached_summary["english_summary"]
                    logger.info(f"💾 Cache hit: Using cached summary for article {article_id}")
                else:
                    # DESIGN: Generate bilingual summaries (Arabic + English)
                    # AI creates concise 3-4 sentence summaries in both languages
                    # Much better than truncated raw text
                    arabic_summary, english_summary = self._generate_bilingual_summary(full_content)
                    self.ai_cache.cache_summary(article_id, arabic_summary, english_summary)
                    logger.info(f"🔄 Cache miss: Generated and cached summary for article {article_id}")

                # DESIGN: Detect game category for article categorization
                # Note: Game category detection is not cached as it's cheap and rarely changes
                game_category: str = self._detect_game_category(ai_title, full_content)

                article: GamingArticle = GamingArticle(
                    title=ai_title,
                    url=entry.get("link", ""),
                    summary=summary,
                    full_content=full_content,
                    arabic_summary=arabic_summary,
                    english_summary=english_summary,
                    image_url=image_url,
                    published_date=published_date,
                    source=source_info["name"],
                    source_emoji=source_info["emoji"],
                    game_category=game_category,
                )

                articles.append(article)

                if len(articles) >= max_articles:
                    break

            except Exception as e:
                logger.warning(
                    f"Failed to parse gaming article from {source_info['name']}: {str(e)[:100]}"
                )
                continue

        return articles

    def _parse_date(self, entry: feedparser.FeedParserDict) -> Optional[datetime]:
        """Parse publication date from RSS entry."""
        date_tuple = entry.get("published_parsed") or entry.get("updated_parsed")

        if date_tuple:
            try:
                return datetime(*date_tuple[:6])
            except (TypeError, ValueError):
                pass

        return datetime.now()

    async def _extract_image(self, entry: feedparser.FeedParserDict) -> Optional[str]:
        """Extract image URL from RSS entry."""
        # Try media:content tag
        if "media_content" in entry:
            for media in entry.media_content:
                if "url" in media and any(
                    ext in media["url"].lower()
                    for ext in [".jpg", ".jpeg", ".png", ".webp"]
                ):
                    return media["url"]

        # Try media:thumbnail tag
        if "media_thumbnail" in entry and entry.media_thumbnail:
            return entry.media_thumbnail[0].get("url")

        # Try enclosure tag
        if "enclosures" in entry and entry.enclosures:
            for enclosure in entry.enclosures:
                if enclosure.get("type", "").startswith("image/"):
                    return enclosure.get("href")

        # Try to extract first image from article content
        content: str = (
            entry.get("summary", "")
            or entry.get("description", "")
            or entry.get("content", [{}])[0].get("value", "")
        )

        if content:
            soup: BeautifulSoup = BeautifulSoup(content, "html.parser")
            img_tag = soup.find("img")
            if img_tag and img_tag.get("src"):
                return img_tag["src"]

        return None

    async def _extract_full_content(self, url: str, source_key: str) -> tuple[str, Optional[str]]:
        """
        Extract full article text content and image from article URL.

        Args:
            url: Article URL to fetch
            source_key: Source identifier (ign)

        Returns:
            Tuple of (full article text content, image URL or None)
        """
        if not url or not self.session:
            return ("Content unavailable", None)

        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    return ("Could not fetch article content", None)

                html: str = await response.text()
                soup: BeautifulSoup = BeautifulSoup(html, "html.parser")

                # DESIGN: Extract first article image
                image_url: Optional[str] = None

                # DESIGN: GameSpot-specific image extraction
                # og:image meta tag is most reliable for news sites
                if source_key.startswith("gamespot"):
                    og_image = soup.find("meta", property="og:image")
                    if og_image and og_image.get("content"):
                        image_url = og_image["content"]

                    # Fallback: article hero image
                    if not image_url:
                        hero_img = soup.find("img", class_=lambda x: x and ("hero" in x.lower() or "lead" in x.lower()) if x else False)
                        if hero_img:
                            image_url = hero_img.get("src") or hero_img.get("data-src")

                # Generic image extraction for other sources
                if not image_url:
                    article_div = (
                        soup.find("div", class_="article-content")
                        or soup.find("article")
                        or soup.find("div", class_=lambda x: x and "content" in x.lower() if x else False)
                    )

                    if article_div:
                        img_tags = article_div.find_all("img")
                        for img in img_tags:
                            src = img.get("src") or img.get("data-src")
                            if src and any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                                if src.startswith("//"):
                                    image_url = "https:" + src
                                elif src.startswith("/"):
                                    from urllib.parse import urlparse
                                    parsed = urlparse(url)
                                    image_url = f"{parsed.scheme}://{parsed.netloc}{src}"
                                else:
                                    image_url = src
                                break

                # DESIGN: Source-specific content extraction
                content_text: str = ""

                # DESIGN: GameSpot-specific content extraction
                # Uses content-entity-body or article-body class
                if source_key.startswith("gamespot"):
                    article_body = (
                        soup.find("div", class_="content-entity-body")
                        or soup.find("div", class_="article-body")
                        or soup.find("div", class_="js-content-entity-body")
                    )
                    if article_body:
                        paragraphs = article_body.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                    # Fallback: try main content area
                    if not content_text:
                        main_content = soup.find("main") or soup.find("article")
                        if main_content:
                            paragraphs = main_content.find_all("p")
                            content_paragraphs = [p for p in paragraphs if len(p.get_text().strip()) > 50]
                            content_text = "\n\n".join([p.get_text().strip() for p in content_paragraphs])

                # DESIGN: Generic fallback
                if not content_text:
                    article = soup.find("article") or soup.find("div", class_=lambda x: x and "content" in x.lower())
                    if article:
                        paragraphs = article.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                # Clean content
                if content_text:
                    content_text = "\n\n".join(line.strip() for line in content_text.split("\n") if line.strip())
                    logger.info(f"🎮 Extracted from {url} - Image: {image_url[:50] if image_url else 'None'}")
                    return (content_text, image_url)
                else:
                    return ("Could not extract article text", image_url)

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching gaming article from {url}")
            return ("Article fetch timed out", None)
        except Exception as e:
            logger.warning(f"Failed to extract gaming content from {url}: {str(e)[:100]}")
            return ("Content extraction failed", None)

    def _generate_ai_title(self, original_title: str, content: str) -> str:
        """Generate a concise 3-5 word English title using OpenAI GPT-3.5-turbo."""
        if not self.openai_client:
            logger.warning("OpenAI client not initialized - using original title")
            return original_title

        try:
            content_snippet: str = content[:500] if len(content) > 500 else content

            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a gaming headline writer specializing in video game news. Create concise, clear English titles for gaming articles. Your titles must be EXACTLY 3-5 words, in English only, and capture the main gaming topic (games, platforms, esports, hardware, industry news, etc.)."
                    },
                    {
                        "role": "user",
                        "content": f"Create a 3-5 word English title for this gaming article.\n\nOriginal title: {original_title}\n\nContent: {content_snippet}\n\nRespond with ONLY the title, nothing else."
                    }
                ],
                max_tokens=20,
                temperature=0.7,
            )

            ai_title: str = response.choices[0].message.content.strip()

            if ai_title and 3 <= len(ai_title.split()) <= 7:
                logger.info(f"🎮 AI generated gaming title: '{ai_title}' from '{original_title[:50]}'")
                return ai_title
            else:
                logger.warning(f"AI gaming title invalid: '{ai_title}' - using original")
                return original_title

        except Exception as e:
            logger.warning(f"Failed to generate AI gaming title: {str(e)[:100]}")
            return original_title

    def _generate_bilingual_summary(self, content: str) -> tuple[str, str]:
        """Generate bilingual summaries (Arabic and English) using OpenAI GPT-3.5-turbo."""
        if not self.openai_client:
            logger.warning("OpenAI client not initialized - using truncated content")
            truncated: str = content[:300] + "..." if len(content) > 300 else content
            return (truncated, truncated)

        try:
            # DESIGN: Limit summaries to fit within Discord's 2000 char message limit
            # Total budget: ~1200 chars (leaving room for key quote/headers/dividers/footer)
            # Arabic: 400 chars, English: 400 chars = 800 chars for summaries
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a bilingual gaming news summarizer. Create concise but informative summaries in both Arabic and English. IMPORTANT: Each summary MUST be under 400 characters. Focus on the most important facts: game name, key announcement, release info. Be concise."
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this gaming article in both Arabic and English. CRITICAL: Keep each summary under 400 characters. Focus on key facts only.\n\nFormat your response EXACTLY as:\n\nARABIC:\n[Arabic summary - MAX 400 characters]\n\nENGLISH:\n[English summary - MAX 400 characters]\n\nArticle content:\n{content}"
                    }
                ],
                temperature=0.7,
                max_tokens=500,  # Limit AI response length
            )

            result: str = response.choices[0].message.content.strip()

            # DESIGN: Parse AI response to extract Arabic and English summaries
            arabic_summary: str = ""
            english_summary: str = ""

            if "ARABIC:" in result and "ENGLISH:" in result:
                parts: list[str] = result.split("ENGLISH:")
                arabic_part: str = parts[0].replace("ARABIC:", "").strip()
                english_part: str = parts[1].strip()

                arabic_summary = arabic_part
                english_summary = english_part

                # DESIGN: Safety truncation to ensure summaries fit Discord limit
                # Total content budget ~1600 chars (leaving room for headers/dividers/footer)
                # 400 chars each = 800 chars for summaries, leaving plenty of room
                if len(arabic_summary) > 400:
                    arabic_summary = arabic_summary[:397] + "..."
                    logger.warning(f"🎮 Truncated Arabic gaming summary from {len(arabic_part)} to 400 chars")
                if len(english_summary) > 400:
                    english_summary = english_summary[:397] + "..."
                    logger.warning(f"🎮 Truncated English gaming summary from {len(english_part)} to 400 chars")

                logger.info(f"🎮 Generated bilingual gaming summaries (AR: {len(arabic_summary)} chars, EN: {len(english_summary)} chars)")
            else:
                logger.warning("AI gaming summary format invalid - using truncated content")
                truncated: str = content[:300] + "..." if len(content) > 300 else content
                return (truncated, truncated)

            return (arabic_summary, english_summary)

        except Exception as e:
            logger.warning(f"Failed to generate bilingual gaming summary: {str(e)[:100]}")
            truncated: str = content[:300] + "..." if len(content) > 300 else content
            return (truncated, truncated)

    def _detect_game_category(self, title: str, content: str) -> str:
        """
        Detect which gaming category the article falls under using AI.

        Args:
            title: Article title
            content: Article content

        Returns:
            Category name string matching one of GAME_CATEGORIES, defaults to "General Gaming"
        """
        if not self.openai_client:
            logger.warning("OpenAI client not initialized - using General Gaming category")
            return "General Gaming"

        try:
            categories_list: str = ", ".join(self.GAME_CATEGORIES)
            content_snippet: str = content[:800] if len(content) > 800 else content

            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": f"You are a gaming news categorization expert. Analyze articles and determine which category they best fit. You must respond with EXACTLY ONE of these categories: {categories_list}. Choose the most specific category that applies. If the article covers multiple categories or doesn't fit any specific one, respond with 'General Gaming'."
                    },
                    {
                        "role": "user",
                        "content": f"Which category does this gaming article best fit? Respond with ONLY the category name from the list provided.\n\nTitle: {title}\n\nContent: {content_snippet}"
                    }
                ],
                max_tokens=10,
                temperature=0.3,  # Low temperature for consistent categorization
            )

            detected_category: str = response.choices[0].message.content.strip()

            # DESIGN: Validate AI response against known categories
            if detected_category in self.GAME_CATEGORIES:
                logger.info(f"🎮 Detected game category: '{detected_category}' for article '{title[:40]}'")
                return detected_category
            else:
                logger.warning(f"AI returned invalid category '{detected_category}' - using General Gaming")
                return "General Gaming"

        except Exception as e:
            logger.warning(f"Failed to detect game category: {str(e)[:100]} - using General Gaming")
            return "General Gaming"
