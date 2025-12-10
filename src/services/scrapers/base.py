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
import asyncio
import aiohttp
from pathlib import Path
from types import TracebackType
from typing import Optional, Type
from dataclasses import dataclass
from datetime import datetime
from openai import OpenAI, APIError, RateLimitError, APIConnectionError, AuthenticationError

from src.core.logger import logger
from src.utils import AICache


# =============================================================================
# OpenAI Error Handling
# =============================================================================

class OpenAIRetryConfig:
    """Configuration for OpenAI API retry behavior."""
    MAX_RETRIES: int = 3
    BASE_DELAY: float = 1.0  # seconds
    MAX_DELAY: float = 60.0  # seconds
    EXPONENTIAL_BASE: float = 2.0


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
        self.openai_client: Optional[OpenAI] = OpenAI(api_key=api_key, timeout=30.0) if api_key else None

        # DESIGN: Initialize AI response cache to reduce OpenAI API costs
        self.ai_cache: AICache = AICache(ai_cache_filename)

    async def __aenter__(self) -> "BaseScraper":
        """Async context manager entry."""
        if self.session_headers:
            self.session = aiohttp.ClientSession(headers=self.session_headers)
        else:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
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
                    logger.info(f"{self.log_emoji} Loaded Posted Article IDs", [
                        ("Type", self.content_type.capitalize()),
                        ("Count", str(len(self.fetched_urls))),
                    ])
            else:
                logger.info(f"{self.log_emoji} No Cache Found", [
                    ("Type", self.content_type.capitalize()),
                    ("Action", "Starting fresh"),
                ])
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(f"{self.log_emoji} Failed to Load Posted Article IDs", [
                ("Type", self.content_type.capitalize()),
                ("Error", str(e)),
            ])
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

            logger.info("💾 Saved Posted Article IDs", [
                ("Type", self.content_type.capitalize()),
                ("Count", str(len(ids_to_save))),
            ])
        except (IOError, OSError) as e:
            logger.warning(f"{self.log_emoji} Failed to Save Posted Article IDs", [
                ("Type", self.content_type.capitalize()),
                ("Error", str(e)),
            ])

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
                system_prompt="""You are a news headline writer. Generate a concise, engaging title in ENGLISH ONLY (3-7 words) for this article.

CRITICAL RULES:
1. The title MUST be in English, not Arabic. Translate Arabic titles to English.
2. ACCURACY IS PARAMOUNT: Extract location names, people names, and key facts DIRECTLY from the article content.
3. DO NOT hallucinate or guess location names. If the article mentions "Aleppo" (حلب), use "Aleppo". If it mentions "Homs" (حمص), use "Homs".
4. Read the content carefully to identify the correct city/location mentioned.
5. Return ONLY the English title, no quotes or explanation.""",
                user_prompt=f"Original title: {original_title}\n\nFull article content:\n{content}",
                max_tokens=50,
                temperature=0.3,
            )
            title: str = response.strip().strip('"').strip("'")
            self.ai_cache.set(cache_key, title)
            return title
        except Exception as e:
            logger.warning("🤖 Failed to Generate Title", [
                ("Error", str(e)),
            ])
            return original_title

    def _truncate_at_sentence(self, text: str, max_length: int) -> str:
        """
        Truncate text at a sentence boundary, not mid-word.

        Args:
            text: Text to truncate
            max_length: Maximum allowed length

        Returns:
            Text truncated at the last complete sentence within max_length
        """
        if len(text) <= max_length:
            return text

        # Find the last sentence boundary within max_length
        # Look for sentence-ending punctuation (. ! ? and Arabic equivalents)
        truncated = text[:max_length]

        # Find last sentence boundary
        last_period = -1
        for i in range(len(truncated) - 1, -1, -1):
            if truncated[i] in '.!?。؟':
                last_period = i
                break

        if last_period > max_length // 2:  # Only use if we keep at least half the content
            return truncated[:last_period + 1]

        # Fallback: truncate at last space to avoid mid-word cut
        last_space = truncated.rfind(' ')
        if last_space > max_length // 2:
            return truncated[:last_space] + "..."

        # Last resort: just truncate with ellipsis
        return truncated[:max_length - 3] + "..."

    async def _generate_bilingual_summary(
        self,
        content: str,
        min_length: int = 150,
        max_length: int = 500,
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

            # Truncate at sentence boundary
            fallback = self._truncate_at_sentence(clean_content, max_length)

            logger.info("🤖 Using Fallback Summary", [
                ("Reason", "AI unavailable"),
                ("Length", f"{len(fallback)} chars"),
            ])
            return (fallback, fallback)  # Return same content for both languages

        if not self.openai_client:
            logger.warning("🤖 OpenAI Client Not Initialized", [
                ("Action", "Using fallback summaries"),
            ])
            return create_fallback_summaries()

        # Log input content info
        logger.info("🤖 Generating Bilingual Summary", [
            ("Content Length", f"{len(content)} chars"),
            ("Content Preview", content[:100].replace('\n', ' ') + "..."),
            ("Min Length", str(min_length)),
            ("Max Length", str(max_length)),
        ])

        # Check cache first
        cache_key: str = f"summary_{content[:200]}"
        cached: Optional[str] = self.ai_cache.get(cache_key)
        if cached and isinstance(cached, str):
            parts = cached.split("|||")
            if len(parts) == 2:
                logger.info("🤖 Cache Hit - Bilingual Summary", [
                    ("Arabic Length", str(len(parts[0]))),
                    ("English Length", str(len(parts[1]))),
                ])
                return (parts[0], parts[1])

        try:
            response = await self._call_openai(
                system_prompt=f"""You are a news summarizer. Generate summaries in Arabic AND English.

OUTPUT FORMAT (VERY IMPORTANT - follow exactly):
[Arabic summary here]|||[English summary here]

The three pipe characters ||| MUST separate the two summaries. Do NOT use any other separator.

REQUIREMENTS:
- Each summary: {min_length}-{max_length} characters
- Arabic summary comes FIRST, then |||, then English summary
- CRITICAL: Both summaries MUST end with complete sentences. NEVER cut off mid-sentence or mid-word.
- Include: what happened, who, where, why it matters
- If approaching the character limit, finish your current sentence and stop. Do not add "..." or incomplete thoughts.

Example format:
هذا ملخص باللغة العربية يحتوي على التفاصيل الكاملة للمقال.|||This is the English summary with full article details.""",
                user_prompt=f"Summarize this article:\n\n{content}",
                max_tokens=1200,
                temperature=0.5,
            )

            # Log raw AI response for debugging
            logger.debug("🤖 AI Raw Response", [
                ("Length", str(len(response))),
                ("Preview", response[:200].replace('\n', ' ') if response else "empty"),
                ("Has Separator", str("|||" in response)),
            ])

            # Try primary separator first
            parts = response.split("|||")

            # Fallback: try other common separators if primary fails
            if len(parts) < 2:
                for sep in ["---", "===", "\n\n\n", "ENGLISH:", "English:"]:
                    if sep in response:
                        parts = response.split(sep, 1)
                        if len(parts) >= 2:
                            logger.info("🤖 Used Fallback Separator", [
                                ("Separator", repr(sep)),
                            ])
                            break

            if len(parts) >= 2:
                arabic: str = parts[0].strip()
                english: str = parts[1].strip()

                # Validate summaries - reject if too short (likely just author name or garbage)
                if len(arabic) < min_length or len(english) < min_length:
                    logger.warning("🤖 AI Summary Too Short - Rejected", [
                        ("Arabic Len", str(len(arabic))),
                        ("Arabic Preview", arabic[:50] if arabic else "empty"),
                        ("English Len", str(len(english))),
                        ("English Preview", english[:50] if english else "empty"),
                        ("Min Required", str(min_length)),
                        ("Action", "Using fallback"),
                    ])
                    return create_fallback_summaries()

                # Safety truncation at sentence boundary (not mid-word)
                truncated_arabic = False
                truncated_english = False
                if len(arabic) > max_length:
                    arabic = self._truncate_at_sentence(arabic, max_length)
                    truncated_arabic = True
                if len(english) > max_length:
                    english = self._truncate_at_sentence(english, max_length)
                    truncated_english = True

                # Validate that Arabic and English are actually different
                if arabic == english or arabic[:100] == english[:100]:
                    logger.warning("🤖 AI Summary Not Bilingual - Rejected", [
                        ("Reason", "Arabic and English are identical"),
                        ("Action", "Using fallback"),
                    ])
                    return create_fallback_summaries()

                # Log successful generation
                logger.success("🤖 Bilingual Summary Generated", [
                    ("Arabic Len", str(len(arabic))),
                    ("English Len", str(len(english))),
                    ("Arabic Truncated", str(truncated_arabic)),
                    ("English Truncated", str(truncated_english)),
                ])

                # Cache the result
                self.ai_cache.set(cache_key, f"{arabic}|||{english}")
                return (arabic, english)

            # AI returned invalid format - use fallback
            logger.warning("🤖 Invalid AI Summary Format", [
                ("Response Length", str(len(response)) if response else "0"),
                ("Response Preview", response[:150].replace('\n', ' ') if response else "empty"),
                ("Parts Found", str(len(parts))),
                ("Action", "Using fallback"),
            ])
            return create_fallback_summaries()

        except Exception as e:
            logger.warning("🤖 Failed to Generate Summaries", [
                ("Error", str(e)),
                ("Action", "Using fallback"),
            ])
            return create_fallback_summaries()

    async def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> str:
        """
        Make an OpenAI API call with exponential backoff retry.

        Args:
            system_prompt: System message for context
            user_prompt: User message with content
            max_tokens: Maximum tokens in response
            temperature: Creativity level (0-1)

        Returns:
            AI response text

        Raises:
            AuthenticationError: Invalid API key (no retry)
            APIError: After all retries exhausted
        """
        if not self.openai_client:
            return ""

        last_exception: Optional[Exception] = None

        for attempt in range(OpenAIRetryConfig.MAX_RETRIES):
            try:
                # Use asyncio.to_thread to make synchronous OpenAI call non-blocking
                response = await asyncio.to_thread(
                    self.openai_client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return response.choices[0].message.content.strip()

            except AuthenticationError as e:
                # Invalid API key - don't retry
                logger.error("OpenAI Authentication Failed", [
                    ("Error", "Invalid API key"),
                    ("Action", "Check OPENAI_API_KEY environment variable"),
                ])
                raise

            except RateLimitError as e:
                # Rate limited - retry with exponential backoff
                delay = min(
                    OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt),
                    OpenAIRetryConfig.MAX_DELAY
                )
                logger.warning("OpenAI Rate Limited", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Retry In", f"{delay:.1f}s"),
                ])
                last_exception = e
                await asyncio.sleep(delay)

            except APIConnectionError as e:
                # Network error - retry with backoff
                delay = min(
                    OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt),
                    OpenAIRetryConfig.MAX_DELAY
                )
                logger.warning("OpenAI Connection Error", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Error", str(e)[:100]),
                    ("Retry In", f"{delay:.1f}s"),
                ])
                last_exception = e
                await asyncio.sleep(delay)

            except APIError as e:
                # Other API error - retry with backoff
                delay = min(
                    OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt),
                    OpenAIRetryConfig.MAX_DELAY
                )
                logger.warning("OpenAI API Error", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Error", str(e)[:100]),
                    ("Retry In", f"{delay:.1f}s"),
                ])
                last_exception = e
                await asyncio.sleep(delay)

            except TimeoutError as e:
                # Timeout - retry with backoff
                delay = min(
                    OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt),
                    OpenAIRetryConfig.MAX_DELAY
                )
                logger.warning("OpenAI Timeout", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Retry In", f"{delay:.1f}s"),
                ])
                last_exception = e
                await asyncio.sleep(delay)

        # All retries exhausted
        logger.error("OpenAI API Failed After Retries", [
            ("Retries", str(OpenAIRetryConfig.MAX_RETRIES)),
            ("Last Error", str(last_exception)[:100] if last_exception else "Unknown"),
        ])
        return ""


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["Article", "BaseScraper"]
