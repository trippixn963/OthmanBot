"""
Othman Discord Bot - Discord Rate Limit Utilities
==================================================

Rate limit handling for Discord API operations.

Features:
- Automatic retry on rate limit (429) errors
- Respects Discord's retry_after header
- Exponential backoff for other errors
- Helper functions for common operations with delays

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import random
from functools import wraps
from typing import Callable, Any, Optional, List, Union

import discord

from src.core.logger import logger
from src.core.config import LOG_TITLE_PREVIEW_LENGTH


# =============================================================================
# Rate Limit Configuration
# =============================================================================

class RateLimitConfig:
    """Configuration for Discord rate limit handling."""
    MAX_RETRIES: int = 3
    BASE_DELAY: float = 1.0  # seconds
    MAX_DELAY: float = 30.0  # seconds
    REACTION_DELAY: float = 0.3  # delay between reactions (300ms)
    MESSAGE_DELAY: float = 0.5  # delay between messages (500ms)


# =============================================================================
# Rate Limit Decorator
# =============================================================================

def with_rate_limit_retry(
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    base_delay: float = RateLimitConfig.BASE_DELAY,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that handles Discord rate limits with automatic retry.

    Args:
        max_retries: Maximum retry attempts
        base_delay: Base delay for exponential backoff

    Returns:
        Decorated function with rate limit handling

    DESIGN: Specifically handles discord.HTTPException with status 429
    Uses retry_after from Discord's response when available
    Falls back to exponential backoff for other errors
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap async function with rate limit retry logic."""
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute wrapped function with automatic retry on rate limits."""
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)

                except discord.HTTPException as e:
                    last_exception = e

                    # Rate limited - use Discord's retry_after
                    if e.status == 429:
                        retry_after = getattr(e, 'retry_after', None)
                        if retry_after:
                            delay = retry_after + 0.5  # Add buffer
                        else:
                            delay = min(base_delay * (2 ** attempt), RateLimitConfig.MAX_DELAY)

                        logger.warning("Discord Rate Limited", [
                            ("Function", func.__name__),
                            ("Attempt", f"{attempt + 1}/{max_retries}"),
                            ("Retry After", f"{delay:.1f}s"),
                        ])

                        if attempt < max_retries - 1:
                            await asyncio.sleep(delay)
                            continue

                    # Other HTTP errors - exponential backoff with jitter
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), RateLimitConfig.MAX_DELAY)
                        # Add jitter (0-10% of delay) to prevent thundering herd
                        delay += random.uniform(0, delay * 0.1)
                        logger.warning("Discord API Error", [
                            ("Function", func.__name__),
                            ("Attempt", f"{attempt + 1}/{max_retries}"),
                            ("Status", str(e.status)),
                            ("Retry In", f"{delay:.1f}s"),
                        ])
                        await asyncio.sleep(delay)
                        continue

                    # Out of retries
                    raise

                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), RateLimitConfig.MAX_DELAY)
                        # Add jitter to prevent thundering herd
                        delay += random.uniform(0, delay * 0.1)
                        await asyncio.sleep(delay)
                        continue
                    raise

            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        return wrapper

    return decorator


# =============================================================================
# Helper Functions for Common Operations
# =============================================================================

async def add_reactions_with_delay(
    message: discord.Message,
    emojis: List[Union[str, discord.Emoji]],
    delay: float = RateLimitConfig.REACTION_DELAY,
) -> List[bool]:
    """
    Add multiple reactions to a message with delays between each.

    Args:
        message: The message to add reactions to
        emojis: List of emojis to add
        delay: Delay between reactions in seconds

    Returns:
        List of success status for each reaction

    DESIGN: Prevents rate limiting when adding multiple reactions
    Discord rate limits reactions heavily (1/0.25s per channel)
    """
    results = []

    for i, emoji in enumerate(emojis):
        try:
            await message.add_reaction(emoji)
            results.append(True)
        except discord.HTTPException as e:
            if e.status == 429:
                # Rate limited - wait and retry
                retry_after = getattr(e, 'retry_after', delay * 2)
                await asyncio.sleep(retry_after)
                try:
                    await message.add_reaction(emoji)
                    results.append(True)
                except discord.HTTPException:
                    results.append(False)
            else:
                logger.warning("Failed to Add Reaction", [
                    ("Emoji", str(emoji)),
                    ("Error", str(e)),
                ])
                results.append(False)

        # Add delay before next reaction (except for last one)
        if i < len(emojis) - 1:
            await asyncio.sleep(delay)

    return results


async def send_message_with_retry(
    channel: Union[discord.TextChannel, discord.Thread],
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    **kwargs: Any,
) -> Optional[discord.Message]:
    """
    Send a message with automatic rate limit retry.

    Args:
        channel: Channel or thread to send to
        content: Message content
        embed: Optional embed
        view: Optional view
        max_retries: Maximum retry attempts
        **kwargs: Additional arguments to send()

    Returns:
        The sent message or None on failure

    DESIGN: Wraps channel.send() with rate limit handling
    Returns None instead of raising to allow graceful degradation
    """
    for attempt in range(max_retries):
        try:
            return await channel.send(
                content=content,
                embed=embed,
                view=view,
                **kwargs,
            )
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', RateLimitConfig.BASE_DELAY * (2 ** attempt))
                logger.warning("Rate Limited on Message Send", [
                    ("Channel", str(channel.id)),
                    ("Attempt", f"{attempt + 1}/{max_retries}"),
                    ("Retry After", f"{retry_after:.1f}s"),
                ])
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after + 0.5)
                    continue
            logger.error("Failed to Send Message", [
                ("Channel", str(channel.id)),
                ("Error", str(e)),
            ])
            return None
        except Exception as e:
            logger.error("Unexpected Error Sending Message", [
                ("Channel", str(channel.id)),
                ("Error", str(e)),
            ])
            return None

    return None


async def edit_message_with_retry(
    message: discord.Message,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    **kwargs: Any,
) -> bool:
    """
    Edit a message with automatic rate limit retry.

    Args:
        message: Message to edit
        content: New content (None to keep existing)
        embed: New embed (None to keep existing)
        max_retries: Maximum retry attempts
        **kwargs: Additional arguments to edit()

    Returns:
        True on success, False on failure
    """
    for attempt in range(max_retries):
        try:
            await message.edit(content=content, embed=embed, **kwargs)
            return True
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', RateLimitConfig.BASE_DELAY * (2 ** attempt))
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after + 0.5)
                    continue
            logger.error("Failed to Edit Message", [
                ("Message ID", str(message.id)),
                ("Error", str(e)),
            ])
            return False
        except Exception as e:
            logger.error("Unexpected Error Editing Message", [
                ("Message ID", str(message.id)),
                ("Error", str(e)),
            ])
            return False

    return False


async def edit_thread_with_retry(
    thread: discord.Thread,
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    **kwargs: Any,
) -> bool:
    """
    Edit a thread with automatic rate limit retry.

    Args:
        thread: Thread to edit
        max_retries: Maximum retry attempts
        **kwargs: Arguments to pass to thread.edit()

    Returns:
        True on success, False on failure

    DESIGN: Thread edits are heavily rate limited (10/min globally)
    This wrapper provides retry logic specifically for thread operations
    """
    for attempt in range(max_retries):
        try:
            await thread.edit(**kwargs)
            return True
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', RateLimitConfig.BASE_DELAY * (2 ** attempt))
                logger.warning("Rate Limited on Thread Edit", [
                    ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH] if thread.name else str(thread.id)),
                    ("Attempt", f"{attempt + 1}/{max_retries}"),
                    ("Retry After", f"{retry_after:.1f}s"),
                ])
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after + 0.5)
                    continue
            logger.error("Failed to Edit Thread", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH] if thread.name else str(thread.id)),
                ("Error", str(e)),
            ])
            return False
        except Exception as e:
            logger.error("Unexpected Error Editing Thread", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH] if thread.name else str(thread.id)),
                ("Error", str(e)),
            ])
            return False

    return False


async def delete_message_safe(
    message: discord.Message,
    delay: float = 0.0,
) -> bool:
    """
    Safely delete a message with optional delay.

    Args:
        message: Message to delete
        delay: Optional delay before deletion

    Returns:
        True if deleted, False otherwise

    DESIGN: Silent failure on NotFound (already deleted)
    Logs other errors but doesn't raise
    """
    if delay > 0:
        await asyncio.sleep(delay)

    try:
        await message.delete()
        return True
    except discord.NotFound:
        # Already deleted - not an error
        return True
    except discord.HTTPException as e:
        if e.status != 429:  # Don't log rate limits as errors
            logger.warning("Failed to Delete Message", [
                ("Message ID", str(message.id)),
                ("Error", str(e)),
            ])
        return False


async def remove_reaction_safe(
    reaction: discord.Reaction,
    user: Union[discord.User, discord.Member],
) -> bool:
    """
    Safely remove a reaction without raising on failure.

    Args:
        reaction: The reaction to remove
        user: The user whose reaction to remove

    Returns:
        True if removed, False otherwise
    """
    try:
        await reaction.remove(user)
        return True
    except discord.HTTPException as e:
        if e.status != 429:  # Don't log rate limits
            logger.warning("Failed to Remove Reaction", [
                ("User", str(user.id)),
                ("Emoji", str(reaction.emoji)),
                ("Error", str(e)),
            ])
        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "RateLimitConfig",
    "with_rate_limit_retry",
    "add_reactions_with_delay",
    "send_message_with_retry",
    "edit_message_with_retry",
    "edit_thread_with_retry",
    "delete_message_safe",
    "remove_reaction_safe",
]
