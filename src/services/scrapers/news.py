"""
Othman Discord Bot - News Scraper Service
=========================================

Fetches Syrian news from Enab Baladi RSS feed.

Sources:
- Enab Baladi (عنب بلدي) - Primary Syrian news

Features:
- RSS feed parsing with fallback
- Image extraction from articles
- AI-powered title generation
- Bilingual summaries (Arabic + English)
- Duplicate detection
- Article categorization for Discord tags

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Optional

from src.core.logger import logger
from src.core.config import NEWS_FORUM_TAGS
from src.services.scrapers.base import BaseScraper, Article


class NewsScraper(BaseScraper):
    """Scrapes Syrian news from Enab Baladi."""

    # DESIGN: Single RSS source - Enab Baladi only
    # Syria-focused independent journalism with media-rich articles
    NEWS_SOURCES: dict[str, dict[str, str]] = {
        "enab_baladi": {
            "name": "Enab Baladi",
            "emoji": "",
            "rss_url": "https://www.enabbaladi.net/feed/",
            "language": "Arabic/English",
        },
    }

    # DESIGN: Discord forum tag IDs for automatic categorization
    CATEGORY_TAGS: dict[str, int] = NEWS_FORUM_TAGS

    def __init__(self) -> None:
        """Initialize the news scraper."""
        super().__init__(
            cache_filename="data/posted_urls.json",
            ai_cache_filename="data/news_ai_cache.json",
            content_type="news",
            log_emoji="📰",
        )

    async def fetch_latest_news(
        self, max_articles: int = 5, hours_back: int = 168
    ) -> list[Article]:
        """
        Fetch latest Syrian news from all sources.

        Args:
            max_articles: Maximum number of articles to return per source
            hours_back: How far back to search (default: 7 days)

        Returns:
            List of Article objects (newest unposted first)
        """
        all_articles: list[Article] = []
        cutoff_time: datetime = datetime.now() - timedelta(hours=hours_back)

        for source_key, source_info in self.NEWS_SOURCES.items():
            try:
                articles = await self._fetch_from_source(
                    source_key, source_info, cutoff_time, max_articles * 10
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

        # Sort by published date (newest first)
        all_articles.sort(key=lambda x: x.published_date, reverse=True)

        # Filter to only NEW articles
        new_articles: list[Article] = []
        seen_ids: set[str] = set()

        for article in all_articles:
            article_id = self._extract_article_id(article.url)

            if article_id in seen_ids:
                continue

            seen_ids.add(article_id)

            if article_id not in self.fetched_urls:
                new_articles.append(article)

        if new_articles:
            logger.info(f"✅ Found {len(new_articles)} NEW unposted articles")
            return new_articles[:max_articles]
        else:
            logger.info(f"📭 No new articles found")
            return []

    async def _fetch_from_source(
        self,
        source_key: str,
        source_info: dict[str, str],
        cutoff_time: datetime,
        max_articles: int,
    ) -> list[Article]:
        """Fetch articles from a single RSS source."""
        articles: list[Article] = []

        feed = feedparser.parse(source_info["rss_url"])

        if not feed.entries:
            logger.warning(f"No entries found in {source_info['name']} feed")
            return articles

        for entry in feed.entries[: max_articles * 2]:
            try:
                # Parse date
                published_date = self._parse_date(entry)
                if not published_date or published_date < cutoff_time:
                    continue

                # Extract image from RSS
                image_url = await self._extract_image(entry)

                # Get summary
                summary = (
                    entry.get("summary", "")
                    or entry.get("description", "")
                    or entry.get("content", [{}])[0].get("value", "")
                )
                summary = BeautifulSoup(summary, "html.parser").get_text()
                summary = summary[:500] + "..." if len(summary) > 500 else summary

                # Extract full content, image, and video
                full_content, scraped_image, scraped_video = await self._extract_full_content(
                    entry.get("link", ""), source_key
                )

                # Prefer scraped image
                if not image_url and scraped_image:
                    image_url = scraped_image

                # Skip articles without media
                if not image_url and not scraped_video:
                    logger.info(f"Skipping article without media: {entry.get('title', 'Untitled')[:50]}")
                    continue

                # Generate AI content
                article_id = self._extract_article_id(entry.get("link", ""))
                original_title = entry.get("title", "Untitled")

                # Check cache for title
                cached_title = self.ai_cache.get_title(article_id)
                if cached_title:
                    ai_title = cached_title["english_title"]
                    logger.info(f"💾 Cache hit: Using cached title for article {article_id}")
                else:
                    ai_title = await self._generate_title(original_title, full_content)
                    self.ai_cache.cache_title(article_id, original_title, ai_title)
                    logger.info(f"🔄 Cache miss: Generated title for article {article_id}")

                # Check cache for summaries
                cached_summary = self.ai_cache.get_summary(article_id)
                if cached_summary:
                    arabic_summary = cached_summary["arabic_summary"]
                    english_summary = cached_summary["english_summary"]
                    logger.info(f"💾 Cache hit: Using cached summary for article {article_id}")
                else:
                    arabic_summary, english_summary = await self._generate_bilingual_summary(full_content)
                    self.ai_cache.cache_summary(article_id, arabic_summary, english_summary)
                    logger.info(f"🔄 Cache miss: Generated summary for article {article_id}")

                # Categorize article
                category_tag_id = await self._categorize_article(ai_title, full_content)

                article = Article(
                    title=ai_title,
                    url=entry.get("link", ""),
                    summary=summary,
                    full_content=full_content,
                    arabic_summary=arabic_summary,
                    english_summary=english_summary,
                    image_url=image_url,
                    video_url=scraped_video,
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

        # Try content
        content = (
            entry.get("summary", "")
            or entry.get("description", "")
            or entry.get("content", [{}])[0].get("value", "")
        )

        if content:
            soup = BeautifulSoup(content, "html.parser")
            img_tag = soup.find("img")
            if img_tag and img_tag.get("src"):
                return img_tag["src"]

        return None

    async def _extract_full_content(
        self, url: str, source_key: str
    ) -> tuple[str, Optional[str], Optional[str]]:
        """
        Extract full article text, image, and video from article URL.

        Returns:
            Tuple of (full text, image URL, video URL)
        """
        if not url or not self.session:
            return ("Content unavailable", None, None)

        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    return ("Could not fetch article content", None, None)

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract image
                image_url: Optional[str] = None
                article_div = (
                    soup.find("div", class_="entry-content")
                    or soup.find("article")
                    or soup.find("div", class_=lambda x: x and "content" in x.lower())
                )

                if article_div:
                    img_tags = article_div.find_all("img")
                    for img in img_tags:
                        src = img.get("src") or img.get("data-src")
                        if src and any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                            image_url = self._make_url_absolute(src, url)
                            break

                # Extract video
                video_url: Optional[str] = None
                if article_div:
                    # Check for video tags
                    video_tag = article_div.find("video")
                    if video_tag:
                        source_tag = video_tag.find("source")
                        if source_tag and source_tag.get("src"):
                            src = source_tag.get("src")
                            if any(ext in src.lower() for ext in [".mp4", ".webm", ".mov"]):
                                video_url = self._make_url_absolute(src, url)
                        elif video_tag.get("src"):
                            src = video_tag.get("src")
                            if any(ext in src.lower() for ext in [".mp4", ".webm", ".mov"]):
                                video_url = self._make_url_absolute(src, url)

                    # Check for iframe embeds
                    if not video_url:
                        iframe = article_div.find("iframe")
                        if iframe and iframe.get("src"):
                            iframe_src = iframe.get("src")
                            if any(domain in iframe_src for domain in ["youtube.com", "youtu.be", "twitter.com", "x.com", "vimeo.com"]):
                                video_url = iframe_src if iframe_src.startswith("http") else f"https:{iframe_src}"

                # Extract content
                content_text = ""

                if source_key == "enab_baladi":
                    article_div = soup.find("div", class_="entry-content")
                    if article_div:
                        paragraphs = article_div.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                # Fallback
                if not content_text:
                    article = soup.find("article") or soup.find("div", class_=lambda x: x and "content" in x.lower())
                    if article:
                        paragraphs = article.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                if content_text:
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
        """Convert relative URL to absolute URL."""
        if url_str.startswith("//"):
            return f"https:{url_str}"
        elif url_str.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{url_str}"
        elif url_str.startswith("http"):
            return url_str
        else:
            from urllib.parse import urljoin
            return urljoin(base_url, url_str)

    async def _categorize_article(self, title: str, content: str) -> Optional[int]:
        """
        Categorize article and return Discord forum tag ID.

        Uses AI to analyze content and select appropriate category.
        """
        if not self.openai_client:
            return None

        try:
            import asyncio

            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a news categorizer for Syrian news articles. Analyze the article and choose the MOST appropriate category from this list:\n\n- military: Military operations, armed conflicts, security forces\n- breaking_news: Urgent breaking news, major developments\n- politics: Political developments, government, diplomacy\n- economy: Economic news, trade, business, finance\n- health: Health care, medical news, diseases\n- international: International relations, foreign affairs\n- social: Society, culture, humanitarian issues\n\nRespond with ONLY the category name (one word), nothing else."
                    },
                    {
                        "role": "user",
                        "content": f"Categorize this Syrian news article.\n\nTitle: {title}\n\nContent: {content[:800]}\n\nCategory:"
                    }
                ],
                max_tokens=10,
                temperature=0.3,
            )

            category = response.choices[0].message.content.strip().lower()

            if category in self.CATEGORY_TAGS:
                tag_id = self.CATEGORY_TAGS[category]
                logger.info(f"Article categorized as '{category}' (tag ID: {tag_id})")
                return tag_id
            else:
                logger.warning(f"Invalid category '{category}' - using 'social' as fallback")
                return self.CATEGORY_TAGS["social"]

        except Exception as e:
            logger.warning(f"Failed to categorize article: {str(e)[:100]}")
            return None
