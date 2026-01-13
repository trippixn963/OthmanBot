"""
OthmanBot - Centralized Colors
========================================

All colors used throughout the bot in one place.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord

from src.core.emojis import UPVOTE_EMOJI, DOWNVOTE_EMOJI, VERIFY_EMOJI, PARTICIPATE_EMOJI


# =============================================================================
# Base Color Values (Hex)
# =============================================================================

# Primary palette (TahaBot color scheme)
COLOR_GREEN = 0x1F5E2E      # Primary success
COLOR_GOLD = 0xE6B84A       # Warnings/alerts
COLOR_RED = 0xB43232        # Critical/denied

# Discord colors
COLOR_BLURPLE = 0x5865F2    # Discord blurple

# Status colors
COLOR_SUCCESS = 0x00FF00    # Bright green
COLOR_ERROR = 0xFF0000      # Bright red
COLOR_WARNING = 0xFFAA00    # Orange
COLOR_CRITICAL = 0x8B0000   # Dark red

# Feature colors
COLOR_KARMA = 0xFFD700      # Gold
COLOR_BAN = 0xFF4500        # Orange-red
COLOR_DEBATE = 0x3498DB     # Blue
COLOR_INFO = 0x9B59B6       # Purple
COLOR_NEWS = 0x1ABC9C       # Teal
COLOR_HOT = 0xFF6B6B        # Coral/Hot
COLOR_REACTION = 0xE67E22   # Orange
COLOR_ACCESS = 0x9B59B6     # Purple
COLOR_CLEANUP = 0x95A5A6    # Gray
COLOR_LEADERBOARD = 0xF1C40F  # Yellow/Gold

# Webhook/Status colors (aliases for consistency)
COLOR_ONLINE = COLOR_SUCCESS    # Green
COLOR_OFFLINE = COLOR_ERROR     # Red
COLOR_COMMAND = COLOR_BLURPLE   # Discord blurple


# =============================================================================
# Discord Embed Colors (discord.Color objects)
# =============================================================================

class EmbedColors:
    """
    Standardized color palette for Discord embeds.

    Matches TahaBot color scheme for consistency across all bots.
    """
    # Base colors
    GREEN = discord.Color.from_rgb(31, 94, 46)    # #1F5E2E
    GOLD = discord.Color.from_rgb(230, 184, 74)   # #E6B84A
    RED = discord.Color.from_rgb(180, 50, 50)     # #B43232

    # Action colors
    BAN = RED
    UNBAN = GREEN
    CLOSE = GOLD
    REOPEN = GREEN
    EXPIRED = GOLD

    # Appeal colors
    APPEAL_PENDING = GOLD
    APPEAL_APPROVED = GREEN
    APPEAL_DENIED = RED

    # Informational colors
    INFO = GREEN
    WARNING = GOLD
    SUCCESS = GREEN
    ERROR = GOLD

    # Special colors
    REJOIN_CLEAN = GOLD
    REJOIN_WARNING = RED


class EmbedIcons:
    """Standardized emoji icons for embed titles."""
    BAN = "🚫"
    UNBAN = "✅"
    CLOSE = "🔒"
    REOPEN = "🔓"
    EXPIRED = "⏰"
    APPEAL = "📝"
    APPROVED = "✅"
    DENIED = "❌"
    INFO = "📋"
    WARNING = "⚠️"
    LEAVE = "🚪"
    REJOIN = "🔄"
    ALERT = "🚨"
    PARTICIPATE = PARTICIPATE_EMOJI  # Custom verify emoji for participation access control


# Standard footer text
EMBED_FOOTER_TEXT = "trippixn.com/othman"

# Standard "no value" placeholder
EMBED_NO_VALUE = "_None provided_"


# =============================================================================
# Custom Emojis (re-exported from src/core/emojis.py for backwards compatibility)
# =============================================================================

# Karma emojis (from Syria server)
EMOJI_UPVOTE = UPVOTE_EMOJI
EMOJI_DOWNVOTE = DOWNVOTE_EMOJI

# Status emojis
EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"
EMOJI_WARNING = "⚠️"
EMOJI_INFO = "ℹ️"

# Action emojis
EMOJI_BAN = "🚫"
EMOJI_UNBAN = "✅"
EMOJI_CLOSE = "🔒"
EMOJI_REOPEN = "🔓"

# Feature emojis
EMOJI_KARMA = "⭐"
EMOJI_DEBATE = "💬"
EMOJI_NEWS = "📰"
EMOJI_HOT = "🔥"
