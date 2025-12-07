"""
Othman Discord Bot - Main Bot Class
===================================

Core Discord client with modular architecture for the Syria Discord server.

ARCHITECTURE OVERVIEW:
======================
The bot follows a layered architecture with clear separation of concerns:

┌─────────────────────────────────────────────────────────────────┐
│                        BOT LAYER (bot.py)                        │
│  - Discord client setup and event routing                       │
│  - Service initialization and lifecycle management              │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   HANDLERS    │    │   SERVICES    │    │   COMMANDS    │
│ - ready.py    │    │ - scrapers/   │    │ - debates.py  │
│ - debates.py  │    │ - debates/    │    │   (slash cmds)│
│ - reactions.py│    │ - schedulers/ │    └───────────────┘
│ - shutdown.py │    └───────────────┘
└───────────────┘              │
                               ▼
                    ┌───────────────────┐
                    │     POSTING       │
                    │ - news.py         │
                    │ - soccer.py       │
                    │ - gaming.py       │
                    │ - debates.py      │
                    └───────────────────┘

KEY DESIGN DECISIONS:
=====================
1. CONTENT ROTATION: Posts rotate hourly (news → soccer → gaming)
   to spread API costs and provide variety

2. KARMA SYSTEM: Reddit-style upvote/downvote with ⬆️/⬇️ reactions
   - Stored in SQLite for persistence
   - Nightly reconciliation catches missed votes
   - Self-voting is blocked

3. HOT TAG MANAGEMENT: Automatic "Hot" tag based on activity thresholds
   - 10+ messages in 1 hour = Hot
   - No activity for 6+ hours = Remove Hot

4. GRACEFUL SHUTDOWN: All services properly cleaned up
   - Database connections closed
   - HTTP sessions terminated
   - Background tasks cancelled

Features:
- Fully automated hourly news posting
- Hot debates system with karma tracking
- Leaderboard with monthly/all-time stats
- AI-powered content summarization (OpenAI)
- Health check HTTP endpoint

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
    on_thread_delete_handler,
    on_debate_reaction_add,
    on_debate_reaction_remove,
    on_member_remove_handler,
    on_member_join_handler,
)
from src.services.debates import DebatesService


# =============================================================================
# OthmanBot Class
# =============================================================================

class OthmanBot(commands.Bot):
    """
    Main Discord bot class for Othman News Bot.

    DESIGN: Central orchestrator that:
    - Routes Discord events to appropriate handlers
    - Holds references to all services for cross-service communication
    - Manages bot lifecycle (startup, shutdown)

    SERVICE INITIALIZATION ORDER (in on_ready):
    1. Debates service (setup_hook)
    2. Content scrapers (news, soccer, gaming)
    3. Content rotation scheduler
    4. Debates scheduler (hot debates every 3 hours)
    5. Hot tag manager
    6. Karma reconciliation (startup + nightly)
    7. Leaderboard manager
    8. Backup scheduler
    9. Health check server

    INTENTS REQUIRED:
    - guilds: Access server info
    - reactions: Track upvotes/downvotes
    - members: Track user join/leave for leaderboard
    - message_content: Read debate messages for karma tracking
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """
        Initialize the Othman bot with necessary intents and configuration.

        DESIGN: Lazy initialization pattern - services are None until on_ready
        This prevents issues with Discord API calls before connection is established
        """
        intents = discord.Intents.default()
        intents.guilds = True
        intents.reactions = True
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",  # Not used - bot uses slash commands only
            intents=intents,
            help_command=None,
        )

        # =================================================================
        # Channel Configuration (loaded from environment)
        # DESIGN: Optional channels - bot continues if not configured
        # =================================================================
        self.news_channel_id: Optional[int] = load_news_channel_id()
        self.soccer_channel_id: Optional[int] = load_soccer_channel_id()
        self.gaming_channel_id: Optional[int] = load_gaming_channel_id()

        # =================================================================
        # Announcement Tracking
        # DESIGN: Prevents users from adding reactions to news announcements
        # Only the pre-set emoji reactions are allowed
        # =================================================================
        self.announcement_messages: set[int] = set()

        # =================================================================
        # Service Placeholders
        # DESIGN: Initialized in on_ready handler after Discord connection
        # All services are Optional to handle partial initialization gracefully
        # =================================================================
        self.news_scraper = None      # NewsScraper - fetches Middle East news
        self.soccer_scraper = None    # SoccerScraper - fetches Kooora soccer news
        self.gaming_scraper = None    # GamingScraper - fetches gaming news
        self.content_rotation_scheduler = None  # Rotates content hourly
        self.debates_service = None   # Karma tracking and debate management
        self.debates_scheduler = None # Posts hot debates every 3 hours

        # =================================================================
        # Background Tasks
        # DESIGN: Tracked for proper cleanup on shutdown
        # =================================================================
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

    async def on_thread_delete(self, thread: discord.Thread) -> None:
        """Event handler for thread deletion - triggers auto-renumbering."""
        await on_thread_delete_handler(self, thread)

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
