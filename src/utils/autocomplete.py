"""
OthmanBot - Autocomplete Utilities
==================================

Reusable autocomplete functions for Discord slash commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import List

import discord
from discord import app_commands

from src.core.config import DISCORD_AUTOCOMPLETE_LIMIT
from src.utils.duration import DURATION_SUGGESTIONS


# =============================================================================
# Thread ID Autocomplete
# =============================================================================

async def thread_id_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """
    Autocomplete for thread_id field.

    Shows 'All Debates' option plus allows custom thread IDs.
    Used by /disallow, /allow, and similar commands.
    """
    choices = []
    current_lower = current.lower()

    # Always show "All" option if it matches
    if not current or "all" in current_lower:
        choices.append(app_commands.Choice(name="All Debates", value="all"))

    # If user typed something that looks like a thread ID, show it
    if current and current != "all" and current_lower != "all debates":
        choices.append(app_commands.Choice(name=f"Thread: {current}", value=current))

    return choices[:DISCORD_AUTOCOMPLETE_LIMIT]


# =============================================================================
# Duration Autocomplete
# =============================================================================

async def duration_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """
    Autocomplete for duration field.

    Shows duration suggestions but allows custom input.
    Used by /disallow and similar commands.
    """
    choices = []
    current_lower = current.lower()

    for name, value in DURATION_SUGGESTIONS:
        # Filter by what user typed
        if current_lower in name.lower() or current_lower in value.lower():
            choices.append(app_commands.Choice(name=name, value=value))

    # If user typed something custom, show it as an option too
    if current and not any(current_lower == v.lower() for _, v in DURATION_SUGGESTIONS):
        # Only show custom if it looks like a valid duration format
        if current_lower not in [n.lower() for n, _ in DURATION_SUGGESTIONS]:
            choices.insert(0, app_commands.Choice(name=f"Custom: {current}", value=current))

    return choices[:DISCORD_AUTOCOMPLETE_LIMIT]


# =============================================================================
# Banned User Autocomplete
# =============================================================================

async def banned_user_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """
    Autocomplete for banned users in /allow command.

    Shows currently banned users with expiry info.
    """
    from datetime import datetime
    from src.core.config import NY_TZ

    bot = interaction.client

    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return []

    # Get banned users with expiry info
    banned_info = bot.debates_service.db.get_banned_users_with_info()

    choices = []
    seen_users = set()  # Track users to avoid duplicates

    for ban in banned_info[:DISCORD_AUTOCOMPLETE_LIMIT * 2]:  # Get more to filter
        user_id = ban['user_id']
        if user_id in seen_users:
            continue
        seen_users.add(user_id)

        # Try to get the member from the guild
        member = interaction.guild.get_member(user_id) if interaction.guild else None

        # Format expiry info
        if ban['expires_at']:
            try:
                expiry = datetime.fromisoformat(ban['expires_at'].replace('Z', '+00:00'))
                now = datetime.now(NY_TZ)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=NY_TZ)
                time_left = expiry - now
                if time_left.days > 0:
                    expiry_str = f"{time_left.days}d left"
                elif time_left.seconds > 3600:
                    expiry_str = f"{time_left.seconds // 3600}h left"
                else:
                    expiry_str = f"{time_left.seconds // 60}m left"
            except (ValueError, TypeError):
                expiry_str = "Temp"
        else:
            expiry_str = "Permanent"

        # Format scope
        scope = "All" if ban['thread_id'] is None else "Thread"

        if member:
            name = member.display_name
            # Filter by current input
            if current.lower() in name.lower() or current in str(user_id):
                display = f"{name} ({scope}, {expiry_str})"
                choices.append(app_commands.Choice(
                    name=display[:100],  # Discord limit
                    value=str(user_id)
                ))
        else:
            # User left the server but still in ban list
            if current in str(user_id) or not current:
                display = f"User {user_id} ({scope}, {expiry_str})"
                choices.append(app_commands.Choice(
                    name=display[:100],
                    value=str(user_id)
                ))

    return choices[:DISCORD_AUTOCOMPLETE_LIMIT]


# =============================================================================
# Case Search Autocomplete
# =============================================================================

async def case_search_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """
    Autocomplete for case search.

    Shows users with moderation cases.
    """
    bot = interaction.client

    if not hasattr(bot, 'debates_service') or bot.debates_service is None:
        return []

    choices = []
    db = bot.debates_service.db

    # Get all case logs
    all_cases = db.get_all_case_logs()

    for case in all_cases[:DISCORD_AUTOCOMPLETE_LIMIT]:
        user_id = case['user_id']
        case_id = case['case_id']

        # Try to get the member from the guild
        member = interaction.guild.get_member(user_id) if interaction.guild else None

        if member:
            name = f"[{case_id:04d}] {member.display_name}"
        else:
            name = f"[{case_id:04d}] User {user_id}"

        # Filter by current input (case ID or user ID)
        if not current or current.lower() in name.lower() or current in str(user_id) or current in str(case_id):
            choices.append(app_commands.Choice(
                name=name[:100],  # Discord limit
                value=str(user_id)
            ))

    return choices[:DISCORD_AUTOCOMPLETE_LIMIT]


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "thread_id_autocomplete",
    "duration_autocomplete",
    "banned_user_autocomplete",
    "case_search_autocomplete",
]
