"""
Othman Discord Bot - Handlers Package
======================================

Event handlers for bot lifecycle and Discord events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.handlers.ready import on_ready_handler
from src.handlers.reactions import on_reaction_add_handler
from src.handlers.shutdown import shutdown_handler
from src.handlers.debates import (
    on_message_handler,
    on_thread_create_handler,
    on_debate_reaction_add,
    on_debate_reaction_remove,
    on_member_remove_handler,
    on_member_join_handler,
)

__all__ = [
    "on_ready_handler",
    "on_reaction_add_handler",
    "shutdown_handler",
    "on_message_handler",
    "on_thread_create_handler",
    "on_debate_reaction_add",
    "on_debate_reaction_remove",
    "on_member_remove_handler",
    "on_member_join_handler",
]
