"""
Othman Discord Bot - Main Bot Class
===================================

Core Discord client with modular architecture.

Features:
- Fully automated hourly news posting
- Hot debates system
- Clean separation of concerns

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import Optional

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import (
    load_news_channel_id,
    load_soccer_channel_id,
    load_gaming_channel_id,
    load_general_channel_id,
)
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
from src.services.debates import DebatesService
from src.services.debates.hostility import HostilityTracker


# =============================================================================
# OthmanBot Class
# =============================================================================

class OthmanBot(commands.Bot):
    """Main Discord bot class for Othman News Bot."""

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """Initialize the Othman bot with necessary intents and configuration."""
        intents = discord.Intents.default()
        intents.guilds = True
        intents.reactions = True
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

        # Load channel configuration
        self.news_channel_id: Optional[int] = load_news_channel_id()
        self.soccer_channel_id: Optional[int] = load_soccer_channel_id()
        self.gaming_channel_id: Optional[int] = load_gaming_channel_id()

        # Track announcement messages for reaction blocking
        self.announcement_messages: set[int] = set()

        # Service placeholders (initialized in on_ready)
        self.news_scraper = None
        self.soccer_scraper = None
        self.gaming_scraper = None
        self.content_rotation_scheduler = None
        self.debates_service = None
        self.debates_scheduler = None
        self.hostility_tracker = None

        # Background task for presence updates
        self.presence_task: Optional[asyncio.Task] = None

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def general_channel_id(self) -> Optional[int]:
        """Get general channel ID from environment."""
        return load_general_channel_id()

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def setup_hook(self) -> None:
        """Setup hook called when bot is starting."""
        # Initialize debates service
        self.debates_service = DebatesService()

        # Initialize hostility tracker (uses debates_service database)
        self.hostility_tracker = HostilityTracker(self.debates_service.db)

        # Load debates cog
        await self.load_extension("src.commands.debates")

        # Note: Commands will be synced in on_ready for instant guild-specific sync
        logger.info("Bot setup complete - commands will sync on ready")

    async def on_ready(self) -> None:
        """Event handler called when bot is ready."""
        await on_ready_handler(self)

    async def on_message(self, message: discord.Message) -> None:
        """Event handler for messages."""
        await on_message_handler(self, message)

    async def on_thread_create(self, thread: discord.Thread) -> None:
        """Event handler for thread creation."""
        await on_thread_create_handler(self, thread)

    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        user: discord.User
    ) -> None:
        """Event handler for reaction additions."""
        await on_reaction_add_handler(self, reaction, user)
        await on_debate_reaction_add(self, reaction, user)

    async def on_reaction_remove(
        self,
        reaction: discord.Reaction,
        user: discord.User
    ) -> None:
        """Event handler for reaction removals."""
        await on_debate_reaction_remove(self, reaction, user)

    async def on_member_remove(self, member: discord.Member) -> None:
        """Event handler for member leaving the server."""
        await on_member_remove_handler(self, member)

    async def on_member_join(self, member: discord.Member) -> None:
        """Event handler for member joining the server."""
        await on_member_join_handler(self, member)

    async def close(self) -> None:
        """Cleanup when bot is shutting down."""
        await shutdown_handler(self)
        await super().close()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["OthmanBot"]
