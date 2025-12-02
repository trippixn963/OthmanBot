"""
Othman Discord Bot - Base Scraper Service
==========================================

Base class with shared functionality for all scrapers (news, soccer, gaming).

Features:
- URL/article ID deduplication and persistence
- AI caching for OpenAI responses
- Async context manager for HTTP sessions
- Common article dataclass

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import re
import json
import aiohttp
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime
from openai import OpenAI

from src.core.logger import logger
from src.utils import AICache


# =============================================================================
# Article Dataclass
# =============================================================================

@dataclass
class Article:
    """
    Base article dataclass with common fields for all content types.

    Used by news, soccer, and gaming scrapers.
    """
    title: str
    url: str
    summary: str
    full_content: str
    arabic_summary: str
    english_summary: str
    image_url: Optional[str]
    published_date: datetime = None
    source: str = ""
    source_emoji: str = ""
    # Optional fields for specific scrapers
    video_url: Optional[str] = None  # News only
    category_tag_id: Optional[int] = None  # News forum tag
    team_tag: Optional[str] = None  # Soccer team tag
    game_category: Optional[str] = None  # Gaming category


# =============================================================================
# Base Scraper Class
# =============================================================================

class BaseScraper:
    """
    Base scraper class with shared functionality.

    All scrapers (news, soccer, gaming) inherit from this class
    to avoid code duplication.
    """

    def __init__(
        self,
        cache_filename: str,
        ai_cache_filename: str,
        content_type: str,
        log_emoji: str = "📰",
        session_headers: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Initialize the base scraper.

        Args:
            cache_filename: JSON file for posted article IDs (e.g., "data/posted_urls.json")
            ai_cache_filename: JSON file for AI response cache (e.g., "data/news_ai_cache.json")
            content_type: Type of content for logging (e.g., "news", "soccer", "gaming")
            log_emoji: Emoji for log messages (e.g., "📰", "⚽", "🎮")
            session_headers: Optional custom headers for HTTP session
        """
        self.session: Optional[aiohttp.ClientSession] = None
        self.content_type: str = content_type
        self.log_emoji: str = log_emoji
        self.session_headers: Optional[dict[str, str]] = session_headers

        # DESIGN: Track fetched URLs to avoid duplicate posts
        # Stored as set for O(1) lookup performance
        # PERSISTED to JSON file to survive bot restarts
        self.fetched_urls: set[str] = set()
        self.max_cached_urls: int = 1000
        self.posted_urls_file: Path = Path(cache_filename)
        self.posted_urls_file.parent.mkdir(exist_ok=True)

        # Load previously posted URLs on startup
        self._load_posted_urls()

        # DESIGN: Initialize OpenAI client for title/summary generation
        api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        self.openai_client: Optional[OpenAI] = OpenAI(api_key=api_key) if api_key else None

        # DESIGN: Initialize AI response cache to reduce OpenAI API costs
        self.ai_cache: AICache = AICache(ai_cache_filename)

    async def __aenter__(self) -> "BaseScraper":
        """Async context manager entry."""
        if self.session_headers:
            self.session = aiohttp.ClientSession(headers=self.session_headers)
        else:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self.session:
            await self.session.close()

    # -------------------------------------------------------------------------
    # URL Deduplication
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_article_id(url: str) -> str:
        """
        Extract unique article ID from URL for deduplication.

        DESIGN: Use article ID instead of full URL to prevent duplicate posts
        Problem: Full URLs can be truncated, have different encodings, or vary in format
        Solution: Extract the numeric article ID which is stable and unique

        Args:
            url: Article URL

        Returns:
            Article ID extracted from URL, or full URL if extraction fails
        """
        # Try /NUMBERS/ pattern first
        match = re.search(r'/(\d+)/', url)
        if not match:
            # Try -NUMBERS- pattern
            match = re.search(r'-(\d+)-', url)
        if not match:
            # Try /NUMBERS at end of URL
            match = re.search(r'/(\d+)$', url)
        if match:
            return match.group(1)
        # Fallback to full URL if no ID found
        return url

    def _load_posted_urls(self) -> None:
        """
        Load previously posted article IDs from JSON file.

        DESIGN: Convert all entries to article IDs for reliable deduplication
        Backward compatible: converts old URL entries to article IDs
        """
        try:
            if self.posted_urls_file.exists():
                with open(self.posted_urls_file, "r", encoding="utf-8") as f:
                    data: dict[str, list[str]] = json.load(f)
                    url_list: list[str] = data.get("posted_urls", [])
                    self.fetched_urls = set(self._extract_article_id(url) for url in url_list)
                    logger.info(
                        f"{self.log_emoji} Loaded {len(self.fetched_urls)} posted {self.content_type} article IDs from cache"
                    )
            else:
                logger.info(f"No posted {self.content_type} article IDs cache found - starting fresh")
        except Exception as e:
            logger.warning(f"Failed to load posted {self.content_type} article IDs: {e}")
            self.fetched_urls = set()

    def _save_posted_urls(self) -> None:
        """
        Save posted article IDs to JSON file.

        DESIGN: Persist article IDs to disk after each post
        Saves ALL article IDs to prevent losing recently posted IDs
        """
        try:
            # Save ALL IDs sorted for consistency
            ids_to_save: list[str] = sorted(list(self.fetched_urls))

            with open(self.posted_urls_file, "w", encoding="utf-8") as f:
                json.dump({"posted_urls": ids_to_save}, f, indent=2, ensure_ascii=False)

            logger.info(f"💾 Saved {len(ids_to_save)} posted {self.content_type} article IDs to cache")
        except Exception as e:
            logger.warning(f"Failed to save posted {self.content_type} article IDs: {e}")

    def add_posted_url(self, url: str) -> None:
        """
        Add a URL to the posted set and save to disk.

        Args:
            url: Article URL or ID to mark as posted
        """
        article_id: str = self._extract_article_id(url)
        self.fetched_urls.add(article_id)
        self._save_posted_urls()

    def is_already_posted(self, url: str) -> bool:
        """
        Check if an article has already been posted.

        Args:
            url: Article URL to check

        Returns:
            True if already posted, False otherwise
        """
        article_id: str = self._extract_article_id(url)
        return article_id in self.fetched_urls

    # -------------------------------------------------------------------------
    # AI Generation Methods
    # -------------------------------------------------------------------------

    async def _generate_title(self, original_title: str, content: str) -> str:
        """
        Generate an English title using AI.

        Args:
            original_title: Original article title
            content: Article content for context

        Returns:
            AI-generated English title
        """
        if not self.openai_client:
            return original_title

        # Check cache first
        cache_key: str = f"title_{original_title[:100]}"
        cached: Optional[str] = self.ai_cache.get(cache_key)
        if cached:
            return cached

        try:
            response = await self._call_openai(
                system_prompt="You are a news headline writer. Generate a concise, engaging title in ENGLISH ONLY (3-7 words) for this article. IMPORTANT: The title MUST be in English, not Arabic. Translate Arabic titles to English. Return ONLY the English title, no quotes or explanation.",
                user_prompt=f"Original title: {original_title}\n\nContent preview: {content[:500]}",
                max_tokens=50,
                temperature=0.7,
            )
            title: str = response.strip().strip('"').strip("'")
            self.ai_cache.set(cache_key, title)
            return title
        except Exception as e:
            logger.warning(f"Failed to generate title: {e}")
            return original_title

    async def _generate_bilingual_summary(
        self,
        content: str,
        min_length: int = 150,
        max_length: int = 400,
    ) -> tuple[str, str]:
        """
        Generate bilingual summaries (Arabic and English) using AI.

        Args:
            content: Full article content
            min_length: Minimum chars per summary
            max_length: Maximum chars per summary

        Returns:
            Tuple of (arabic_summary, english_summary)
        """
        # Fallback function to create summaries from raw content
        def create_fallback_summaries() -> tuple[str, str]:
            """Create basic summaries from raw content when AI is unavailable."""
            # Clean and truncate content
            clean_content = content.strip()

            # Create a simple truncated summary
            if len(clean_content) > max_length:
                fallback = clean_content[:max_length - 3] + "..."
            else:
                fallback = clean_content

            logger.info(f"Using fallback summary (AI unavailable) - {len(fallback)} chars")
            return (fallback, fallback)  # Return same content for both languages

        if not self.openai_client:
            logger.warning("OpenAI client not initialized - using fallback summaries")
            return create_fallback_summaries()

        # Check cache first
        cache_key: str = f"summary_{content[:200]}"
        cached: Optional[str] = self.ai_cache.get(cache_key)
        if cached:
            parts = cached.split("|||")
            if len(parts) == 2:
                return (parts[0], parts[1])

        try:
            response = await self._call_openai(
                system_prompt=f"""You are a news summarizer. Generate complete, standalone summaries of this article in both Arabic and English.

CRITICAL REQUIREMENTS:
- Each summary MUST be {min_length}-{max_length} characters (count carefully!)
- Summaries MUST be COMPLETE - end with a proper conclusion, never mid-sentence
- DO NOT exceed {max_length} characters - write concisely to fit within the limit
- Include: what happened, who is involved, why it matters
- Arabic summary first, then English translation of the same content
- Separate with "|||"
- Format: Arabic summary|||English summary

The English summary should be a direct translation of the Arabic summary to maintain consistency.""",
                user_prompt=f"Article content:\n\n{content}",
                max_tokens=800,
                temperature=0.7,
            )

            parts = response.split("|||")
            if len(parts) >= 2:
                arabic: str = parts[0].strip()
                english: str = parts[1].strip()

                # Safety truncation
                if len(arabic) > max_length:
                    arabic = arabic[: max_length - 3] + "..."
                if len(english) > max_length:
                    english = english[: max_length - 3] + "..."

                # Cache the result
                self.ai_cache.set(cache_key, f"{arabic}|||{english}")
                return (arabic, english)

            # AI returned invalid format - use fallback
            logger.warning("AI returned invalid summary format - using fallback")
            return create_fallback_summaries()

        except Exception as e:
            logger.warning(f"Failed to generate summaries: {e} - using fallback")
            return create_fallback_summaries()

    async def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> str:
        """
        Make an OpenAI API call.

        Args:
            system_prompt: System message for context
            user_prompt: User message with content
            max_tokens: Maximum tokens in response
            temperature: Creativity level (0-1)

        Returns:
            AI response text
        """
        if not self.openai_client:
            return ""

        import asyncio

        # DESIGN: Use asyncio.to_thread to make synchronous OpenAI call non-blocking
        response = await asyncio.to_thread(
            self.openai_client.chat.completions.create,
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        return response.choices[0].message.content.strip()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["Article", "BaseScraper"]
