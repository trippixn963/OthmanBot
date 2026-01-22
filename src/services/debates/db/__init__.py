"""
OthmanBot - Debates Database Package
====================================

Modular SQLite database with mixins for different features.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.services.debates.db.database import DebatesDatabase
from src.services.debates.db.core import UserKarma
from src.services.debates.db.models import (
    BanRecord,
    BanHistoryRecord,
    BanInfo,
    VoteRecord,
    DebateThread,
    ThreadParticipation,
    CaseLog,
    ClosureHistoryRecord,
    AnalyticsMessage,
    ThreadAnalytics,
    AppealRecord,
    UserStreak,
)

__all__ = [
    "DebatesDatabase",
    # Models
    "UserKarma",
    "BanRecord",
    "BanHistoryRecord",
    "BanInfo",
    "VoteRecord",
    "DebateThread",
    "ThreadParticipation",
    "CaseLog",
    "ClosureHistoryRecord",
    "AnalyticsMessage",
    "ThreadAnalytics",
    "AppealRecord",
    "UserStreak",
]
