"""
OthmanBot - Centralized Emoji Constants
=======================================

All custom Discord emoji IDs in one place.
Import from here instead of defining in multiple files.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""


# =============================================================================
# Karma/Voting Emojis
# =============================================================================

UPVOTE_EMOJI = "<:upvote:1460602851331014811>"
DOWNVOTE_EMOJI = "<:downvote:1460603397748035606>"


# =============================================================================
# UI/Interaction Emojis
# =============================================================================

VERIFY_EMOJI = "<:verify:1460604872754725028>"
LEADERBOARD_EMOJI = "<:leaderboard:1452015571120951316>"
APPEAL_EMOJI = "<:appeal:1460605659371274446>"


# =============================================================================
# Participation Access Control
# =============================================================================

# Used for debate participation gating
PARTICIPATE_EMOJI = VERIFY_EMOJI


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "UPVOTE_EMOJI",
    "DOWNVOTE_EMOJI",
    "VERIFY_EMOJI",
    "LEADERBOARD_EMOJI",
    "PARTICIPATE_EMOJI",
    "APPEAL_EMOJI",
]
