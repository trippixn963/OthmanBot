"""
OthmanBot - Slash Commands Package
==================================

Discord slash commands for OthmanBot functionality.

Available Commands:
- /toggle - Enable/disable bot functionality (Developer only)
- /karma - Check karma points for yourself or another user
- /disallow - Ban a user from a debate thread or all debates
- /allow - Unban a user from a debate thread or all debates
- /rename - Rename a locked debate thread with proper numbering
- /cases - Look up a user's moderation case history
- /close - Close a debate thread with a reason
- /open - Reopen a closed debate thread with a reason

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.commands.toggle import ToggleCog
from src.commands.karma import KarmaCog
from src.commands.disallow import DisallowCog
from src.commands.allow import AllowCog
from src.commands.rename import RenameCog
from src.commands.cases import CasesCog
from src.commands.close import CloseCog
from src.commands.open import OpenCog

__all__ = [
    "ToggleCog",
    "KarmaCog",
    "DisallowCog",
    "AllowCog",
    "RenameCog",
    "CasesCog",
    "CloseCog",
    "OpenCog",
]
