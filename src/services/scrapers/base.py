"""
OthmanBot - Base Scraper Service
==========================================

Base class with shared functionality for all scrapers (news, soccer).

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
import asyncio
import time
import random
import aiohttp
from types import TracebackType
from typing import Optional, Type
from dataclasses import dataclass
from datetime import datetime
from openai import OpenAI, APIError, RateLimitError, APIConnectionError, AuthenticationError

from src.core.logger import logger
from src.services.database import get_db
from src.utils import AICache
from src.utils.language import is_english_only
from src.utils.similarity import cosine_similarity, SIMILARITY_THRESHOLD


# =============================================================================
# OpenAI Error Handling
# =============================================================================

class OpenAIRetryConfig:
    """Configuration for OpenAI API retry behavior."""
    MAX_RETRIES: int = 3
    BASE_DELAY: float = 1.0  # seconds
    MAX_DELAY: float = 60.0  # seconds
    EXPONENTIAL_BASE: float = 2.0
    JITTER_RANGE: float = 0.1  # 10% jitter


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts based on API response times and errors.

    Tracks latency and automatically throttles when API is slow or returns errors.
    """

    def __init__(self) -> None:
        self._retry_after: float = 0.0  # Timestamp when retry is allowed
        self._latency_samples: list[float] = []
        self._max_samples: int = 10
        self._throttle_threshold_ms: float = 2000.0  # Throttle if latency > 2s
        self._throttle_multiplier: float = 1.0  # Current throttle level (1.0 = normal)

    def record_latency(self, latency_ms: float) -> None:
        """Record API call latency and adjust throttle."""
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > self._max_samples:
            self._latency_samples.pop(0)

        # Calculate average latency
        avg_latency = sum(self._latency_samples) / len(self._latency_samples)

        # Adjust throttle based on latency
        if avg_latency > self._throttle_threshold_ms:
            self._throttle_multiplier = min(3.0, self._throttle_multiplier * 1.2)
        elif avg_latency < self._throttle_threshold_ms / 2:
            self._throttle_multiplier = max(1.0, self._throttle_multiplier * 0.9)

    def set_retry_after(self, seconds: float) -> None:
        """Set retry-after from API header."""
        self._retry_after = time.time() + seconds
        logger.tree("Rate Limiter - Retry After Set", [
            ("Wait Seconds", f"{seconds:.1f}"),
            ("Current Throttle", f"{self._throttle_multiplier:.1f}x"),
            ("Avg Latency", f"{self.avg_latency_ms:.0f}ms"),
        ], emoji="⏳")

    async def wait_if_needed(self) -> None:
        """Wait if rate limited or throttled."""
        # Check retry-after
        now = time.time()
        if self._retry_after > now:
            wait_time = self._retry_after - now
            logger.tree("Rate Limiter - Waiting (Retry-After)", [
                ("Wait Time", f"{wait_time:.1f}s"),
                ("Avg Latency", f"{self.avg_latency_ms:.0f}ms"),
            ], emoji="⏸️")
            await asyncio.sleep(wait_time)

        # Apply throttle multiplier
        if self._throttle_multiplier > 1.0:
            throttle_wait = (self._throttle_multiplier - 1.0) * 0.5
            if throttle_wait > 0.1:  # Only log if significant wait
                logger.tree("Rate Limiter - Throttling Active", [
                    ("Throttle Level", f"{self._throttle_multiplier:.1f}x"),
                    ("Extra Wait", f"{throttle_wait:.2f}s"),
                    ("Avg Latency", f"{self.avg_latency_ms:.0f}ms"),
                ], emoji="🐌")
            await asyncio.sleep(throttle_wait)

    def get_delay_with_jitter(self, base_delay: float) -> float:
        """Get delay with random jitter."""
        jitter = base_delay * OpenAIRetryConfig.JITTER_RANGE * random.random()
        return base_delay + jitter

    @property
    def throttle_level(self) -> float:
        """Current throttle multiplier."""
        return self._throttle_multiplier

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if not self._latency_samples:
            return 0.0
        return sum(self._latency_samples) / len(self._latency_samples)


# Global rate limiter instance
_rate_limiter = AdaptiveRateLimiter()


# =============================================================================
# Article Dataclass
# =============================================================================

@dataclass
class Article:
    """
    Base article dataclass with common fields for all content types.

    Used by news and soccer scrapers.
    """
    title: str
    url: str
    summary: str
    full_content: str
    arabic_summary: str
    english_summary: str
    image_url: Optional[str]
    published_date: Optional[datetime] = None
    source: str = ""
    source_emoji: str = ""
    # Optional fields for specific scrapers
    video_url: Optional[str] = None  # News only
    category_tag_id: Optional[int] = None  # News forum tag
    team_tag: Optional[str] = None  # Soccer team tag
    game_category: Optional[str] = None  # Reserved for future use
    key_quote: Optional[str] = None  # Extracted quote from article


