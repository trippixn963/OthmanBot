"""
Othman Discord Bot - Debates Service Package
=============================================

Karma tracking for the debates forum.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.services.debates.database import DebatesDatabase, UserKarma
from src.services.debates.service import DebatesService, HotDebate

__all__ = [
    "DebatesDatabase",
    "UserKarma",
    "DebatesService",
    "HotDebate",
]
