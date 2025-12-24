"""
Othman Discord Bot - Base Poster Module
========================================

Shared media download and forum formatting utilities.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import aiohttp
import discord

from src.core.logger import logger
from src.utils.retry import get_circuit_breaker, RETRYABLE_EXCEPTIONS


# =============================================================================
# Constants
# =============================================================================

TEMP_DIR: Path = Path("data/temp_media")
"""Temporary directory for downloaded media files."""

TEMP_FILE_MAX_AGE_HOURS: int = 24
"""Maximum age for temp files before cleanup (hours)."""

DOWNLOAD_TIMEOUT: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=20, connect=10)
"""Timeout settings for media download sessions."""

MEDIA_DOWNLOAD_RETRIES: int = 3
"""Number of retry attempts for media downloads."""

# Circuit breaker for media downloads (5 failures = 60s cooldown)
_media_circuit = get_circuit_breaker("media_download", failure_threshold=5, recovery_timeout=60.0)


# =============================================================================
# Media Download
# =============================================================================

async def download_media(
    url: str,
    prefix: str,
    url_hash: int,
    allowed_extensions: list[str],
    timeout: int = 10
) -> Tuple[Optional[discord.File], Optional[str]]:
    """
    Download media from URL and create Discord file.

    Args:
        url: URL to download from
        prefix: Filename prefix (e.g., "article", "soccer")
        url_hash: Hash for unique filename
        allowed_extensions: List of allowed file extensions
        timeout: Request timeout in seconds

    Returns:
        Tuple of (discord.File or None, temp_path or None)

    DESIGN: Downloads media to temp directory then creates Discord file
    Uses hash-based filename to prevent collisions
    Returns both file object and path for cleanup
    Uses circuit breaker to prevent hammering failing services
    """
    # Check circuit breaker
    if _media_circuit.is_open:
        logger.debug("Media Download Skipped (Circuit Open)", [
            ("URL", url[:50]),
        ])
        return None, None

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    last_error: Optional[Exception] = None

    for attempt in range(MEDIA_DOWNLOAD_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.debug("Media Download Non-200", [
                            ("URL", url[:50]),
                            ("Status", str(response.status)),
                        ])
                        return None, None

                    # Get file extension
                    ext: str = ".jpg"
                    if "." in url:
                        url_ext = url.split(".")[-1].split("?")[0].lower()
                        if url_ext in allowed_extensions:
                            ext = f".{url_ext}"

                    # Save to temp file
                    temp_path = str(TEMP_DIR / f"temp_{prefix}_{url_hash}{ext}")
                    content: bytes = await response.read()

                    with open(temp_path, "wb") as f:
                        f.write(content)

                    # Create Discord file object
                    discord_file = discord.File(temp_path, filename=f"{prefix}{ext}")
                    _media_circuit.record_success()
                    return discord_file, temp_path

        except RETRYABLE_EXCEPTIONS as e:
            last_error = e
            if attempt < MEDIA_DOWNLOAD_RETRIES - 1:
                delay = 2 ** attempt  # 1s, 2s, 4s
                logger.debug("Media Download Retry", [
                    ("URL", url[:50]),
                    ("Attempt", f"{attempt + 1}/{MEDIA_DOWNLOAD_RETRIES}"),
                    ("Delay", f"{delay}s"),
                ])
                await asyncio.sleep(delay)
            continue
        except Exception as e:
            last_error = e
            break

    # All retries failed
    _media_circuit.record_failure()
    logger.warning("📥 Failed To Download Media", [
        ("URL", url[:50]),
        ("Error", str(last_error) if last_error else "Unknown"),
        ("Attempts", str(MEDIA_DOWNLOAD_RETRIES)),
    ])
    return None, None


async def download_image(
    url: str,
    prefix: str,
    url_hash: int
) -> Tuple[Optional[discord.File], Optional[str]]:
    """
    Download image from URL.

    Args:
        url: Image URL
        prefix: Filename prefix
        url_hash: Hash for unique filename

    Returns:
        Tuple of (discord.File or None, temp_path or None)
    """
    return await download_media(
        url,
        prefix,
        url_hash,
        ["jpg", "jpeg", "png", "webp", "gif"]
    )


async def download_video(
    url: str,
    prefix: str,
    url_hash: int,
    max_size_mb: int = 25
) -> Tuple[Optional[discord.File], Optional[str]]:
    """
    Download video from URL with size check.

    Args:
        url: Video URL
        prefix: Filename prefix
        url_hash: Hash for unique filename
        max_size_mb: Maximum file size in MB

    Returns:
        Tuple of (discord.File or None, temp_path or None)

    DESIGN: Only downloads direct video files (not embeds)
    Checks Content-Length header and actual file size
    Respects Discord's 25MB file size limit
    """
    # Only download direct video files
    is_direct = any(ext in url.lower() for ext in [".mp4", ".webm", ".mov"])
    if not is_direct:
        logger.info("🎬 Video Is An Embed (Not Downloadable)", [
            ("URL", url[:50]),
        ])
        return None, None

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, connect=10)) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None, None

                # Check content length
                content_length = response.headers.get("Content-Length")
                max_bytes = max_size_mb * 1024 * 1024
                if content_length and int(content_length) > max_bytes:
                    logger.warning("🎬 Video Too Large", [
                        ("Size", f"{int(content_length)/1024/1024:.1f}MB"),
                        ("Limit", f"{max_size_mb}MB"),
                    ])
                    return None, None

                # Get extension
                ext: str = ".mp4"
                if "." in url:
                    url_ext = url.split(".")[-1].split("?")[0].lower()
                    if url_ext in ["mp4", "webm", "mov"]:
                        ext = f".{url_ext}"

                # Download and check actual size
                content: bytes = await response.read()
                if len(content) > max_bytes:
                    logger.warning("🎬 Video Size Exceeds Limit", [
                        ("Size", f"{len(content)/1024/1024:.1f}MB"),
                        ("Limit", f"{max_size_mb}MB"),
                    ])
                    return None, None

                # Save file
                temp_path = str(TEMP_DIR / f"temp_vid_{url_hash}{ext}")
                with open(temp_path, "wb") as f:
                    f.write(content)

                discord_file = discord.File(temp_path, filename=f"video{ext}")
                logger.info("🎬 Downloaded Video", [
                    ("Size", f"{len(content)/1024/1024:.1f}MB"),
                ])
                return discord_file, temp_path

    except Exception as e:
        logger.warning("🎬 Failed To Download Video", [
            ("Error", str(e)),
        ])
        return None, None


# =============================================================================
# Cleanup
# =============================================================================

def cleanup_temp_file(path: Optional[str]) -> None:
    """
    Delete temporary file if it exists.

    Args:
        path: Path to temporary file

    DESIGN: Safely removes temp files after Discord upload
    Prevents disk space issues from accumulated downloads
    Handles errors gracefully to avoid interrupting posting flow
    """
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            logger.warning("🗑️ Failed To Delete Temp File", [
                ("Path", path),
                ("Error", str(e)),
            ])


def cleanup_old_temp_files() -> int:
    """
    Remove temporary files older than TEMP_FILE_MAX_AGE_HOURS.

    Should be called periodically (e.g., on bot startup or hourly)
    to prevent disk space bloat from orphaned temp files.

    Returns:
        Number of files removed
    """
    if not TEMP_DIR.exists():
        return 0

    removed_count = 0
    max_age_seconds = TEMP_FILE_MAX_AGE_HOURS * 3600
    current_time = time.time()

    try:
        for file_path in TEMP_DIR.iterdir():
            if file_path.is_file():
                try:
                    file_age = current_time - file_path.stat().st_mtime
                    if file_age > max_age_seconds:
                        file_path.unlink()
                        removed_count += 1
                except (OSError, PermissionError) as e:
                    logger.warning("🗑️ Failed To Remove Old Temp File", [
                        ("Path", str(file_path)),
                        ("Error", str(e)),
                    ])

        if removed_count > 0:
            logger.info("🗑️ Cleaned Old Temp Files", [
                ("Removed", str(removed_count)),
                ("Max Age", f"{TEMP_FILE_MAX_AGE_HOURS}h"),
            ])

    except Exception as e:
        logger.warning("🗑️ Failed To Clean Temp Directory", [
            ("Error", str(e)),
        ])

    return removed_count


# =============================================================================
# Content Building Utilities
# =============================================================================

def truncate_at_sentence(text: str, max_length: int) -> str:
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

    truncated = text[:max_length]

    # Find last sentence boundary (. ! ? and Arabic ؟)
    last_period = -1
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i] in '.!?؟':
            last_period = i
            break

    if last_period > max_length // 2:
        return truncated[:last_period + 1]

    # Fallback: truncate at last space
    last_space = truncated.rfind(' ')
    if last_space > max_length // 2:
        return truncated[:last_space] + "..."

    return truncated[:max_length - 3] + "..."


def build_forum_content(
    source: str,
    source_emoji: str,
    url: str,
    published_date,
    arabic_summary: str,
    english_summary: str,
) -> str:
    """
    Build forum post content with bilingual summaries.

    Args:
        source: News source name
        source_emoji: Emoji for source
        url: Article URL
        published_date: Article published date
        arabic_summary: Arabic summary text
        english_summary: English summary text

    Returns:
        Formatted message content for forum post

    DESIGN: Build footer first to calculate remaining space for summaries
    Ensures URL is never truncated (breaks "Read Full Article" link)
    Key quote at top for engagement, then Arabic/English summaries
    """
    published_date_str = published_date.strftime("%B %d, %Y") if published_date else "N/A"

    footer = ""
    footer += f"📰 **Source:** {source_emoji} {source} • 🔗 **[Read Full Article](<{url}>)**\n"
    footer += f"📅 **Published:** {published_date_str}\n\n"
    footer += "-# ⚠️ This news article was automatically generated and posted by an automated bot. "
    footer += "The content is sourced from various news outlets and summarized using AI.\n\n"
    footer += "-# Bot developed by حَـــــنَّـــــا."

    # Calculate space for summaries (Discord limit 2000, minus footer and formatting overhead)
    max_summary_space = 2000 - len(footer) - 400

    # Add null checks
    arabic = arabic_summary or "الملخص غير متوفر"
    english = english_summary or "Summary not available"

    combined_length = len(arabic) + len(english)
    if combined_length > max_summary_space:
        max_each = max_summary_space // 2
        if len(arabic) > max_each:
            arabic = truncate_at_sentence(arabic, max_each)
        if len(english) > max_each:
            english = truncate_at_sentence(english, max_each)

    message_content = ""

    # Key quote - extract first proper sentence
    # Use '. ' followed by uppercase to detect real sentence boundaries
    # This avoids splitting on abbreviations like "U.S." or "Dr."
    import re
    # Match sentence ending with period followed by space + uppercase (new sentence)
    # or period at end of text
    sentence_match = re.search(r'^(.{30,}?\.)\s+[A-Z]', english)
    if sentence_match:
        first_sentence = sentence_match.group(1).strip()
    else:
        # Fallback: take first 200 chars and truncate at last period
        snippet = english[:200]
        last_period = snippet.rfind('.')
        if last_period > 30:
            first_sentence = snippet[:last_period + 1].strip()
        else:
            first_sentence = truncate_at_sentence(english, 150)

    if len(first_sentence) > 250:
        first_sentence = truncate_at_sentence(first_sentence, 247)

    if len(first_sentence) > 20:
        message_content += f"> 💬 *\"{first_sentence}\"*\n\n"
        message_content += "─────────────\n\n"

    # Summaries
    message_content += f"🇸🇾 **Arabic Summary**\n{arabic}\n\n"
    message_content += "─────────────\n\n"
    message_content += f"🇬🇧 **English Translation**\n{english}\n\n"
    message_content += "─────────────\n\n"

    message_content += footer

    return message_content


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "download_media",
    "download_image",
    "download_video",
    "cleanup_temp_file",
    "cleanup_old_temp_files",
    "truncate_at_sentence",
    "build_forum_content",
    "TEMP_DIR",
]
