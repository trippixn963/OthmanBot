"""
OthmanBot - Debates Handler Package
===================================

Modular debate forum event handlers.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.handlers.debates_modules.analytics import (
    update_analytics_embed,
    refresh_all_analytics_embeds,
)
from src.handlers.debates_modules.access_control import (
    DEBATE_MANAGEMENT_ROLE_ID,
    has_debate_management_role,
    should_skip_access_control,
    check_user_participation,
    check_user_ban,
)
from src.handlers.debates_modules.reactions import (
    on_debate_reaction_add,
    on_debate_reaction_remove,
    is_debates_forum_message,
)
from src.handlers.debates_modules.member_lifecycle import (
    on_member_remove_handler,
    on_member_join_handler,
)
from src.handlers.debates_modules.thread_management import (
    get_next_debate_number,
    extract_debate_number,
    renumber_debates_after_deletion,
    on_thread_delete_handler,
)

__all__ = [
    # Analytics
    "update_analytics_embed",
    "refresh_all_analytics_embeds",
    # Access control
    "DEBATE_MANAGEMENT_ROLE_ID",
    "has_debate_management_role",
    "should_skip_access_control",
    "check_user_participation",
    "check_user_ban",
    # Reactions
    "on_debate_reaction_add",
    "on_debate_reaction_remove",
    "is_debates_forum_message",
    # Member lifecycle
    "on_member_remove_handler",
    "on_member_join_handler",
    # Thread management
    "get_next_debate_number",
    "extract_debate_number",
    "renumber_debates_after_deletion",
    "on_thread_delete_handler",
]
