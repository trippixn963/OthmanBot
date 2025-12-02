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
- Team tag detection for forum categorization

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Optional

from src.core.logger import logger
from src.services.scrapers.base import BaseScraper, Article


class SoccerScraper(BaseScraper):
    """Scrapes soccer/football news from Kooora.com."""

    # DESIGN: Single RSS source - Kooora.com
    # Leading Arabic sports website with comprehensive soccer coverage
    SOCCER_SOURCES: dict[str, dict[str, str]] = {
        "kooora": {
            "name": "Kooora",
            "emoji": "",
            "rss_url": "https://feeds.footballco.com/kooora/feed/6p5bsxot7te8yick",
            "language": "Arabic",
        },
    }

    # DESIGN: Soccer team categories for AI-powered tagging
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
        super().__init__(
            cache_filename="data/posted_soccer_urls.json",
            ai_cache_filename="data/soccer_ai_cache.json",
            content_type="soccer",
            log_emoji="⚽",
        )

    async def fetch_latest_soccer_news(
        self, max_articles: int = 5, hours_back: int = 24
    ) -> list[Article]:
        """
        Fetch latest soccer news from Kooora.com.

        Args:
            max_articles: Maximum number of articles to return
            hours_back: How far back to search (default: 24 hours)

        Returns:
            List of Article objects (newest unposted first)
        """
        all_articles: list[Article] = []
        cutoff_time: datetime = datetime.now() - timedelta(hours=hours_back)

        for source_key, source_info in self.SOCCER_SOURCES.items():
            try:
                articles = await self._fetch_from_source(
                    source_key, source_info, cutoff_time, max_articles * 10
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
            logger.info(f"✅ Found {len(new_articles)} NEW unposted soccer articles")
            return new_articles[:max_articles]
        else:
            logger.info(f"📭 No new soccer articles found")
            return []

    async def _fetch_from_source(
        self,
        source_key: str,
        source_info: dict[str, str],
        cutoff_time: datetime,
        max_articles: int,
    ) -> list[Article]:
        """Fetch articles from Kooora RSS feed."""
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

                # Extract full content and image
                full_content, scraped_image = await self._extract_full_content(
                    entry.get("link", ""), source_key
                )

                # Prefer scraped image
                if not image_url and scraped_image:
                    image_url = scraped_image

                # Skip articles with fetch errors
                error_messages = [
                    "Article fetch timed out",
                    "Could not fetch article content",
                    "Could not extract article text",
                    "Content extraction failed",
                    "Content unavailable"
                ]
                if any(error_msg in full_content for error_msg in error_messages):
                    continue

                # Skip articles without images
                if not image_url:
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
                    ai_title = await self._generate_soccer_title(original_title, full_content)
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

                # Check cache for team tag
                cached_team = self.ai_cache.get_team_tag(article_id)
                if cached_team:
                    team_tag = cached_team
                    logger.info(f"💾 Cache hit: Using cached team tag for article {article_id}")
                else:
                    team_tag = await self._detect_team_tag(ai_title, full_content)
                    self.ai_cache.cache_team_tag(article_id, team_tag)
                    logger.info(f"🔄 Cache miss: Generated team tag for article {article_id}")

                article = Article(
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
    ) -> tuple[str, Optional[str]]:
        """
        Extract full article text and image from article URL.

        Returns:
            Tuple of (full text, image URL)
        """
        if not url or not self.session:
            return ("Content unavailable", None)

        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    return ("Could not fetch article content", None)

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                # Extract image
                image_url: Optional[str] = None
                article_div = (
                    soup.find("div", class_="article-content")
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

                # Extract content - Kooora specific
                content_text = ""

                if source_key == "kooora":
                    article_body = soup.find("div", class_="fco-article-body")

                    if article_body:
                        paragraphs = article_body.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                    # Fallback: Try main tag
                    if not content_text:
                        main_tag = soup.find("main")
                        if main_tag:
                            paragraphs = main_tag.find_all("p")
                            content_paragraphs = [p for p in paragraphs if len(p.get_text().strip()) > 50]
                            content_text = "\n\n".join([p.get_text().strip() for p in content_paragraphs])

                # Generic fallback
                if not content_text:
                    article = soup.find("article") or soup.find("div", class_=lambda x: x and "content" in x.lower())
                    if article:
                        paragraphs = article.find_all("p")
                        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])

                if content_text:
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

    async def _generate_soccer_title(self, original_title: str, content: str) -> str:
        """
        Generate a concise 3-5 word English title for soccer articles.

        Args:
            original_title: Original article title (may be in Arabic)
            content: Article content for context

        Returns:
            Generated English title or original if AI fails
        """
        if not self.openai_client:
            return original_title

        try:
            response = await self._call_openai(
                system_prompt="You are a sports headline writer specializing in soccer/football news. Create concise, clear English titles for soccer articles. Your titles must be EXACTLY 3-5 words, in English only, and capture the main soccer topic.",
                user_prompt=f"Create a 3-5 word English title for this soccer article.\n\nOriginal title: {original_title}\n\nContent: {content[:500]}\n\nRespond with ONLY the title.",
                max_tokens=20,
                temperature=0.7,
            )

            ai_title = response.strip()
            if ai_title and 3 <= len(ai_title.split()) <= 7:
                logger.info(f"⚽ AI generated soccer title: '{ai_title}'")
                return ai_title
            return original_title
        except Exception as e:
            logger.warning(f"Failed to generate AI soccer title: {str(e)[:100]}")
            return original_title

    async def _detect_team_tag(self, title: str, content: str) -> str:
        """
        Detect which team the article is primarily about using AI.

        Args:
            title: Article title
            content: Article content

        Returns:
            Team name string matching one of TEAM_CATEGORIES
        """
        if not self.openai_client:
            return "International"

        try:
            teams_list = ", ".join(self.TEAM_CATEGORIES)

            response = await self._call_openai(
                system_prompt=f"You are a soccer news categorization expert. Analyze articles and determine which team they are primarily about. You must respond with EXACTLY ONE of these team names: {teams_list}. If the article is about multiple teams, international soccer, or general news, respond with 'International'.",
                user_prompt=f"Which team is this soccer article primarily about? Respond with ONLY the team name.\n\nTitle: {title}\n\nContent: {content[:800]}",
                max_tokens=10,
                temperature=0.3,
            )

            detected_team = response.strip()
            if detected_team in self.TEAM_CATEGORIES:
                logger.info(f"⚽ Detected team tag: '{detected_team}'")
                return detected_team
            else:
                logger.warning(f"AI returned invalid team '{detected_team}' - using International")
                return "International"

        except Exception as e:
            logger.warning(f"Failed to detect team tag: {str(e)[:100]}")
            return "International"
