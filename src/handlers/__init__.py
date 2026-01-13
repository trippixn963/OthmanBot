"""
Othman Discord Bot - Handlers Package
======================================

Event handlers as Discord.py Cogs.
Cogs are loaded in bot.py via load_extension().

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Handlers are loaded as extensions, not imported here
# This prevents circular import issues and allows lazy loading

from src.handlers.shutdown import shutdown_handler

__all__ = [
    "shutdown_handler",
]
