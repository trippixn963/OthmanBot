"""
Othman Discord Bot - Soccer Scraper Service
==========================================

Fetches soccer/football news from Kooora.com RSS feed.

Sources:
- Kooora.com (كووورة) - Leading Arabic sports website

Features:
- RSS feed parsing
- Image extraction from articles
- AI-powered title generation
- Bilingual summaries (Arabic + English)
- Duplicate detection
- Soccer-focused content

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
class SoccerArticle:
    """Represents a soccer news article with all necessary information."""

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
    team_tag: Optional[str] = None  # AI-detected team tag for categorization


class SoccerScraper:
    """Scrapes soccer/football news from Kooora.com."""

    # DESIGN: Single RSS source - Kooora.com
    # Leading Arabic sports website with comprehensive soccer coverage
    SOCCER_SOURCES: dict[str, dict[str, str]] = {
        "kooora": {
            "name": "Kooora",
            "emoji": "⚽",
            "rss_url": "https://feeds.footballco.com/kooora/feed/6p5bsxot7te8yick",
            "language": "Arabic",
        },
    }

    # DESIGN: Soccer team categories for AI-powered tagging
    # Maps team names to their exact string for tag matching
    # AI will analyze article content and return ONE of these team names
    # Fallback to "International" for multi-team or general soccer news
    TEAM_CATEGORIES: list[str] = [
        "Barcelona",
        "Real Madrid",
        "Atletico Madrid",
        "Liverpool",
        "Bayern Munich",
        "Manchester City",
        "Manchester United",
        "Arsenal",
        "Chelsea",
        "Paris Saint-Germain",
        "Juventus",
        "AC Milan",
        "Inter Milan",
        "Napoli",
        "Borussia Dortmund",
        "Roma",
        "Tottenham Hotspur",
        "International",
        "Champions League",
    ]

    def __init__(self) -> None:
        """Initialize the soccer scraper."""
        self.session: Optional[aiohttp.ClientSession] = None

        # DESIGN: Track fetched URLs to avoid duplicate posts
        # Stored as set for O(1) lookup performance
        # Limited to last 1000 URLs to prevent memory growth
        # PERSISTED to JSON file to survive bot restarts
        self.fetched_urls: set[str] = set()
        self.max_cached_urls: int = 1000
        self.posted_urls_file: Path = Path("data/posted_soccer_urls.json")
        self.posted_urls_file.parent.mkdir(exist_ok=True)

        # DESIGN: Load previously posted URLs on startup
        # Prevents re-posting same articles after bot restart
        self._load_posted_urls()

        # DESIGN: Initialize OpenAI client for title generation and summaries
        # Uses API key from environment variables
        api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        self.openai_client: Optional[OpenAI] = OpenAI(api_key=api_key) if api_key else None

    async def __aenter__(self) -> "SoccerScraper":
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self.session:
            await self.session.close()

    def _load_posted_urls(self) -> None:
        """
        Load previously posted URLs from JSON file.

        DESIGN: Read URLs from persistent storage on bot startup
        Prevents duplicate posts after bot restarts
        Gracefully handles missing or corrupt file
        """
        try:
            if self.posted_urls_file.exists():
                with open(self.posted_urls_file, "r", encoding="utf-8") as f:
                    data: dict[str, list[str]] = json.load(f)
                    url_list: list[str] = data.get("posted_urls", [])
                    self.fetched_urls = set(url_list)
                    logger.info(f"⚽ Loaded {len(self.fetched_urls)} posted soccer URLs from cache")
            else:
                logger.info("No posted soccer URLs cache found - starting fresh")
        except Exception as e:
            logger.warning(f"Failed to load posted soccer URLs: {e}")
            self.fetched_urls = set()

    def _save_posted_urls(self) -> None:
        """
        Save posted URLs to JSON file.

        DESIGN: Persist URLs to disk after each post
        Ensures duplicate prevention survives bot restarts
        Saves ALL URLs (no limit) to prevent losing recently posted URLs
        """
        try:
            # DESIGN: Save ALL URLs in the set to avoid random subset bug
            # Previous bug: list(set)[-1000:] takes random 1000 URLs due to undefined set order
            # This caused newly-added URLs to be lost when saving
            # Fix: Save ALL URLs, sort for consistency
            urls_to_save: list[str] = sorted(list(self.fetched_urls))

            with open(self.posted_urls_file, "w", encoding="utf-8") as f:
                json.dump({"posted_urls": urls_to_save}, f, indent=2, ensure_ascii=False)

            logger.info(f"⚽ Saved {len(urls_to_save)} posted soccer URLs to cache")
        except Exception as e:
            logger.warning(f"Failed to save posted soccer URLs: {e}")

    async def fetch_latest_soccer_news(
        self, max_articles: int = 5, hours_back: int = 24
    ) -> List[SoccerArticle]:
        """
        Fetch latest soccer news from Kooora.com with backfill logic.

        BACKFILL STRATEGY:
        1. Always check for new (unposted) articles first
        2. If no new articles, go backwards through older articles
        3. Post one old article per interval until a new one appears
        4. This ensures consistent posting even during slow news periods

        Args:
            max_articles: Maximum number of articles to return
            hours_back: How far back to search (default: 24 hours)

        Returns:
            List of SoccerArticle objects (newest unposted first, or oldest if all new posted)
        """
        all_articles: list[SoccerArticle] = []
        cutoff_time: datetime = datetime.now() - timedelta(hours=hours_back)

        # DESIGN: Fetch from soccer source
        for source_key, source_info in self.SOCCER_SOURCES.items():
            try:
                articles: list[SoccerArticle] = await self._fetch_from_source(
                    source_key, source_info, cutoff_time, max_articles * 10  # Fetch more for backfill
                )
                all_articles.extend(articles)
                logger.success(
                    f"⚽ Fetched {len(articles)} soccer articles from {source_info['name']}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to fetch soccer from {source_info['name']}: {str(e)[:100]}"
                )
                continue

        # DESIGN: Sort by published date (newest first) initially
        # This allows us to check latest articles first
        all_articles.sort(key=lambda x: x.published_date, reverse=True)

        # DESIGN: Separate new articles from old articles
        # New = not in posted URLs cache
        new_articles: list[SoccerArticle] = []
        old_articles: list[SoccerArticle] = []
        seen_urls: set[str] = set()

        for article in all_articles:
            if article.url in seen_urls:
                continue  # Skip duplicates within this fetch

            seen_urls.add(article.url)

            if article.url not in self.fetched_urls:
                new_articles.append(article)
            else:
                old_articles.append(article)

        # DESIGN: Backfill logic - prefer new, fallback to old
        # If we have new articles, use those (newest first)
        # If no new articles, use old articles (oldest first, to go backwards chronologically)
        if new_articles:
            logger.info(f"✅ Found {len(new_articles)} NEW unposted soccer articles")
            selected_articles: list[SoccerArticle] = new_articles[:max_articles]
        elif old_articles:
            # DESIGN: Reverse sort old articles to get OLDEST first
            # This creates a backfill effect: post older articles in chronological order
            old_articles.sort(key=lambda x: x.published_date)  # Oldest first
            logger.info(f"⏪ No new soccer articles - backfilling from {len(old_articles)} older articles")
            selected_articles: list[SoccerArticle] = old_articles[:max_articles]
        else:
            logger.warning("⚠️ No soccer articles found (all filtered or none available)")
            return []

        logger.info(
            f"⚽ Returning {len(selected_articles)} soccer article(s)"
        )
        return selected_articles

    async def _fetch_from_source(
        self,
        source_key: str,
        source_info: dict[str, str],
        cutoff_time: datetime,
        max_articles: int,
    ) -> List[SoccerArticle]:
        """
        Fetch articles from Kooora RSS feed.

        Args:
            source_key: Source identifier
            source_info: Source configuration dict
            cutoff_time: Only fetch articles newer than this
            max_articles: Maximum articles to fetch

        Returns:
            List of SoccerArticle objects from this source
        """
        articles: list[SoccerArticle] = []

        # DESIGN: Use feedparser for reliable RSS parsing
        # feedparser handles various RSS/Atom formats automatically
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
                # RSS feeds store images in different tags
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
                # Fetch the actual article page and extract text + media
                full_content: str
                scraped_image: Optional[str]
                full_content, scraped_image = await self._extract_full_content(
                    entry.get("link", ""), source_key
                )

                # DESIGN: Prefer scraped image from article page over RSS feed image
                # Article page images are usually better quality and more relevant
                if not image_url and scraped_image:
                    image_url = scraped_image

                # DESIGN: Skip articles with fetch errors (timeout, extraction failed, etc.)
                # These error messages are returned as content by _extract_full_content
                # Don't post articles with error messages as content
                error_messages: list[str] = [
                    "Article fetch timed out",
                    "Could not fetch article content",
                    "Could not extract article text",
                    "Content extraction failed",
                    "Content unavailable"
                ]
                if any(error_msg in full_content for error_msg in error_messages):
                    logger.info(f"⚽ Skipping soccer article due to fetch error: {entry.get('title', 'Untitled')[:50]}")
                    continue

                # DESIGN: Skip articles without images
                # NEVER post articles without media - user requirement
                if not image_url:
                    logger.info(f"⚽ Skipping soccer article without image: {entry.get('title', 'Untitled')[:50]}")
                    continue

                # DESIGN: Generate AI-powered 3-5 word English title
                # Replaces original title (may be Arabic or too long) with clean English title
                original_title: str = entry.get("title", "Untitled")
                ai_title: str = self._generate_ai_title(original_title, full_content)

                # DESIGN: Generate bilingual summaries (Arabic + English)
                # AI creates concise 3-4 sentence summaries in both languages
                arabic_summary: str
                english_summary: str
                arabic_summary, english_summary = self._generate_bilingual_summary(full_content)

                # DESIGN: Detect team tag for article categorization
                # AI analyzes title and content to determine primary team
                # Used for Discord forum tag assignment
                team_tag: str = self._detect_team_tag(ai_title, full_content)

                article: SoccerArticle = SoccerArticle(
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
                    team_tag=team_tag,
                )

                articles.append(article)

                if len(articles) >= max_articles:
                    break

            except Exception as e:
                logger.warning(
                    f"Failed to parse soccer article from {source_info['name']}: {str(e)[:100]}"
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
        date_tuple = entry.get("published_parsed") or entry.get("updated_parsed")

        if date_tuple:
            try:
                return datetime(*date_tuple[:6])
            except (TypeError, ValueError):
                pass

        # DESIGN: Fallback to current time if no date available
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
            source_key: Source identifier (kooora)

        Returns:
            Tuple of (full article text content, image URL or None)

        DESIGN: Kooora.com has specific HTML structure
        Use specific selectors to extract article content and images
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

                # Try to find image in article content areas
                article_div = (
                    soup.find("div", class_="article-content")
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

                # DESIGN: Kooora-specific content extraction
                content_text: str = ""

                if source_key == "kooora":
                    # Kooora: article content in various div structures
                    article_div = (
                        soup.find("div", class_="article-content")
                        or soup.find("div", class_="news-text")
                        or soup.find("article")
                    )
                    if article_div:
                        # Get all paragraphs
                        paragraphs = article_div.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                # DESIGN: Fallback - try common article tags
                if not content_text:
                    article = soup.find("article") or soup.find("div", class_=lambda x: x and "content" in x.lower())
                    if article:
                        paragraphs = article.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                # Clean content (no truncation - AI will summarize)
                if content_text:
                    # Remove extra whitespace
                    content_text = "\n\n".join(line.strip() for line in content_text.split("\n") if line.strip())
                    logger.info(f"⚽ Extracted from {url} - Image: {image_url[:50] if image_url else 'None'}")
                    return (content_text, image_url)
                else:
                    return ("Could not extract article text", image_url)

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching soccer article from {url}")
            return ("Article fetch timed out", None)
        except Exception as e:
            logger.warning(f"Failed to extract soccer content from {url}: {str(e)[:100]}")
            return ("Content extraction failed", None)

    def _generate_ai_title(self, original_title: str, content: str) -> str:
        """
        Generate a concise 3-5 word English title using OpenAI GPT-3.5-turbo.

        Args:
            original_title: Original article title (may be in Arabic)
            content: Article content for context

        Returns:
            Generated English title (3-5 words) or original if AI fails

        DESIGN: Use AI to create clean, readable English titles for soccer news
        Original titles may be in Arabic or too long
        AI creates short, descriptive English titles for Discord forum posts
        """
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
                        "content": "You are a sports headline writer specializing in soccer/football news. Create concise, clear English titles for soccer articles. Your titles must be EXACTLY 3-5 words, in English only, and capture the main soccer topic (teams, players, matches, transfers, etc.)."
                    },
                    {
                        "role": "user",
                        "content": f"Create a 3-5 word English title for this soccer article.\n\nOriginal title: {original_title}\n\nContent: {content_snippet}\n\nRespond with ONLY the title, nothing else."
                    }
                ],
                max_tokens=20,
                temperature=0.7,
            )

            ai_title: str = response.choices[0].message.content.strip()

            # DESIGN: Validate AI response
            if ai_title and 3 <= len(ai_title.split()) <= 7:
                logger.info(f"⚽ AI generated soccer title: '{ai_title}' from '{original_title[:50]}'")
                return ai_title
            else:
                logger.warning(f"AI soccer title invalid: '{ai_title}' - using original")
                return original_title

        except Exception as e:
            logger.warning(f"Failed to generate AI soccer title: {str(e)[:100]}")
            return original_title

    def _generate_bilingual_summary(self, content: str) -> tuple[str, str]:
        """
        Generate bilingual summaries (Arabic and English) using OpenAI GPT-3.5-turbo.

        Args:
            content: Full article content

        Returns:
            Tuple of (arabic_summary, english_summary)

        DESIGN: Create concise summaries in both languages for Syrian soccer fans
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
                        "content": "You are a bilingual sports news summarizer for soccer/football articles. Create comprehensive summaries in both Arabic and English. Read the FULL article content and capture ALL important details including: key facts, player/team quotes, context, significance, and any important statements. NEVER omit important context or quotes. Make the summary as long as needed to convey the full story, but stay under Discord's character limit."
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this soccer article in both Arabic and English. IMPORTANT: Include ALL important context, quotes, and details from the article. Don't truncate or leave out key information that readers need to understand the full story.\n\nFormat your response EXACTLY as:\n\nARABIC:\n[Comprehensive Arabic summary with ALL key context and quotes]\n\nENGLISH:\n[Comprehensive English summary with ALL key context and quotes]\n\nArticle content:\n{content}"
                    }
                ],
                temperature=0.7,
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

                logger.info(f"⚽ Generated bilingual soccer summaries (AR: {len(arabic_summary)} chars, EN: {len(english_summary)} chars)")
            else:
                logger.warning("AI soccer summary format invalid - using truncated content")
                truncated: str = content[:300] + "..." if len(content) > 300 else content
                return (truncated, truncated)

            return (arabic_summary, english_summary)

        except Exception as e:
            logger.warning(f"Failed to generate bilingual soccer summary: {str(e)[:100]}")
            truncated: str = content[:300] + "..." if len(content) > 300 else content
            return (truncated, truncated)

    def _detect_team_tag(self, title: str, content: str) -> str:
        """
        Detect which team the article is primarily about using AI.

        Args:
            title: Article title
            content: Article content

        Returns:
            Team name string matching one of TEAM_CATEGORIES, defaults to "International"

        DESIGN: Use AI to categorize articles by primary team mentioned
        Helps organize soccer forum channel with proper team tags
        AI analyzes title and content to determine the main team focus
        Falls back to "International" for general news or multi-team articles
        """
        if not self.openai_client:
            logger.warning("OpenAI client not initialized - using International tag")
            return "International"

        try:
            teams_list: str = ", ".join(self.TEAM_CATEGORIES)
            content_snippet: str = content[:800] if len(content) > 800 else content

            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": f"You are a soccer news categorization expert. Analyze articles and determine which team they are primarily about. You must respond with EXACTLY ONE of these team names: {teams_list}. If the article is about multiple teams, international soccer, World Cup, or general soccer news, respond with 'International'. If it's about Champions League in general, respond with 'Champions League'."
                    },
                    {
                        "role": "user",
                        "content": f"Which team is this soccer article primarily about? Respond with ONLY the team name from the list provided.\n\nTitle: {title}\n\nContent: {content_snippet}"
                    }
                ],
                max_tokens=10,
                temperature=0.3,  # Low temperature for consistent categorization
            )

            detected_team: str = response.choices[0].message.content.strip()

            # DESIGN: Validate AI response against known team categories
            # Ensure returned team name exactly matches one of our categories
            if detected_team in self.TEAM_CATEGORIES:
                logger.info(f"⚽ Detected team tag: '{detected_team}' for article '{title[:40]}'")
                return detected_team
            else:
                logger.warning(f"AI returned invalid team '{detected_team}' - using International")
                return "International"

        except Exception as e:
            logger.warning(f"Failed to detect team tag: {str(e)[:100]} - using International")
            return "International"
