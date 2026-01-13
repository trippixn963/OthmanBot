"""
OthmanBot - Embed Factory Utility
=================================

Reusable embed creation patterns for consistent styling.
Reduces boilerplate code across commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional, List, Tuple

import discord

from src.core.colors import EmbedColors
from src.core.config import NY_TZ
from src.utils.footer import set_footer


# =============================================================================
# Base Embed Creators
# =============================================================================

def create_embed(
    title: str,
    description: Optional[str] = None,
    color: discord.Color = EmbedColors.INFO,
    thumbnail_url: Optional[str] = None,
    image_url: Optional[str] = None,
    author_name: Optional[str] = None,
    author_icon_url: Optional[str] = None,
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    add_footer: bool = True
) -> discord.Embed:
    """
    Create a standardized embed with consistent styling.

    Args:
        title: Embed title
        description: Embed description
        color: Embed color (defaults to INFO green)
        thumbnail_url: URL for thumbnail image
        image_url: URL for main image
        author_name: Author name
        author_icon_url: Author icon URL
        fields: List of (name, value, inline) tuples for fields
        add_footer: Whether to add standard footer

    Returns:
        Configured discord.Embed
    """
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )

    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    if image_url:
        embed.set_image(url=image_url)

    if author_name:
        embed.set_author(name=author_name, icon_url=author_icon_url)

    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    if add_footer:
        set_footer(embed)

    return embed


# =============================================================================
# Specialized Embed Types
# =============================================================================

def create_success_embed(
    title: str,
    description: Optional[str] = None,
    **kwargs
) -> discord.Embed:
    """Create a success embed (green color)."""
    return create_embed(
        title=f"✅ {title}",
        description=description,
        color=EmbedColors.SUCCESS,
        **kwargs
    )


def create_error_embed(
    title: str,
    description: Optional[str] = None,
    **kwargs
) -> discord.Embed:
    """Create an error embed (gold/warning color)."""
    return create_embed(
        title=f"❌ {title}",
        description=description,
        color=EmbedColors.ERROR,
        **kwargs
    )


def create_warning_embed(
    title: str,
    description: Optional[str] = None,
    **kwargs
) -> discord.Embed:
    """Create a warning embed (gold color)."""
    return create_embed(
        title=f"⚠️ {title}",
        description=description,
        color=EmbedColors.WARNING,
        **kwargs
    )


def create_info_embed(
    title: str,
    description: Optional[str] = None,
    **kwargs
) -> discord.Embed:
    """Create an info embed (green color)."""
    return create_embed(
        title=f"ℹ️ {title}",
        description=description,
        color=EmbedColors.INFO,
        **kwargs
    )


# =============================================================================
# Timestamp Helpers
# =============================================================================

def add_timestamp_field(
    embed: discord.Embed,
    name: str = "Time",
    inline: bool = True
) -> discord.Embed:
    """
    Add a Discord timestamp field to an embed.

    Uses the current time in NY timezone formatted as a Discord timestamp.

    Args:
        embed: Embed to add field to
        name: Field name (default "Time")
        inline: Whether field should be inline

    Returns:
        The embed with timestamp field added
    """
    now = datetime.now(NY_TZ)
    embed.add_field(
        name=name,
        value=f"<t:{int(now.timestamp())}:f>",
        inline=inline
    )
    return embed


def format_discord_timestamp(dt: Optional[datetime] = None, style: str = "f") -> str:
    """
    Format a datetime as a Discord timestamp string.

    Args:
        dt: Datetime to format (defaults to now in NY_TZ)
        style: Discord timestamp style:
            - 't' = Short time (16:20)
            - 'T' = Long time (16:20:30)
            - 'd' = Short date (20/04/2021)
            - 'D' = Long date (20 April 2021)
            - 'f' = Short date/time (20 April 2021 16:20)
            - 'F' = Long date/time (Tuesday, 20 April 2021 16:20)
            - 'R' = Relative (2 months ago)

    Returns:
        Discord timestamp string (e.g., "<t:1618940700:f>")
    """
    if dt is None:
        dt = datetime.now(NY_TZ)
    return f"<t:{int(dt.timestamp())}:{style}>"


# =============================================================================
# Action Embed Types
# =============================================================================

def create_ban_embed(
    user: discord.User,
    reason: Optional[str] = None,
    moderator: Optional[discord.User] = None,
    duration: Optional[str] = None,
    **kwargs
) -> discord.Embed:
    """Create a ban notification embed."""
    fields = [
        ("User", f"{user.mention} ({user.id})", True),
        ("Reason", reason or "No reason provided", True),
    ]

    if duration:
        fields.append(("Duration", duration, True))

    if moderator:
        fields.append(("Moderator", moderator.mention, True))

    return create_embed(
        title="🚫 User Banned",
        color=EmbedColors.BAN,
        thumbnail_url=user.display_avatar.url,
        fields=fields,
        **kwargs
    )


def create_unban_embed(
    user: discord.User,
    reason: Optional[str] = None,
    moderator: Optional[discord.User] = None,
    **kwargs
) -> discord.Embed:
    """Create an unban notification embed."""
    fields = [
        ("User", f"{user.mention} ({user.id})", True),
        ("Reason", reason or "No reason provided", True),
    ]

    if moderator:
        fields.append(("Moderator", moderator.mention, True))

    return create_embed(
        title="✅ User Unbanned",
        color=EmbedColors.UNBAN,
        thumbnail_url=user.display_avatar.url,
        fields=fields,
        **kwargs
    )


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "create_embed",
    "create_success_embed",
    "create_error_embed",
    "create_warning_embed",
    "create_info_embed",
    "create_ban_embed",
    "create_unban_embed",
    # Timestamp helpers
    "add_timestamp_field",
    "format_discord_timestamp",
]
