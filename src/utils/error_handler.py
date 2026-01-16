"""
OthmanBot - Discord Error Handler Utility
=========================================

Reusable error handling patterns for Discord API operations.
Reduces code duplication across commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import functools
from typing import Callable, Optional, TypeVar, Any

import discord

from src.core.logger import logger
from src.utils.discord_rate_limit import log_http_error


# =============================================================================
# Type Definitions
# =============================================================================

T = TypeVar('T')


# =============================================================================
# Error Response Helper
# =============================================================================

async def send_error_response(
    interaction: discord.Interaction,
    message: str = "An error occurred.",
    ephemeral: bool = True
) -> None:
    """
    Send an error response to the user.

    Handles both deferred and non-deferred interactions.

    Args:
        interaction: The Discord interaction
        message: Error message to display
        ephemeral: Whether to make the message ephemeral
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)
    except discord.HTTPException:
        # If we can't respond, just log it
        logger.warning("Failed to send error response", [
            ("Message", message[:50]),
        ])


# =============================================================================
# Error Handling Decorator
# =============================================================================

def handle_command_errors(
    operation_name: str,
    user_message: str = "An error occurred while processing your request.",
    log_user: bool = True
) -> Callable:
    """
    Decorator for handling common Discord command errors.

    Usage:
        @handle_command_errors("Ban User", "Failed to ban user.")
        async def ban_command(self, interaction, user):
            ...

    Args:
        operation_name: Name for logging (e.g., "Ban User")
        user_message: Message to show user on error
        log_user: Whether to include user info in logs
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Optional[T]:
            # Find the interaction in args (usually second arg after self)
            interaction = None
            for arg in args:
                if isinstance(arg, discord.Interaction):
                    interaction = arg
                    break

            try:
                return await func(*args, **kwargs)

            except discord.Forbidden as e:
                log_details = [("Error", "Missing permissions")]
                if log_user and interaction:
                    log_details.insert(0, ("ID", str(interaction.user.id)))
                    log_details.insert(0, ("User", f"{interaction.user.name} ({interaction.user.display_name})"))

                logger.warning(f"{operation_name} Failed (Forbidden)", log_details)

                if interaction:
                    await send_error_response(
                        interaction,
                        "I don't have permission to perform this action."
                    )

            except discord.NotFound as e:
                log_details = [("Error", "Resource not found")]
                if log_user and interaction:
                    log_details.insert(0, ("ID", str(interaction.user.id)))
                    log_details.insert(0, ("User", f"{interaction.user.name} ({interaction.user.display_name})"))

                logger.warning(f"{operation_name} Failed (NotFound)", log_details)

                if interaction:
                    await send_error_response(
                        interaction,
                        "The requested resource was not found."
                    )

            except discord.HTTPException as e:
                log_details = []
                if log_user and interaction:
                    log_details.append(("User", f"{interaction.user.name} ({interaction.user.display_name})"))
                    log_details.append(("ID", str(interaction.user.id)))

                log_http_error(e, operation_name, log_details)

                if interaction:
                    await send_error_response(interaction, user_message)

            except Exception as e:
                log_details = [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)[:100]),
                ]
                if log_user and interaction:
                    log_details.insert(0, ("ID", str(interaction.user.id)))
                    log_details.insert(0, ("User", f"{interaction.user.name} ({interaction.user.display_name})"))

                logger.exception(f"{operation_name} Failed (Unexpected)", log_details)

                if interaction:
                    await send_error_response(
                        interaction,
                        "An unexpected error occurred. Please try again."
                    )

            return None

        return wrapper
    return decorator


# =============================================================================
# Async Operation Wrapper
# =============================================================================

async def safe_api_call(
    coro,
    operation_name: str,
    default: Any = None,
    log_details: list = None
) -> Any:
    """
    Safely execute a Discord API call with error handling.

    Args:
        coro: Coroutine to execute
        operation_name: Name for logging
        default: Default value to return on error
        log_details: Additional details for logging

    Returns:
        Result of coroutine or default on error
    """
    try:
        return await coro
    except discord.Forbidden:
        logger.warning(f"{operation_name} Failed (Forbidden)", log_details or [])
        return default
    except discord.NotFound:
        logger.debug(f"{operation_name} Failed (NotFound)", log_details or [])
        return default
    except discord.HTTPException as e:
        log_http_error(e, operation_name, log_details or [])
        return default
    except Exception as e:
        logger.exception(f"{operation_name} Failed (Unexpected)", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:100]),
            *(log_details or []),
        ])
        return default


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "send_error_response",
    "handle_command_errors",
    "safe_api_call",
]
