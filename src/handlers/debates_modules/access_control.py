"""
OthmanBot - Debates Access Control
==================================

Access control utilities for debate threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import MODERATOR_ROLE_ID, DEVELOPER_ID
from src.core.emojis import PARTICIPATE_EMOJI
from src.utils import send_message_with_retry
from src.utils.discord_rate_limit import log_http_error

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

DEBATE_MANAGEMENT_ROLE_ID = MODERATOR_ROLE_ID


# =============================================================================
# Role Checks
# =============================================================================

def has_debate_management_role(member: discord.Member) -> bool:
    """Check if member has the Debate Management role."""
    if not hasattr(member, 'roles'):
        return False
    return any(role.id == DEBATE_MANAGEMENT_ROLE_ID for role in member.roles)


def should_skip_access_control(member: discord.Member) -> bool:
    """
    Check if member should bypass access control.

    Returns True for:
    - Debate Management role holders
    - Moderators
    - Developer
    """
    is_debate_manager = has_debate_management_role(member)
    is_moderator = hasattr(member, 'roles') and any(
        role.id == MODERATOR_ROLE_ID for role in member.roles
    )
    is_developer = member.id == DEVELOPER_ID

    return is_debate_manager or is_moderator or is_developer


# =============================================================================
# Access Control Enforcement
# =============================================================================

async def check_user_participation(
    bot: "OthmanBot",
    message: discord.Message
) -> bool:
    """
    Check if user has reacted to the analytics embed to participate.

    Args:
        bot: The OthmanBot instance
        message: The message to check (from the user attempting to post)

    Returns:
        True if user can post, False if blocked
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return True  # Allow if service unavailable

    try:
        # Get analytics message ID from database
        analytics_message_id = await bot.debates_service.db.get_analytics_message_async(message.channel.id)

        if not analytics_message_id:
            return True  # No analytics message, allow posting

        # Fetch the analytics message
        try:
            analytics_message = await message.channel.fetch_message(analytics_message_id)

            # Check if the user has reacted with participation emoji
            user_has_reacted = False
            for reaction in analytics_message.reactions:
                if str(reaction.emoji) == PARTICIPATE_EMOJI:
                    # Check if the current user is in the list of users who reacted
                    async for user in reaction.users(limit=None):
                        if user.id == message.author.id:
                            user_has_reacted = True
                            break
                    break

            if not user_has_reacted:
                # Delete the user's message
                await message.delete()

                # Try to send a DM to the user
                try:
                    await send_message_with_retry(
                        message.author,
                        content=(
                            f"Hi {message.author.name},\n\n"
                            f"To participate in the debate **{message.channel.name}**, "
                            f"you need to react with {PARTICIPATE_EMOJI} to the analytics embed first.\n\n"
                            f"Please go back to the thread and react with {PARTICIPATE_EMOJI} "
                            f"to the analytics message to unlock posting access."
                        )
                    )
                    logger.info("🔐 User Blocked - No Participation React", [
                        ("User", f"{message.author.name} ({message.author.display_name})"),
                        ("ID", str(message.author.id)),
                        ("Thread", f"{message.channel.name} ({message.channel.id})"),
                        ("Action", "DM sent with instructions"),
                    ])
                except discord.Forbidden:
                    # User has DMs disabled, send a temporary message in the channel
                    await send_message_with_retry(
                        message.channel,
                        content=f"{message.author.mention} You need to react with {PARTICIPATE_EMOJI} "
                                f"to the analytics embed above to participate in this debate.",
                        delete_after=8
                    )
                    logger.info("🔐 User Blocked - No Participation React", [
                        ("User", f"{message.author.name} ({message.author.display_name})"),
                        ("ID", str(message.author.id)),
                        ("Thread", f"{message.channel.name} ({message.channel.id})"),
                        ("Action", "Channel message sent (DMs disabled)"),
                    ])

                return False

        except discord.NotFound:
            # Clear stale reference
            await bot.debates_service.db.clear_analytics_message_async(message.channel.id)
            logger.info("🔐 Cleared Stale Analytics Reference (Access Control)", [
                ("Message ID", str(analytics_message_id)),
                ("Thread ID", str(message.channel.id)),
            ])
        except discord.Forbidden:
            logger.warning("🔐 No Permission to Fetch Analytics Message", [
                ("Message ID", str(analytics_message_id)),
                ("Thread ID", str(message.channel.id)),
            ])
        except discord.HTTPException as e:
            log_http_error(e, "Fetch Analytics Message", [
                ("Message ID", str(analytics_message_id)),
                ("Thread", str(message.channel.id)),
            ])

    except discord.HTTPException as e:
        log_http_error(e, "Access Control Check", [
            ("User", f"{message.author.name} ({message.author.display_name})"),
            ("ID", str(message.author.id)),
            ("Thread", str(message.channel.id)),
        ])
    except (ValueError, AttributeError) as e:
        logger.error("🔐 Error Checking Access Control", [
            ("User", f"{message.author.name} ({message.author.display_name})"),
            ("ID", str(message.author.id)),
            ("Thread", str(message.channel.id)),
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
        ])

    return True


async def check_user_ban(bot: "OthmanBot", message: discord.Message) -> bool:
    """
    Check if user is banned from the debate thread.

    Args:
        bot: The OthmanBot instance
        message: The message to check

    Returns:
        True if user can post, False if banned (message deleted)
    """
    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return True

    is_banned = bot.debates_service.db.is_user_banned(message.author.id, message.channel.id)

    if is_banned:
        try:
            content_preview = message.content[:50] + "..." if len(message.content) > 50 else message.content
            await message.delete()
            logger.info("🚫 Banned User Message Deleted", [
                ("User", f"{message.author.name} ({message.author.display_name})"),
                ("ID", str(message.author.id)),
                ("Thread", f"{message.channel.name} ({message.channel.id})"),
                ("Content Preview", content_preview),
            ])
        except discord.HTTPException as e:
            log_http_error(e, "Delete Banned User Message", [
                ("User", f"{message.author.name} ({message.author.display_name})"),
                ("ID", str(message.author.id)),
                ("Thread", str(message.channel.id)),
            ])
        return False

    return True


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DEBATE_MANAGEMENT_ROLE_ID",
    "has_debate_management_role",
    "should_skip_access_control",
    "check_user_participation",
    "check_user_ban",
]
