"""
OthmanBot - Debates Database (Redirect)
=================================================

This file redirects to the modular database package.
Import from src.services.debates.db instead.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Backwards compatibility - redirect to modular database
from src.services.debates.db import DebatesDatabase, UserKarma

__all__ = ["DebatesDatabase", "UserKarma"]
