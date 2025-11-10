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
import asyncio
import feedparser
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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
    published_date: datetime
    source: str
    source_emoji: str


class NewsScraper:
    """Scrapes Syrian news from multiple sources."""

    # DESIGN: Multiple RSS sources for redundancy and diverse coverage
    # Enab Baladi is primary (Syria-focused independent journalism)
    # Al Jazeera provides major network coverage
    # Syrian Observer offers English alternative
    NEWS_SOURCES: dict[str, dict[str, str]] = {
        "enab_baladi": {
            "name": "Enab Baladi",
            "emoji": "🍇",
            "rss_url": "https://www.enabbaladi.net/feed/",
            "language": "Arabic/English",
        },
        "aljazeera": {
            "name": "Al Jazeera Arabic",
            "emoji": "📡",
            "rss_url": "https://www.aljazeera.net/xml/rss/all.xml",
            "language": "Arabic",
        },
        "syrian_observer": {
            "name": "Syrian Observer",
            "emoji": "📰",
            "rss_url": "https://syrianobserver.com/feed/",
            "language": "English",
        },
    }

    def __init__(self) -> None:
        """Initialize the news scraper."""
        self.session: Optional[aiohttp.ClientSession] = None
        # DESIGN: Track fetched URLs to avoid duplicate posts
        # Stored as set for O(1) lookup performance
        # Limited to last 1000 URLs to prevent memory growth
        self.fetched_urls: set[str] = set()
        self.max_cached_urls: int = 1000

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

    async def fetch_latest_news(
        self, max_articles: int = 5, hours_back: int = 24
    ) -> List[NewsArticle]:
        """
        Fetch latest Syrian news from all sources.

        Args:
            max_articles: Maximum number of articles to return per source
            hours_back: Only fetch articles from last N hours

        Returns:
            List of NewsArticle objects, sorted by date (newest first)
        """
        all_articles: list[NewsArticle] = []
        cutoff_time: datetime = datetime.now() - timedelta(hours=hours_back)

        # DESIGN: Fetch from all sources concurrently for speed
        # Each source operates independently to prevent one failure blocking others
        for source_key, source_info in self.NEWS_SOURCES.items():
            try:
                articles: list[NewsArticle] = await self._fetch_from_source(
                    source_key, source_info, cutoff_time, max_articles
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

        # DESIGN: Sort by published date (newest first) for chronological posting
        # Users see most recent news first
        all_articles.sort(key=lambda x: x.published_date, reverse=True)

        # DESIGN: Filter out duplicates based on URL
        # Prevents same article from appearing twice from different sources
        unique_articles: list[NewsArticle] = []
        seen_urls: set[str] = set()

        for article in all_articles:
            if article.url not in seen_urls and article.url not in self.fetched_urls:
                unique_articles.append(article)
                seen_urls.add(article.url)

        # DESIGN: Update cache of fetched URLs
        # Maintain maximum cache size to prevent memory growth
        self.fetched_urls.update(seen_urls)
        if len(self.fetched_urls) > self.max_cached_urls:
            # Remove oldest URLs (convert to list, remove first half)
            urls_list: list[str] = list(self.fetched_urls)
            self.fetched_urls = set(urls_list[-self.max_cached_urls :])

        logger.info(
            f"Fetched {len(unique_articles)} unique articles from {len(self.NEWS_SOURCES)} sources"
        )
        return unique_articles[:max_articles]

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

                # DESIGN: Extract full article content from the URL
                # Fetch the actual article page and extract text
                full_content: str = await self._extract_full_content(
                    entry.get("link", ""), source_key
                )

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

                article: NewsArticle = NewsArticle(
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

    async def _extract_full_content(self, url: str, source_key: str) -> str:
        """
        Extract full article text content from article URL.

        Args:
            url: Article URL to fetch
            source_key: Source identifier (enab_baladi, aljazeera, syrian_observer)

        Returns:
            Full article text content or fallback message

        DESIGN: Each news source has different HTML structure
        Use specific selectors for each source to extract article content
        """
        if not url or not self.session:
            return "Content unavailable"

        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    return "Could not fetch article content"

                html: str = await response.text()
                soup: BeautifulSoup = BeautifulSoup(html, "html.parser")

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
                    return content_text
                else:
                    return "Could not extract article text"

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching article content from {url}")
            return "Article fetch timed out"
        except Exception as e:
            logger.warning(f"Failed to extract content from {url}: {str(e)[:100]}")
            return "Content extraction failed"

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
                        "content": "You are a bilingual news summarizer for Syrian news. Create concise summaries in both Arabic and English. Each summary should be 3-4 sentences capturing the key points of the article."
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this news article in both Arabic and English. Format your response EXACTLY as:\n\nARABIC:\n[3-4 sentence Arabic summary]\n\nENGLISH:\n[3-4 sentence English summary]\n\nArticle content:\n{content[:2000]}"
                    }
                ],
                max_tokens=400,
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
