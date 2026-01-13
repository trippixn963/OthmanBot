"""
OthmanBot - Database Models
===========================

Dataclass definitions for database records.
Provides type safety and structure for database query results.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# =============================================================================
# User Models
# =============================================================================

@dataclass
class UserKarma:
    """User karma statistics."""
    user_id: int
    total_karma: int
    upvotes_received: int
    downvotes_received: int


@dataclass
class UserStreak:
    """User participation streak data."""
    user_id: int
    current_streak: int
    longest_streak: int
    last_participation_date: Optional[str] = None


# =============================================================================
# Ban Models
# =============================================================================

@dataclass
class BanRecord:
    """Active ban record."""
    user_id: int
    thread_id: Optional[int]
    banned_by: int
    reason: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class BanHistoryRecord:
    """Historical ban record for audit purposes."""
    id: int
    user_id: int
    thread_id: Optional[int]
    banned_by: int
    reason: Optional[str] = None
    duration_hours: Optional[float] = None
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    unbanned_at: Optional[str] = None
    unbanned_by: Optional[int] = None


@dataclass
class BanInfo:
    """Simplified ban info for autocomplete."""
    user_id: int
    expires_at: Optional[str]
    thread_id: Optional[int]


# =============================================================================
# Vote Models
# =============================================================================

@dataclass
class VoteRecord:
    """Vote record for a message."""
    voter_id: int
    message_id: int
    author_id: int
    value: int  # +1 for upvote, -1 for downvote
    thread_id: Optional[int] = None
    created_at: Optional[str] = None


# =============================================================================
# Thread Models
# =============================================================================

@dataclass
class DebateThread:
    """Debate thread record."""
    thread_id: int
    debate_number: int
    creator_id: int
    title: Optional[str] = None
    created_at: Optional[str] = None
    closed_at: Optional[str] = None
    closed_by: Optional[int] = None


@dataclass
class ThreadParticipation:
    """User participation in a thread."""
    thread_id: int
    user_id: int
    message_count: int = 0
    first_message_at: Optional[str] = None
    last_message_at: Optional[str] = None


# =============================================================================
# Case Log Models
# =============================================================================

@dataclass
class CaseLog:
    """Case log entry for moderation actions."""
    user_id: int
    case_thread_id: Optional[int] = None
    action_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ClosureHistoryRecord:
    """Thread closure history record."""
    id: int
    thread_id: int
    action: str  # 'close' or 'reopen'
    performed_by: int
    reason: Optional[str] = None
    created_at: Optional[str] = None


# =============================================================================
# Analytics Models
# =============================================================================

@dataclass
class AnalyticsMessage:
    """Analytics message reference for a thread."""
    thread_id: int
    message_id: int
    created_at: Optional[str] = None


@dataclass
class ThreadAnalytics:
    """Computed analytics for a debate thread."""
    thread_id: int
    total_messages: int = 0
    unique_participants: int = 0
    total_upvotes: int = 0
    total_downvotes: int = 0
    approval_rate: float = 0.0


# =============================================================================
# Appeal Models
# =============================================================================

@dataclass
class AppealRecord:
    """Appeal submission record."""
    id: int
    user_id: int
    action_type: str  # 'disallow', 'close', etc.
    action_id: int
    reason: str
    status: str = "pending"  # pending, approved, denied
    created_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[int] = None


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # User models
    "UserKarma",
    "UserStreak",
    # Ban models
    "BanRecord",
    "BanHistoryRecord",
    "BanInfo",
    # Vote models
    "VoteRecord",
    # Thread models
    "DebateThread",
    "ThreadParticipation",
    # Case log models
    "CaseLog",
    "ClosureHistoryRecord",
    # Analytics models
    "AnalyticsMessage",
    "ThreadAnalytics",
    # Appeal models
    "AppealRecord",
]
