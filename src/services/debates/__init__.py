"""
OthmanBot - Debates Service Package
===================================

Karma tracking for the debates forum.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.services.debates.db import DebatesDatabase, UserKarma
from src.services.debates.service import DebatesService, HotDebate
from src.services.debates.open_discussion import OpenDiscussionService

__all__ = [
    "DebatesDatabase",
    "UserKarma",
    "DebatesService",
    "HotDebate",
    "OpenDiscussionService",
]
