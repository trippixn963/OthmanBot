"""
OthmanBot - Main Bot Class
====================================

Core Discord client for the Syria Discord server combining automated
news posting with a debates forum featuring karma tracking.

Features:
- Automated hourly news posting (news, soccer rotation)
- Debates forum with karma tracking
- Moderation tools (disallow, close, rename)
- Appeal system with persistent buttons
- Case logging to moderator forum
- AI-powered content summarization
- Health check HTTP endpoint

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import asyncio
from typing import Optional

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import (
    load_news_channel_id,
    load_soccer_channel_id,
    load_general_channel_id,
)
from src.handlers.shutdown import shutdown_handler
from src.services.debates import DebatesService, OpenDiscussionService
from src.services.webhook_alerts import get_alert_service
from src.services.case_log import CaseLogService
from src.services.ban_notifier import BanNotifier
from src.services.appeal_service import AppealService
from src.views.appeals import (
    handle_appeal_button_interaction,
    handle_review_button_interaction,
    handle_info_button_interaction,
)


# =============================================================================
# Constants
# =============================================================================

# Status channel ID for online/offline indicator (in mods server)
STATUS_CHANNEL_ID = int(os.getenv("STATUS_CHANNEL_ID", "0"))


# =============================================================================
# OthmanBot Class
# =============================================================================

class OthmanBot(commands.Bot):
    """
    Main Discord bot class for Othman News & Debates Bot.

    DESIGN: Central orchestrator that:
    - Routes Discord events to appropriate handlers
    - Holds references to all services for cross-service communication
    - Manages bot lifecycle (startup, shutdown)
    - Routes persistent button clicks for appeal system

    SERVICE INITIALIZATION ORDER:
    1. setup_hook (before on_ready):
       - Debates service (karma, database)
       - Interaction logger (webhook logging)
       - Case log service (moderator forum threads)
       - Ban notifier service (DM notifications)
       - Appeal service (appeal submission/review)
       - Persistent views registration
       - Command cog loading

    2. on_ready:
       - Content scrapers (news, soccer)
       - Content rotation scheduler (hourly posts)
       - Hot tag manager
       - Karma reconciliation (startup + nightly)
       - Backup scheduler
       - Health check server
       - Numbering scheduler
       - Presence rotation

    INTENTS REQUIRED:
    - guilds: Access server info
    - reactions: Track upvotes/downvotes
    - members: Track user join/leave
    - message_content: Read debate messages for karma tracking
    - presences: Track user online status for karma cards
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
        intents.presences = True  # Required for accurate user status in karma cards

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

        # =================================================================
        # Announcement Tracking
        # DESIGN: Prevents users from adding reactions to news announcements
        # Only the pre-set emoji reactions are allowed
        # =================================================================
        self.announcement_messages: set[int] = set()

        # =================================================================
        # Service Placeholders
        # DESIGN: Most initialized in setup_hook, some in on_ready
        # All services are Optional to handle partial initialization gracefully
        # =================================================================
        self.news_scraper = None      # NewsScraper - fetches Middle East news
        self.soccer_scraper = None    # SoccerScraper - fetches Kooora soccer news
        self.content_rotation_scheduler = None  # Rotates content hourly
        self.debates_service = None   # Karma tracking and debate management
        self.open_discussion = None   # Open Discussion service (casual chat, no karma)
        self.stats_api = None         # Stats API for dashboard

        # =================================================================
        # Presence Handler
        # DESIGN: Manages rotating presence and hourly promo
        # =================================================================
        self.presence_handler = None  # Set by ready handler

        # =================================================================
        # Ready State Guard
        # DESIGN: Prevents on_ready from running multiple times
        # Discord can fire on_ready multiple times (reconnects, etc.)
        # =================================================================
        self._ready_initialized: bool = False

        # =================================================================
        # Disabled State
        # DESIGN: When True, all handlers and schedulers stop processing
        # Bot stays connected for remote re-enabling via /toggle command
        # =================================================================
        self.disabled: bool = False

        # =================================================================
        # Webhook Alerts Service
        # DESIGN: Singleton service for Discord webhook notifications
        # =================================================================
        self.alert_service = get_alert_service()

        # =================================================================
        # Case Log Service
        # DESIGN: Logs ban/unban actions to forum threads in mods server
        # =================================================================
        self.case_log_service: Optional[CaseLogService] = None

        # =================================================================
        # Ban Notifier Service
        # DESIGN: Sends DM notifications to users when banned/unbanned
        # =================================================================
        self.ban_notifier: Optional[BanNotifier] = None

        # =================================================================
        # Appeal Service
        # DESIGN: Handles appeal submission, approval, and denial
        # =================================================================
        self.appeal_service: Optional[AppealService] = None

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

        # Initialize open discussion service (casual chat, no karma tracking)
        self.open_discussion = OpenDiscussionService(self, self.debates_service.db)

        # Initialize case log service (for ban/unban logging to mods server)
        self.case_log_service = CaseLogService(self)

        # Initialize ban notifier service (for DM notifications)
        self.ban_notifier = BanNotifier(self)

        # Initialize appeal service (for appeal submission/review)
        self.appeal_service = AppealService(self)

        # NOTE: Appeal buttons are handled via on_interaction, not add_view()
        # This avoids duplicate handling since on_interaction routes all appeal buttons

        # Load command cogs (each command in its own file)
        await self.load_extension("src.commands.toggle")
        await self.load_extension("src.commands.karma")
        await self.load_extension("src.commands.disallow")
        await self.load_extension("src.commands.allow")
        await self.load_extension("src.commands.rename")
        await self.load_extension("src.commands.cases")
        await self.load_extension("src.commands.close")
        await self.load_extension("src.commands.open")

        # Load handler cogs (self-register their event listeners)
        await self.load_extension("src.handlers.ready")
        await self.load_extension("src.handlers.reactions")
        await self.load_extension("src.handlers.debates")

        logger.info("Bot Setup Complete", [
            ("Status", "Commands and handlers loaded"),
        ])

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Event handler for all interactions.

        DESIGN: Handles persistent button clicks for appeal system.
        Discord's add_view() doesn't work well with dynamic custom_ids,
        so we catch button clicks here and route them manually.
        """
        # Only handle component (button) interactions
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""

        # Route appeal review button clicks (check first - more specific prefix)
        if custom_id.startswith("appeal_review:"):
            # Check if this is the "More Info" button
            if custom_id.endswith(":info"):
                await handle_info_button_interaction(interaction, custom_id)
            else:
                await handle_review_button_interaction(interaction, custom_id)
            return

        # Route appeal button clicks
        if custom_id.startswith("appeal:"):
            await handle_appeal_button_interaction(interaction, custom_id)
            return

    async def close(self) -> None:
        """Cleanup when bot is shutting down."""
        await shutdown_handler(self)
        await super().close()

    # =========================================================================
    # Status Channel
    # =========================================================================

    async def update_status_channel(self, online: bool) -> None:
        """
        Update the status channel name to indicate bot online/offline status.

        Args:
            online: True for online (green), False for offline (red)
        """
        if not STATUS_CHANNEL_ID:
            return

        try:
            # Try cache first, then fetch from API
            channel = self.get_channel(STATUS_CHANNEL_ID)
            if not channel:
                try:
                    channel = await self.fetch_channel(STATUS_CHANNEL_ID)
                except discord.NotFound:
                    logger.warning("Status Channel Not Found", [
                        ("Channel ID", str(STATUS_CHANNEL_ID)),
                    ])
                    return
                except discord.Forbidden:
                    logger.warning("Status Channel Access Denied", [
                        ("Channel ID", str(STATUS_CHANNEL_ID)),
                    ])
                    return

            new_name = "🟢・status" if online else "🔴・status"
            await channel.edit(name=new_name)
            logger.info("Status Channel Updated", [
                ("Status", "Online" if online else "Offline"),
                ("Channel", new_name),
            ])
        except discord.Forbidden as e:
            logger.warning("Failed To Update Status Channel (Permissions)", [
                ("Error", str(e)),
            ])
        except Exception as e:
            logger.warning("Failed To Update Status Channel", [
                ("Error", str(e)),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["OthmanBot"]
