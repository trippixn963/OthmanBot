"""
Othman Discord Bot - News Scraper Service
=========================================

Fetches Syrian news from multiple RSS feeds and websites.

Sources:
- Enab Baladi (عنب بلدي) - Primary Syrian news
- Al Jazeera Arabic Syria - Major network coverage
- Syrian Observer - English backup

Features:
- RSS feed parsing with fallback
- Image extraction from articles
- Duplicate detection
- Multi-source aggregation

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import json
import asyncio
import feedparser
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from openai import OpenAI

from src.core.logger import logger


@dataclass
class NewsArticle:
    """Represents a news article with all necessary information."""

    title: str
    url: str
    summary: str
    full_content: str  # Full article text extracted from page
    arabic_summary: str  # AI-generated Arabic summary
    english_summary: str  # AI-generated English summary
    image_url: Optional[str]
    video_url: Optional[str] = None  # Video URL extracted from article
    published_date: datetime = None
    source: str = ""
    source_emoji: str = ""
    category_tag_id: Optional[int] = None  # Discord forum tag ID


class NewsScraper:
    """Scrapes Syrian news from multiple sources."""

    # DESIGN: Single RSS source - Enab Baladi only
    # Syria-focused independent journalism with media-rich articles
    NEWS_SOURCES: dict[str, dict[str, str]] = {
        "enab_baladi": {
            "name": "Enab Baladi",
            "emoji": "🍇",
            "rss_url": "https://www.enabbaladi.net/feed/",
            "language": "Arabic/English",
        },
    }

    def __init__(self) -> None:
        """Initialize the news scraper."""
        self.session: Optional[aiohttp.ClientSession] = None

        # DESIGN: Track fetched URLs to avoid duplicate posts
        # Stored as set for O(1) lookup performance
        # Limited to last 1000 URLs to prevent memory growth
        # PERSISTED to JSON file to survive bot restarts
        self.fetched_urls: set[str] = set()
        self.max_cached_urls: int = 1000
        self.posted_urls_file: Path = Path("data/posted_urls.json")
        self.posted_urls_file.parent.mkdir(exist_ok=True)

        # DESIGN: Load previously posted URLs on startup
        # Prevents re-posting same articles after bot restart
        self._load_posted_urls()

        # DESIGN: Initialize OpenAI client for title generation
        # Uses API key from environment variables
        api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        self.openai_client: Optional[OpenAI] = OpenAI(api_key=api_key) if api_key else None

    async def __aenter__(self) -> "NewsScraper":
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
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
        Example: https://www.enabbaladi.net/784230/... → "784230"

        Args:
            url: Article URL

        Returns:
            Article ID extracted from URL, or full URL if extraction fails
        """
        import re
        # DESIGN: Match article ID pattern: /NUMBERS/ or /NUMBERS?
        # Enab Baladi URLs follow pattern: domain.com/ARTICLE_ID/title-slug/
        match = re.search(r'/(\d+)/', url)
        if match:
            return match.group(1)
        # Fallback to full URL if no ID found
        return url

    @staticmethod
    def _normalize_url(url: str) -> str:
        """
        Normalize URL for consistent comparison.

        DESIGN: Strip trailing slash to prevent duplicate posts
        RSS feeds often have URLs without trailing slash
        After HTTP redirects/fetching, URLs gain trailing slash
        This causes "URL A" != "URL A/" mismatch
        Solution: Always strip trailing slash for comparison

        NOTE: This is now deprecated in favor of _extract_article_id()
        which is more reliable for deduplication

        Args:
            url: URL to normalize

        Returns:
            Normalized URL without trailing slash
        """
        return url.rstrip('/')

    def _load_posted_urls(self) -> None:
        """
        Load previously posted article IDs from JSON file.

        DESIGN: Read article IDs from persistent storage on bot startup
        Prevents duplicate posts after bot restarts
        Now uses article IDs instead of full URLs for reliability
        Gracefully handles both old URL format and new ID format
        """
        try:
            if self.posted_urls_file.exists():
                with open(self.posted_urls_file, "r", encoding="utf-8") as f:
                    data: dict[str, list[str]] = json.load(f)
                    url_list: list[str] = data.get("posted_urls", [])
                    # DESIGN: Convert all entries to article IDs for consistency
                    # Old entries may be full URLs, new entries will be article IDs
                    # Extract article ID from each entry (handles both formats)
                    self.fetched_urls = set(self._extract_article_id(url) for url in url_list)
                    logger.info(f"📥 Loaded {len(self.fetched_urls)} posted article IDs from cache")
            else:
                logger.info("No posted URLs cache found - starting fresh")
        except Exception as e:
            logger.warning(f"Failed to load posted URLs: {e}")
            self.fetched_urls = set()

    def _save_posted_urls(self) -> None:
        """
        Save posted article IDs to JSON file.

        DESIGN: Persist article IDs to disk after each post
        Ensures duplicate prevention survives bot restarts
        Saves ALL IDs (no limit) for complete deduplication
        Uses article IDs instead of full URLs for reliability
        """
        try:
            # DESIGN: Save ALL article IDs in the set to avoid random subset bug
            # Previous bug: list(set)[-1000:] takes random 1000 IDs due to undefined set order
            # This caused newly-added IDs to be lost when saving
            # Fix: Save ALL IDs, sort for consistency
            ids_to_save: list[str] = sorted(list(self.fetched_urls))

            with open(self.posted_urls_file, "w", encoding="utf-8") as f:
                json.dump({"posted_urls": ids_to_save}, f, indent=2, ensure_ascii=False)

            logger.info(f"💾 Saved {len(ids_to_save)} posted article IDs to cache")
        except Exception as e:
            logger.warning(f"Failed to save posted article IDs: {e}")

    async def fetch_latest_news(
        self, max_articles: int = 5, hours_back: int = 168
    ) -> List[NewsArticle]:
        """
        Fetch latest Syrian news from all sources with backfill logic.

        BACKFILL STRATEGY:
        1. Always check for new (unposted) articles first
        2. If no new articles, go backwards through older articles
        3. Post one old article per hour until a new one appears
        4. This ensures hourly posts even during slow news periods

        Args:
            max_articles: Maximum number of articles to return per source
            hours_back: How far back to search (default: 7 days for backfill)

        Returns:
            List of NewsArticle objects (newest unposted first, or oldest if all new posted)
        """
        all_articles: list[NewsArticle] = []
        cutoff_time: datetime = datetime.now() - timedelta(hours=hours_back)

        # DESIGN: Fetch from all sources concurrently for speed
        # Each source operates independently to prevent one failure blocking others
        for source_key, source_info in self.NEWS_SOURCES.items():
            try:
                articles: list[NewsArticle] = await self._fetch_from_source(
                    source_key, source_info, cutoff_time, max_articles * 10  # Fetch more for backfill
                )
                all_articles.extend(articles)
                logger.success(
                    f"Fetched {len(articles)} articles from {source_info['name']}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to fetch from {source_info['name']}: {str(e)[:100]}"
                )
                continue

        # DESIGN: Sort by published date (newest first) initially
        # This allows us to check latest articles first
        all_articles.sort(key=lambda x: x.published_date, reverse=True)

        # DESIGN: Separate new articles from old articles
        # New = not in posted article IDs cache
        new_articles: list[NewsArticle] = []
        old_articles: list[NewsArticle] = []
        seen_ids: set[str] = set()

        for article in all_articles:
            # DESIGN: Extract article ID for reliable deduplication
            # Article IDs are stable and unique, unlike URLs which can vary
            # Example: https://www.enabbaladi.net/784230/... → "784230"
            article_id: str = self._extract_article_id(article.url)

            if article_id in seen_ids:
                continue  # Skip duplicates within this fetch

            seen_ids.add(article_id)

            if article_id not in self.fetched_urls:
                new_articles.append(article)
            else:
                old_articles.append(article)

        # DESIGN: Backfill logic - prefer new, fallback to old
        # If we have new articles, use those (newest first)
        # If no new articles, use old articles (oldest first, to go backwards chronologically)
        if new_articles:
            logger.info(f"✅ Found {len(new_articles)} NEW unposted articles")
            selected_articles: list[NewsArticle] = new_articles[:max_articles]
        elif old_articles:
            # DESIGN: Reverse sort old articles to get OLDEST first
            # This creates a backfill effect: post older articles in chronological order
            old_articles.sort(key=lambda x: x.published_date)  # Oldest first
            logger.info(f"⏪ No new articles - backfilling from {len(old_articles)} older articles")
            selected_articles: list[NewsArticle] = old_articles[:max_articles]
        else:
            logger.warning("⚠️ No articles found (all filtered or none available)")
            return []

        logger.info(
            f"📰 Returning {len(selected_articles)} article(s) from {len(self.NEWS_SOURCES)} source(s)"
        )
        return selected_articles

    async def _fetch_from_source(
        self,
        source_key: str,
        source_info: dict[str, str],
        cutoff_time: datetime,
        max_articles: int,
    ) -> List[NewsArticle]:
        """
        Fetch articles from a single RSS source.

        Args:
            source_key: Source identifier
            source_info: Source configuration dict
            cutoff_time: Only fetch articles newer than this
            max_articles: Maximum articles to fetch

        Returns:
            List of NewsArticle objects from this source
        """
        articles: list[NewsArticle] = []

        # DESIGN: Use feedparser for reliable RSS parsing
        # feedparser handles various RSS/Atom formats automatically
        # parse() is synchronous, but fast enough for our needs
        feed: feedparser.FeedParserDict = feedparser.parse(source_info["rss_url"])

        if not feed.entries:
            logger.warning(f"No entries found in {source_info['name']} feed")
            return articles

        for entry in feed.entries[: max_articles * 2]:  # Fetch extra for filtering
            try:
                # DESIGN: Parse published date with multiple fallback formats
                # Different RSS feeds use different date formats
                published_date: Optional[datetime] = self._parse_date(entry)
                if not published_date or published_date < cutoff_time:
                    continue

                # DESIGN: Extract image from multiple possible locations
                # RSS feeds store images in different tags (media:content, enclosure, etc.)
                image_url: Optional[str] = await self._extract_image(entry)

                # DESIGN: Get summary text, fallback to description or truncated content
                # Some feeds use 'summary', others use 'description'
                summary: str = (
                    entry.get("summary", "")
                    or entry.get("description", "")
                    or entry.get("content", [{}])[0].get("value", "")
                )
                # Clean HTML tags from summary
                summary = BeautifulSoup(summary, "html.parser").get_text()
                summary = summary[:500] + "..." if len(summary) > 500 else summary

                # DESIGN: Extract full article content, image, AND video from the URL
                # Fetch the actual article page and extract text + media
                full_content: str
                scraped_image: Optional[str]
                scraped_video: Optional[str]
                full_content, scraped_image, scraped_video = await self._extract_full_content(
                    entry.get("link", ""), source_key
                )

                # DESIGN: Prefer scraped image from article page over RSS feed image
                # Article page images are usually better quality and more relevant
                if not image_url and scraped_image:
                    image_url = scraped_image

                # DESIGN: Skip articles without media (image or video)
                # NEVER post articles without media - user requirement
                if not image_url and not scraped_video:
                    logger.info(f"Skipping article without media: {entry.get('title', 'Untitled')[:50]}")
                    continue

                # DESIGN: Generate AI-powered 3-5 word English title
                # Replaces original title (may be Arabic or too long) with clean English title
                # Uses OpenAI GPT-3.5-turbo to understand article and create concise title
                original_title: str = entry.get("title", "Untitled")
                ai_title: str = self._generate_ai_title(original_title, full_content)

                # DESIGN: Generate bilingual summaries (Arabic + English)
                # AI creates concise 3-4 sentence summaries in both languages
                # Much better than truncated raw text
                arabic_summary: str
                english_summary: str
                arabic_summary, english_summary = self._generate_bilingual_summary(full_content)

                # DESIGN: Categorize article for Discord forum tag
                # AI analyzes content and selects most appropriate category
                # Returns Discord tag ID for automatic tag assignment
                category_tag_id: Optional[int] = self._categorize_article(ai_title, full_content)

                article: NewsArticle = NewsArticle(
                    title=ai_title,
                    url=entry.get("link", ""),
                    summary=summary,
                    full_content=full_content,
                    arabic_summary=arabic_summary,
                    english_summary=english_summary,
                    image_url=image_url,
                    video_url=scraped_video,  # Include extracted video URL
                    published_date=published_date,
                    source=source_info["name"],
                    source_emoji=source_info["emoji"],
                    category_tag_id=category_tag_id,
                )

                articles.append(article)

                if len(articles) >= max_articles:
                    break

            except Exception as e:
                logger.warning(
                    f"Failed to parse article from {source_info['name']}: {str(e)[:100]}"
                )
                continue

        return articles

    def _parse_date(self, entry: feedparser.FeedParserDict) -> Optional[datetime]:
        """
        Parse publication date from RSS entry.

        Args:
            entry: RSS feed entry

        Returns:
            datetime object or None if parsing fails
        """
        # DESIGN: Try multiple date fields with fallbacks
        # published_parsed is most reliable when available
        # published and updated are fallbacks for different feed formats
        date_tuple = entry.get("published_parsed") or entry.get("updated_parsed")

        if date_tuple:
            try:
                return datetime(*date_tuple[:6])
            except (TypeError, ValueError):
                pass

        # DESIGN: Fallback to current time if no date available
        # Better to show recent articles without date than skip them
        return datetime.now()

    async def _extract_image(self, entry: feedparser.FeedParserDict) -> Optional[str]:
        """
        Extract image URL from RSS entry.

        Args:
            entry: RSS feed entry

        Returns:
            Image URL string or None
        """
        # DESIGN: Check multiple possible image locations in RSS feed
        # Different feeds store images in different tags

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

        # DESIGN: Try to extract first image from article content
        # Last resort: parse HTML content for img tags
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

    async def _extract_full_content(self, url: str, source_key: str) -> tuple[str, Optional[str], Optional[str]]:
        """
        Extract full article text content, image, AND video from article URL.

        Args:
            url: Article URL to fetch
            source_key: Source identifier (enab_baladi, aljazeera, syrian_observer)

        Returns:
            Tuple of (full article text content, image URL or None, video URL or None)

        DESIGN: Each news source has different HTML structure
        Use specific selectors for each source to extract article content, images, and videos
        Looks for video tags, iframe embeds, and direct video files
        """
        if not url or not self.session:
            return ("Content unavailable", None, None)

        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    return ("Could not fetch article content", None, None)

                html: str = await response.text()
                soup: BeautifulSoup = BeautifulSoup(html, "html.parser")

                # DESIGN: Extract first article image
                # Look for images in article/content divs, prefer larger images
                image_url: Optional[str] = None

                # Try to find image in article content areas first
                article_div = (
                    soup.find("div", class_="entry-content")
                    or soup.find("article")
                    or soup.find("div", class_=lambda x: x and "content" in x.lower())
                )

                if article_div:
                    # Find first img tag with a valid src
                    img_tags = article_div.find_all("img")
                    for img in img_tags:
                        src = img.get("src") or img.get("data-src")
                        if src and any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                            # Make URL absolute if it's relative
                            if src.startswith("//"):
                                image_url = "https:" + src
                            elif src.startswith("/"):
                                from urllib.parse import urlparse
                                parsed = urlparse(url)
                                image_url = f"{parsed.scheme}://{parsed.netloc}{src}"
                            else:
                                image_url = src
                            break

                # DESIGN: Extract video from article
                # Look for video tags, iframe embeds, and direct video files
                video_url: Optional[str] = None

                if article_div:
                    # 1. Check for direct <video> tags with mp4/webm sources
                    video_tag = article_div.find("video")
                    if video_tag:
                        # Try <source> tag first
                        source_tag = video_tag.find("source")
                        if source_tag and source_tag.get("src"):
                            src = source_tag.get("src")
                            if any(ext in src.lower() for ext in [".mp4", ".webm", ".mov"]):
                                video_url = self._make_url_absolute(src, url)
                        # Try video src attribute
                        elif video_tag.get("src"):
                            src = video_tag.get("src")
                            if any(ext in src.lower() for ext in [".mp4", ".webm", ".mov"]):
                                video_url = self._make_url_absolute(src, url)

                    # 2. Check for iframe embeds (social media platforms)
                    if not video_url:
                        iframe = article_div.find("iframe")
                        if iframe and iframe.get("src"):
                            iframe_src = iframe.get("src")
                            # Look for common video embed platforms
                            if any(domain in iframe_src for domain in ["youtube.com", "youtu.be", "twitter.com", "x.com", "vimeo.com"]):
                                video_url = iframe_src if iframe_src.startswith("http") else f"https:{iframe_src}"

                    # 3. Check for data-video-url or similar attributes
                    if not video_url:
                        video_elements = article_div.find_all(attrs={"data-video-url": True})
                        if video_elements:
                            video_url = self._make_url_absolute(video_elements[0].get("data-video-url"), url)

                # DESIGN: Source-specific content extraction
                # Each site structures their articles differently
                content_text: str = ""

                if source_key == "enab_baladi":
                    # Enab Baladi: article content in <div class="entry-content">
                    article_div = soup.find("div", class_="entry-content")
                    if article_div:
                        # Get all paragraphs
                        paragraphs = article_div.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                elif source_key == "aljazeera":
                    # Al Jazeera: article content in <div class="wysiwyg">
                    article_div = soup.find("div", class_="wysiwyg") or soup.find("article")
                    if article_div:
                        paragraphs = article_div.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                elif source_key == "syrian_observer":
                    # Syrian Observer: article content in <div class="entry-content">
                    article_div = soup.find("div", class_="entry-content") or soup.find("article")
                    if article_div:
                        paragraphs = article_div.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                # DESIGN: Fallback - try common article tags if source-specific fails
                if not content_text:
                    article = soup.find("article") or soup.find("div", class_=lambda x: x and "content" in x.lower())
                    if article:
                        paragraphs = article.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                # Clean content (no truncation - AI will summarize)
                if content_text:
                    # Remove extra whitespace
                    content_text = "\n\n".join(line.strip() for line in content_text.split("\n") if line.strip())
                    logger.info(f"Extracted from {url} - Image: {image_url[:50] if image_url else 'None'}, Video: {video_url[:50] if video_url else 'None'}")
                    return (content_text, image_url, video_url)
                else:
                    return ("Could not extract article text", image_url, video_url)

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching article content from {url}")
            return ("Article fetch timed out", None, None)
        except Exception as e:
            logger.warning(f"Failed to extract content from {url}: {str(e)[:100]}")
            return ("Content extraction failed", None, None)

    def _make_url_absolute(self, url_str: str, base_url: str) -> str:
        """
        Convert relative URL to absolute URL.

        Args:
            url_str: URL string (may be relative or absolute)
            base_url: Base URL to resolve relative URLs against

        Returns:
            Absolute URL string

        DESIGN: Handle all URL formats (relative, protocol-relative, absolute)
        """
        if url_str.startswith("//"):
            return f"https:{url_str}"
        elif url_str.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{url_str}"
        elif url_str.startswith("http"):
            return url_str
        else:
            # Relative path
            from urllib.parse import urljoin
            return urljoin(base_url, url_str)

    # DESIGN: Discord forum tag IDs for automatic categorization
    # Maps category names to Discord forum tag IDs
    CATEGORY_TAGS: dict[str, int] = {
        "military": 1382114547996954664,
        "breaking_news": 1382114954165092565,
        "politics": 1382115092077871174,
        "economy": 1382115132317892619,
        "health": 1382115182184235088,
        "international": 1382115248814690354,
        "social": 1382115306842882118,
    }

    def _categorize_article(self, title: str, content: str) -> Optional[int]:
        """
        Categorize article and return appropriate Discord forum tag ID.

        Args:
            title: Article title
            content: Article content

        Returns:
            Discord forum tag ID or None if no category matches

        DESIGN: Use AI to intelligently categorize articles
        AI analyzes title and content to determine most appropriate category
        Returns Discord tag ID for automatic tag application
        """
        if not self.openai_client:
            logger.warning("OpenAI client not initialized - skipping categorization")
            return None

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a news categorizer for Syrian news articles. Analyze the article and choose the MOST appropriate category from this list:\n\n- military: Military operations, armed conflicts, security forces, weapons, battles\n- breaking_news: Urgent breaking news, major developments, significant events\n- politics: Political developments, government, diplomacy, elections, policies\n- economy: Economic news, trade, business, finance, currency, markets\n- health: Health care, medical news, diseases, hospitals, public health\n- international: International relations, foreign affairs, global events affecting Syria\n- social: Society, culture, humanitarian issues, refugees, daily life\n\nRespond with ONLY the category name (one word), nothing else."
                    },
                    {
                        "role": "user",
                        "content": f"Categorize this Syrian news article.\n\nTitle: {title}\n\nContent: {content[:800]}\n\nCategory:"
                    }
                ],
                max_tokens=10,
                temperature=0.3,  # Low temperature for consistent categorization
            )

            category: str = response.choices[0].message.content.strip().lower()

            # DESIGN: Map AI category to Discord tag ID
            # Validate category and return corresponding tag ID
            if category in self.CATEGORY_TAGS:
                tag_id: int = self.CATEGORY_TAGS[category]
                logger.info(f"Article categorized as '{category}' (tag ID: {tag_id})")
                return tag_id
            else:
                # DESIGN: Fallback to 'social' tag for invalid categories
                # Better to have some tag than no tag at all
                # Social category covers culture, education, humanitarian, daily life
                logger.warning(f"Invalid category '{category}' - using 'social' as fallback")
                return self.CATEGORY_TAGS["social"]

        except Exception as e:
            logger.warning(f"Failed to categorize article: {str(e)[:100]}")
            return None

    def _generate_ai_title(self, original_title: str, content: str) -> str:
        """
        Generate a concise 3-5 word English title using OpenAI GPT-3.5-turbo.

        Args:
            original_title: Original article title (may be in Arabic)
            content: Article content for context

        Returns:
            Generated English title (3-5 words) or original if AI fails

        DESIGN: Use AI to create clean, readable English titles
        Original titles may be in Arabic or too long
        AI creates short, descriptive English titles for Discord forum posts
        """
        if not self.openai_client:
            logger.warning("OpenAI client not initialized - using original title")
            return original_title

        try:
            # DESIGN: Provide context from both title and content snippet
            # Helps AI understand the article topic better
            content_snippet: str = content[:500] if len(content) > 500 else content

            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a news headline writer. Create concise, clear English titles for news articles. Your titles must be EXACTLY 3-5 words, in English only, and capture the main topic."
                    },
                    {
                        "role": "user",
                        "content": f"Create a 3-5 word English title for this news article.\n\nOriginal title: {original_title}\n\nContent: {content_snippet}\n\nRespond with ONLY the title, nothing else."
                    }
                ],
                max_tokens=20,
                temperature=0.7,
            )

            ai_title: str = response.choices[0].message.content.strip()

            # DESIGN: Validate AI response
            # Ensure title is reasonable length and not empty
            if ai_title and 3 <= len(ai_title.split()) <= 7:
                logger.info(f"AI generated title: '{ai_title}' from '{original_title[:50]}'")
                return ai_title
            else:
                logger.warning(f"AI title invalid: '{ai_title}' - using original")
                return original_title

        except Exception as e:
            logger.warning(f"Failed to generate AI title: {str(e)[:100]}")
            return original_title

    def _generate_bilingual_summary(self, content: str) -> tuple[str, str]:
        """
        Generate bilingual summaries (Arabic and English) using OpenAI GPT-3.5-turbo.

        Args:
            content: Full article content

        Returns:
            Tuple of (arabic_summary, english_summary)

        DESIGN: Create concise summaries in both languages for Syrian audience
        Arabic summary comes first (primary language)
        English summary second (for international readers)
        Each summary is 3-4 sentences, capturing key points
        """
        if not self.openai_client:
            logger.warning("OpenAI client not initialized - using truncated content")
            truncated: str = content[:300] + "..." if len(content) > 300 else content
            return (truncated, truncated)

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a bilingual news summarizer for Syrian news. Create comprehensive summaries in both Arabic and English. Read the FULL article content and capture ALL important details including: key facts, quotes, context, significance, and any important statements. NEVER omit important context or quotes. Make the summary as long as needed to convey the full story, but stay under Discord's character limit."
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this news article in both Arabic and English. IMPORTANT: Include ALL important context, quotes, and details from the article. Don't truncate or leave out key information that readers need to understand the full story.\n\nFormat your response EXACTLY as:\n\nARABIC:\n[Comprehensive Arabic summary with ALL key context and quotes]\n\nENGLISH:\n[Comprehensive English summary with ALL key context and quotes]\n\nArticle content:\n{content}"
                    }
                ],
                temperature=0.7,
            )

            result: str = response.choices[0].message.content.strip()

            # DESIGN: Parse AI response to extract Arabic and English summaries
            # Expected format: "ARABIC:\n[text]\n\nENGLISH:\n[text]"
            arabic_summary: str = ""
            english_summary: str = ""

            if "ARABIC:" in result and "ENGLISH:" in result:
                parts: list[str] = result.split("ENGLISH:")
                arabic_part: str = parts[0].replace("ARABIC:", "").strip()
                english_part: str = parts[1].strip()

                arabic_summary = arabic_part
                english_summary = english_part

                logger.info(f"Generated bilingual summaries (AR: {len(arabic_summary)} chars, EN: {len(english_summary)} chars)")
            else:
                logger.warning("AI summary format invalid - using truncated content")
                truncated: str = content[:300] + "..." if len(content) > 300 else content
                return (truncated, truncated)

            return (arabic_summary, english_summary)

        except Exception as e:
            logger.warning(f"Failed to generate bilingual summary: {str(e)[:100]}")
            truncated: str = content[:300] + "..." if len(content) > 300 else content
            return (truncated, truncated)

    async def test_sources(self) -> Dict[str, Any]:
        """
        Test all news sources and return status.

        Returns:
            Dictionary with source test results
        """
        results: dict[str, Any] = {}

        for source_key, source_info in self.NEWS_SOURCES.items():
            try:
                feed: feedparser.FeedParserDict = feedparser.parse(
                    source_info["rss_url"]
                )
                results[source_key] = {
                    "name": source_info["name"],
                    "status": "✅ Working" if feed.entries else "⚠️ No entries",
                    "articles_found": len(feed.entries),
                    "last_updated": feed.feed.get("updated", "Unknown"),
                }
            except Exception as e:
                results[source_key] = {
                    "name": source_info["name"],
                    "status": f"❌ Error: {str(e)[:50]}",
                    "articles_found": 0,
                    "last_updated": "N/A",
                }

        return results
