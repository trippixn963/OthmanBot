"""
OthmanBot - Colors Module
=========================

Re-exports shared colors plus OthmanBot-specific UI constants.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Import all shared colors
from shared.core.colors import *  # noqa: F401, F403

from src.core.emojis import UPVOTE_EMOJI, DOWNVOTE_EMOJI, VERIFY_EMOJI, PARTICIPATE_EMOJI


# =============================================================================
# OthmanBot-Specific Feature Colors (Hex)
# =============================================================================

COLOR_BAN = 0xFF4500        # Orange-red for bans
COLOR_DEBATE = 0x3498DB     # Blue for debates
COLOR_ACCESS = 0x9B59B6     # Purple for access control
COLOR_CLEANUP = 0x95A5A6    # Gray for cleanup
COLOR_REACTION = 0xE67E22   # Orange for reactions


# =============================================================================
# OthmanBot-Specific Embed Icons
# =============================================================================

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
    PARTICIPATE = PARTICIPATE_EMOJI


# =============================================================================
# OthmanBot-Specific Constants
# =============================================================================

EMBED_FOOTER_TEXT = "trippixn.com/othman"
EMBED_NO_VALUE = "_None provided_"


# =============================================================================
# Re-exported Custom Emojis (for backwards compatibility)
# =============================================================================

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
