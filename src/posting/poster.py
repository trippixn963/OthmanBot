"""
Othman Discord Bot - Base Poster Module
========================================

Shared media download and forum formatting utilities.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
from pathlib import Path
from typing import Optional, Tuple

import aiohttp
import discord

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

TEMP_DIR: Path = Path("data/temp_media")
"""Temporary directory for downloaded media files."""


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
        prefix: Filename prefix (e.g., "article", "soccer", "gaming")
        url_hash: Hash for unique filename
        allowed_extensions: List of allowed file extensions
        timeout: Request timeout in seconds

    Returns:
        Tuple of (discord.File or None, temp_path or None)

    DESIGN: Downloads media to temp directory then creates Discord file
    Uses hash-based filename to prevent collisions
    Returns both file object and path for cleanup
    """
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
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
                return discord_file, temp_path

    except Exception as e:
        logger.warning(f"Failed to download media from {url[:50]}: {e}")
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
        logger.info(f"Video is an embed (not downloadable): {url[:50]}")
        return None, None

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status != 200:
                    return None, None

                # Check content length
                content_length = response.headers.get("Content-Length")
                max_bytes = max_size_mb * 1024 * 1024
                if content_length and int(content_length) > max_bytes:
                    logger.warning(f"Video too large ({int(content_length)/1024/1024:.1f}MB)")
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
                    logger.warning(f"Video size ({len(content)/1024/1024:.1f}MB) exceeds limit")
                    return None, None

                # Save file
                temp_path = str(TEMP_DIR / f"temp_vid_{url_hash}{ext}")
                with open(temp_path, "wb") as f:
                    f.write(content)

                discord_file = discord.File(temp_path, filename=f"video{ext}")
                logger.info(f"Downloaded video ({len(content)/1024/1024:.1f}MB)")
                return discord_file, temp_path

    except Exception as e:
        logger.warning(f"Failed to download video: {e}")
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
            logger.warning(f"Failed to delete temp file {path}: {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "download_media",
    "download_image",
    "download_video",
    "cleanup_temp_file",
    "TEMP_DIR",
]