# =============================================================================
# Base Scraper Class
# =============================================================================

class BaseScraper:
    """
    Base scraper class with shared functionality.

    All scrapers (news, soccer) inherit from this class
    to avoid code duplication.
    """

    def __init__(
        self,
        content_type: str,
        log_emoji: str = "📰",
        session_headers: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Initialize the base scraper.

        Args:
            content_type: Type of content for logging (e.g., "news", "soccer")
            log_emoji: Emoji for log messages (e.g., "📰", "⚽")
            session_headers: Optional custom headers for HTTP session
        """
        self.session: Optional[aiohttp.ClientSession] = None
        self.content_type: str = content_type
        self.log_emoji: str = log_emoji
        self.session_headers: Optional[dict[str, str]] = session_headers

        # DESIGN: Use unified database for posted URLs
        self._db = get_db()

        # Load previously posted URLs into memory for O(1) lookup
        self.fetched_urls: set[str] = self._db.get_posted_urls_set(content_type)
        logger.tree("Loaded Posted Article IDs", [
            ("Type", content_type.capitalize()),
            ("Count", str(len(self.fetched_urls))),
            ("Backend", "SQLite"),
        ], emoji=log_emoji)

        # DESIGN: Initialize OpenAI client for title/summary generation
        api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        self.openai_client: Optional[OpenAI] = OpenAI(api_key=api_key, timeout=30.0) if api_key else None

        # DESIGN: Initialize AI response cache (now SQLite-backed)
        self.ai_cache: AICache = AICache(content_type)

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

    def add_posted_url(self, url: str) -> None:
        """
        Add a URL to the posted set and save to database.

        Args:
            url: Article URL or ID to mark as posted
        """
        article_id: str = self._extract_article_id(url)

        # Add to in-memory set for O(1) lookup
        self.fetched_urls.add(article_id)

        # Persist to database
        self._db.mark_url_posted(self.content_type, article_id)

        # Cleanup old entries if needed
        self._db.cleanup_posted_urls(self.content_type)

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
    # Content-Based Duplicate Detection
    # -------------------------------------------------------------------------

    def is_duplicate_content(self, content: str, url: str) -> tuple[bool, float]:
        """
        Check if content is similar to recently posted articles.

        Args:
            content: Article content to check
            url: Article URL (for logging)

        Returns:
            Tuple of (is_duplicate, similarity_score)
        """
        article_id = self._extract_article_id(url)

        # Get recent content from database
        recent_content = self._db.get_recent_content(self.content_type, limit=50)

        if not recent_content:
            return (False, 0.0)

        # Check similarity against each recent article
        highest_similarity = 0.0
        matching_id = None

        for existing_id, existing_content in recent_content:
            # Skip self
            if existing_id == article_id:
                continue

            similarity = cosine_similarity(content, existing_content)
            if similarity > highest_similarity:
                highest_similarity = similarity
                matching_id = existing_id

        is_duplicate = highest_similarity >= SIMILARITY_THRESHOLD

        if is_duplicate:
            logger.tree(f"{self.log_emoji} Duplicate Content Detected", [
                ("Article ID", article_id),
                ("Similarity", f"{highest_similarity:.2%}"),
                ("Matches Article", matching_id or "Unknown"),
                ("Threshold", f"{SIMILARITY_THRESHOLD:.0%}"),
                ("Compared Against", f"{len(recent_content)} articles"),
            ], emoji="🔍")

        return (is_duplicate, highest_similarity)

    def store_content_for_similarity(self, content: str, url: str) -> None:
        """
        Store content for future similarity checks.

        Args:
            content: Article content
            url: Article URL
        """
        article_id = self._extract_article_id(url)
        self._db.store_content_hash(self.content_type, article_id, content)

    # -------------------------------------------------------------------------
    # Dead Letter Queue
    # -------------------------------------------------------------------------

    def is_quarantined(self, url: str) -> bool:
        """
        Check if an article is quarantined due to repeated failures.

        Args:
            url: Article URL to check

        Returns:
            True if quarantined and should be skipped
        """
        article_id = self._extract_article_id(url)
        return self._db.is_quarantined(self.content_type, article_id)

    def record_failure(self, url: str, error: str) -> int:
        """
        Record an article processing failure.

        Args:
            url: Article URL
            error: Error message

        Returns:
            Current failure count
        """
        article_id = self._extract_article_id(url)
        failure_count = self._db.add_to_dead_letter(
            self.content_type, article_id, url, error
        )
        # Logging handled by database method
        return failure_count

    def clear_failure(self, url: str) -> None:
        """
        Clear failure record after successful processing.

        Args:
            url: Article URL
        """
        article_id = self._extract_article_id(url)
        self._db.clear_dead_letter(self.content_type, article_id)

    # -------------------------------------------------------------------------
    # Metrics Recording
    # -------------------------------------------------------------------------

    def record_metric(self, metric_name: str, value: float) -> None:
        """
        Record a scraper metric.

        Args:
            metric_name: Name of metric (e.g., 'ai_latency_ms', 'articles_processed')
            value: Metric value
        """
        self._db.record_metric(self.content_type, metric_name, value)

    def get_metrics_summary(self, hours_back: int = 24) -> dict:
        """
        Get metrics summary for this scraper.

        Args:
            hours_back: Number of hours to look back

        Returns:
            Dict with metric statistics
        """
        return self._db.get_metrics_summary(self.content_type, hours_back)

    # -------------------------------------------------------------------------
    # AI Generation Methods
    # -------------------------------------------------------------------------

    async def _generate_title(self, original_title: str, content: str) -> Optional[str]:
        """
        Generate an English title using AI.

        Args:
            original_title: Original article title
            content: Article content for context

        Returns:
            AI-generated English title, or None if generation fails
        """
        if not self.openai_client:
            logger.warning("🤖 OpenAI Client Not Initialized For Title", [
                ("Action", "Skipping article"),
                ("Original", original_title[:50]),
            ])
            return None

        # Check cache first
        cache_key: str = f"title_{original_title[:100]}"
        cached: Optional[str] = self.ai_cache.get(cache_key)
        if cached:
            logger.info("🤖 Cache Hit - Title", [
                ("Original", original_title[:30]),
                ("Cached", cached[:30]),
            ])
            return cached

        logger.info("🤖 Generating Title", [
            ("Original", original_title[:50]),
            ("Content Length", f"{len(content)} chars"),
        ])

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

            # Validate the title is actually English
            if not is_english_only(title):
                logger.warning("🤖 Generated Title Not English - Retrying", [
                    ("Original", original_title[:30]),
                    ("Generated", title[:30]),
                ])
                # Retry with more explicit instruction
                response = await self._call_openai(
                    system_prompt="Translate this Arabic headline to English. Return ONLY the English translation, nothing else.",
                    user_prompt=original_title,
                    max_tokens=50,
                    temperature=0.2,
                )
                title = response.strip().strip('"').strip("'")

                # If still not English, generate a generic title from content
                if not is_english_only(title):
                    logger.warning("🤖 Retry Failed - Generating From Content", [
                        ("Original", original_title[:30]),
                    ])
                    response = await self._call_openai(
                        system_prompt="Generate a 3-5 word English headline summarizing this article. English only.",
                        user_prompt=f"Article content:\n{content[:500]}",
                        max_tokens=30,
                        temperature=0.3,
                    )
                    title = response.strip().strip('"').strip("'")

            self.ai_cache.set(cache_key, title)
            logger.success("🤖 Title Generated", [
                ("Original", original_title[:30]),
                ("Generated", title[:50]),
            ])
            return title
        except Exception as e:
            logger.warning("🤖 Failed to Generate Title", [
                ("Error", str(e)),
                ("Original", original_title[:30]),
                ("Action", "Skipping article"),
            ])
            # Return None to signal that this article should be skipped
            return None

    async def _extract_key_quote(self, content: str) -> Optional[str]:
        """
        Extract a compelling key quote from article content using AI.

        Args:
            content: Full article content

        Returns:
            Extracted quote in English, or None if extraction fails
        """
        if not self.openai_client:
            logger.tree("Key Quote Extraction Skipped", [
                ("Reason", "OpenAI client not initialized"),
                ("Content Length", f"{len(content)} chars"),
            ], emoji="⏭️")
            return None

        # Check cache first (v2 = English-only validation added)
        cache_key: str = f"quote_v2_{content[:100]}"
        cached: Optional[str] = self.ai_cache.get(cache_key)
        if cached:
            # Double-check cached quote is English (safety net)
            if is_english_only(cached):
                logger.tree("Key Quote Cache Hit", [
                    ("Quote", cached[:50]),
                    ("Source", "AI Cache"),
                ], emoji="💾")
                return cached
            else:
                logger.tree("Key Quote Cache Invalidated", [
                    ("Reason", "Cached quote not English"),
                    ("Quote Preview", cached[:30]),
                ], emoji="🔄")

        logger.tree("Extracting Key Quote", [
            ("Content Length", f"{len(content)} chars"),
            ("Method", "OpenAI API"),
        ], emoji="🔍")

        try:
            response = await self._call_openai(
                system_prompt="""You are a news editor. Extract the most compelling quote or statement from this article and OUTPUT IN ENGLISH ONLY.

CRITICAL RULES:
1. OUTPUT MUST BE IN ENGLISH - translate Arabic content to English
2. Find an actual statement, fact, or quote from the article - NOT a summary
3. Keep it concise: 1-2 sentences maximum (under 200 characters)
4. Choose something impactful that captures the essence of the news
5. Do NOT add quotation marks - return just the text
6. Prefer direct quotes from officials, witnesses, or key figures if available
7. NEVER output Arabic text - always translate to English

Examples of CORRECT output:
- The Ministry of Health prioritizes cancer patients due to the severity of their condition
- Over 500 families have been displaced from the region since Monday
- This marks the first diplomatic meeting between the two countries in 12 years

Return ONLY the extracted quote IN ENGLISH, nothing else.""",
                user_prompt=f"Extract a key quote IN ENGLISH from this article:\n\n{content[:2000]}",
                max_tokens=100,
                temperature=0.3,
            )

            quote = response.strip().strip('"').strip("'")

            # Validate quote is reasonable length
            if len(quote) < 20 or len(quote) > 250:
                logger.tree("Key Quote Validation Failed", [
                    ("Reason", "Invalid length"),
                    ("Length", f"{len(quote)} chars"),
                    ("Quote Preview", quote[:50] if quote else "empty"),
                ], emoji="❌")
                return None

            # Validate quote is in English
            if not is_english_only(quote):
                logger.tree("Key Quote Validation Failed", [
                    ("Reason", "Not in English"),
                    ("Quote Preview", quote[:50]),
                ], emoji="❌")
                return None

            self.ai_cache.set(cache_key, quote)
            logger.tree("Key Quote Extracted Successfully", [
                ("Quote", quote[:60]),
                ("Length", f"{len(quote)} chars"),
                ("Cached", "Yes"),
            ], emoji="✅")
            return quote

        except Exception as e:
            logger.tree("Key Quote Extraction Failed", [
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:80]),
                ("Content Length", f"{len(content)} chars"),
            ], emoji="❌")
            return None

    def _truncate_at_sentence(self, text: str, max_length: int) -> str:
        """
        Truncate text at a sentence boundary, not mid-word.

        Args:
            text: Text to truncate
            max_length: Maximum allowed length

        Returns:
            Text truncated at the last complete sentence within max_length
        """
        original_length = len(text)
        if original_length <= max_length:
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
            result = truncated[:last_period + 1]
            logger.debug("✂️ Truncated At Sentence Boundary", [
                ("Original Length", str(original_length)),
                ("New Length", str(len(result))),
                ("Max Allowed", str(max_length)),
                ("Method", "sentence boundary"),
            ])
            return result

        # Fallback: truncate at last space to avoid mid-word cut
        last_space = truncated.rfind(' ')
        if last_space > max_length // 2:
            result = truncated[:last_space] + "..."
            logger.debug("✂️ Truncated At Word Boundary", [
                ("Original Length", str(original_length)),
                ("New Length", str(len(result))),
                ("Max Allowed", str(max_length)),
                ("Method", "word boundary"),
            ])
            return result

        # Last resort: just truncate with ellipsis
        result = truncated[:max_length - 3] + "..."
        logger.warning("✂️ Truncated Mid-Text (No Good Boundary)", [
            ("Original Length", str(original_length)),
            ("New Length", str(len(result))),
            ("Max Allowed", str(max_length)),
            ("Method", "hard cut"),
        ])
        return result

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

                # Validate summaries - reject garbage/repeated content
                def is_garbage_summary(text: str) -> tuple[bool, str]:
                    """Detect garbage summaries like repeated dates or patterns.

                    Returns:
                        Tuple of (is_garbage, reason)
                    """
                    import re

                    lines = [l.strip() for l in text.split('\n') if l.strip()]

                    # If more than 3 lines and most are identical, it's garbage
                    if len(lines) > 3:
                        unique_lines = set(lines)
                        if len(unique_lines) <= 2:  # Almost all lines are the same
                            return (True, f"identical_lines ({len(unique_lines)} unique of {len(lines)})")

                    # Check for repeated short patterns (like "2025-12-08" repeated)
                    if len(lines) > 5:
                        first_line = lines[0]
                        repeat_count = lines.count(first_line)
                        if len(first_line) < 20 and repeat_count > len(lines) // 2:
                            return (True, f"repeated_pattern ('{first_line[:20]}' x{repeat_count})")

                    # Check if content is mostly just dates or numbers
                    date_pattern = r'\d{4}-\d{2}-\d{2}'
                    date_matches = re.findall(date_pattern, text)
                    if len(date_matches) > 5 and len(text) < 200:
                        return (True, f"date_spam ({len(date_matches)} dates in {len(text)} chars)")

                    return (False, "")

                arabic_garbage, arabic_reason = is_garbage_summary(arabic)
                english_garbage, english_reason = is_garbage_summary(english)

                if arabic_garbage or english_garbage:
                    logger.warning("🤖 AI Summary Is Garbage - Rejected", [
                        ("Arabic Garbage", str(arabic_garbage)),
                        ("Arabic Reason", arabic_reason if arabic_garbage else "OK"),
                        ("English Garbage", str(english_garbage)),
                        ("English Reason", english_reason if english_garbage else "OK"),
                        ("Arabic Preview", arabic[:100].replace('\n', ' ')),
                        ("English Preview", english[:100].replace('\n', ' ')),
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
        Make an OpenAI API call with exponential backoff retry and adaptive rate limiting.

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

        # Wait if rate limited
        await _rate_limiter.wait_if_needed()

        for attempt in range(OpenAIRetryConfig.MAX_RETRIES):
            try:
                # Track latency
                start_time = time.time()

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

                # Record latency
                latency_ms = (time.time() - start_time) * 1000
                _rate_limiter.record_latency(latency_ms)
                self.record_metric("ai_latency_ms", latency_ms)

                return response.choices[0].message.content.strip()

            except AuthenticationError as e:
                # Invalid API key - don't retry
                logger.error("OpenAI Authentication Failed", [
                    ("Error", "Invalid API key"),
                    ("Action", "Check OPENAI_API_KEY environment variable"),
                ])
                raise

            except RateLimitError as e:
                # Parse Retry-After header if available
                retry_after = getattr(e, 'retry_after', None)
                if retry_after:
                    _rate_limiter.set_retry_after(float(retry_after))
                    delay = float(retry_after)
                else:
                    base_delay = OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt)
                    delay = _rate_limiter.get_delay_with_jitter(min(base_delay, OpenAIRetryConfig.MAX_DELAY))

                logger.warning("OpenAI Rate Limited", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Retry In", f"{delay:.1f}s"),
                    ("Throttle Level", f"{_rate_limiter.throttle_level:.1f}x"),
                ])
                self.record_metric("ai_rate_limit", 1)
                last_exception = e
                await asyncio.sleep(delay)

            except APIConnectionError as e:
                # Network error - retry with backoff + jitter
                base_delay = OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt)
                delay = _rate_limiter.get_delay_with_jitter(min(base_delay, OpenAIRetryConfig.MAX_DELAY))

                logger.warning("OpenAI Connection Error", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Error", str(e)[:100]),
                    ("Retry In", f"{delay:.1f}s"),
                ])
                self.record_metric("ai_connection_error", 1)
                last_exception = e
                await asyncio.sleep(delay)

            except APIError as e:
                # Other API error - retry with backoff + jitter
                base_delay = OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt)
                delay = _rate_limiter.get_delay_with_jitter(min(base_delay, OpenAIRetryConfig.MAX_DELAY))

                logger.warning("OpenAI API Error", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Error", str(e)[:100]),
                    ("Retry In", f"{delay:.1f}s"),
                ])
                self.record_metric("ai_api_error", 1)
                last_exception = e
                await asyncio.sleep(delay)

            except TimeoutError as e:
                # Timeout - retry with backoff + jitter
                base_delay = OpenAIRetryConfig.BASE_DELAY * (OpenAIRetryConfig.EXPONENTIAL_BASE ** attempt)
                delay = _rate_limiter.get_delay_with_jitter(min(base_delay, OpenAIRetryConfig.MAX_DELAY))

                logger.warning("OpenAI Timeout", [
                    ("Attempt", f"{attempt + 1}/{OpenAIRetryConfig.MAX_RETRIES}"),
                    ("Retry In", f"{delay:.1f}s"),
                ])
                self.record_metric("ai_timeout", 1)
                last_exception = e
                await asyncio.sleep(delay)

        # All retries exhausted
        logger.error("OpenAI API Failed After Retries", [
            ("Retries", str(OpenAIRetryConfig.MAX_RETRIES)),
            ("Last Error", str(last_exception)[:100] if last_exception else "Unknown"),
        ])
        self.record_metric("ai_total_failure", 1)
        return ""


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["Article", "BaseScraper"]
