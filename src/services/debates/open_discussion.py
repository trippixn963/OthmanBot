"""
OthmanBot - Open Discussion Service
===================================

Service for managing the Open Discussion thread - a casual conversation space
in the debates forum where karma is not tracked.

Features:
- Pinned thread with no numbering
- Original post contains rules with acknowledgment reaction
- No karma or message count tracking for users
- Unacknowledged users get message deleted with ephemeral reminder

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import (
    DEBATES_FORUM_ID,
    OWNER_ID,
    EmbedColors,
    EmbedIcons,
    OPEN_DISCUSSION_ACKNOWLEDGMENT_EMOJI,
)
from src.services.debates.database import DebatesDatabase
from src.utils.footer import set_footer
from src.handlers.debates_modules.access_control import (
    should_skip_access_control,
    check_user_ban,
)

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

# Thread title with emoji
OPEN_DISCUSSION_TITLE = "💬 | Open Discussion"

# Allowed message types (default text and replies, not system messages)
ALLOWED_MESSAGE_TYPES = (discord.MessageType.default, discord.MessageType.reply)

# Rules embed description - explains the purpose and rules of Open Discussion
RULES_DESCRIPTION = """
## Welcome to Open Discussion

This is a casual space for free-flowing conversation. Unlike regular debates, **karma is not tracked here** - no upvotes or downvotes affect your score.

### Guidelines

- **Be respectful** - Keep conversations civil and friendly
- **Stay on topic** - This is for general discussion, not spam
- **Low effort allowed** - Casual posts are welcome here
- **Have fun** - This is your space to chat freely

### How to Participate

**No verification needed!** Just start chatting - everyone can post here freely.

---
*Your messages here won't affect your karma stats or message counts.*
""".strip()


# =============================================================================
# Open Discussion Service
# =============================================================================

class OpenDiscussionService:
    """
    Service for managing the Open Discussion thread.

    The Open Discussion thread is a special pinned thread in the debates forum
    where users can have casual conversations without karma tracking. It features:
    - Always pinned at the top of the forum
    - No debate number in the title (format: "💬 | Open Discussion")
    - Original post contains rules with acknowledgment reaction
    - Users must react to original post before posting
    - Unacknowledged messages are deleted with ephemeral reminder

    DESIGN: Uses a single-instance pattern where the thread is created once
    and its ID is stored in the database. The original post serves as the
    permanent rules message that users must acknowledge.
    """

    def __init__(self, bot: "OthmanBot", db: DebatesDatabase) -> None:
        """
        Initialize the Open Discussion service.

        Args:
            bot: The OthmanBot instance
            db: Database instance for state persistence
        """
        self._bot = bot
        self._db = db
        self._lock = asyncio.Lock()  # Prevent concurrent operations

        logger.tree("Open Discussion Service Initialized", [
            ("Thread Name", OPEN_DISCUSSION_TITLE),
        ], emoji="💬")

    # -------------------------------------------------------------------------
    # Thread Management
    # -------------------------------------------------------------------------

    async def ensure_thread_exists(self) -> Optional[discord.Thread]:
        """
        Ensure the Open Discussion thread exists and is properly configured.

        Creates the thread if it doesn't exist, or retrieves it if it does.
        Also ensures the thread is pinned.

        Returns:
            The Open Discussion thread, or None if creation failed

        DESIGN: Idempotent operation - safe to call multiple times.
        Uses database to track thread ID across bot restarts.
        """
        async with self._lock:
            # Check if we already have a thread ID stored
            thread_id = self._db.get_open_discussion_thread_id()

            if thread_id:
                # Try to fetch existing thread
                thread = await self._fetch_thread(thread_id)
                if thread:
                    # Ensure it's still healthy (pinned, not archived)
                    await self._ensure_thread_healthy(thread)
                    return thread

                # Thread was deleted or inaccessible, create a new one
                logger.warning("Open Discussion Thread Not Found", [
                    ("Stored ID", str(thread_id)),
                    ("Action", "Creating new thread"),
                ])

            # Create new thread
            return await self._create_thread()

    async def _fetch_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """
        Fetch a thread by ID.

        Args:
            thread_id: Discord thread ID

        Returns:
            Thread object or None if not found
        """
        try:
            thread = self._bot.get_channel(thread_id)
            if isinstance(thread, discord.Thread):
                return thread

            # Try fetching if not in cache
            forum = self._bot.get_channel(DEBATES_FORUM_ID)
            if forum and isinstance(forum, discord.ForumChannel):
                thread = forum.get_thread(thread_id)
                if thread:
                    return thread

            return None

        except discord.HTTPException as e:
            logger.warning("Failed To Fetch Open Discussion Thread", [
                ("Thread ID", str(thread_id)),
                ("Error", str(e)),
            ])
            return None

    async def _create_thread(self) -> Optional[discord.Thread]:
        """
        Create a new Open Discussion thread.

        Returns:
            The created thread, or None if creation failed
        """
        try:
            forum = self._bot.get_channel(DEBATES_FORUM_ID)
            if not forum or not isinstance(forum, discord.ForumChannel):
                logger.error("Debates Forum Not Found", [
                    ("Forum ID", str(DEBATES_FORUM_ID)),
                ])
                return None

            # First, check for any existing Open Discussion threads and unpin them
            # This handles migration from old versions
            for thread in forum.threads:
                if "Open Discussion" in thread.name:
                    # Check if pinned using flags (for forum threads)
                    is_pinned = False
                    if hasattr(thread, 'flags') and hasattr(thread.flags, 'pinned'):
                        is_pinned = thread.flags.pinned
                    elif hasattr(thread, 'pinned'):
                        is_pinned = thread.pinned

                    if is_pinned:
                        try:
                            await thread.edit(pinned=False)
                            logger.info("Unpinned Old Open Discussion Thread", [
                                ("Thread ID", str(thread.id)),
                                ("Name", thread.name),
                            ])
                        except discord.HTTPException as e:
                            logger.debug("Could Not Unpin Old Open Discussion Thread", [
                                ("Thread ID", str(thread.id)),
                                ("Error", str(e)[:50]),
                            ])

            # Create the thread with starter message (rules)
            starter_embed = self._build_rules_embed()

            thread_with_message = await forum.create_thread(
                name=OPEN_DISCUSSION_TITLE,
                embed=starter_embed,
                reason="Creating Open Discussion thread",
            )

            thread = thread_with_message.thread
            starter_message = thread_with_message.message

            # Store the thread ID
            self._db.set_open_discussion_thread_id(thread.id)

            # Pin the thread
            await thread.edit(pinned=True)

            # Add acknowledgment reaction to starter message
            await starter_message.add_reaction(OPEN_DISCUSSION_ACKNOWLEDGMENT_EMOJI)

            logger.tree("Open Discussion Thread Created", [
                ("Thread ID", str(thread.id)),
                ("Thread Name", thread.name),
                ("Pinned", "Yes"),
            ], emoji="💬")

            return thread

        except discord.HTTPException as e:
            logger.error("Failed To Create Open Discussion Thread", [
                ("Error", str(e)),
            ])
            return None
        except Exception as e:
            logger.error("Unexpected Error Creating Open Discussion Thread", [
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])
            return None

    async def _ensure_thread_healthy(self, thread: discord.Thread) -> None:
        """
        Ensure the thread is in a healthy state (pinned, not archived, correct name).

        Args:
            thread: The Open Discussion thread
        """
        try:
            needs_update = False
            updates = {}

            # Check if name has the emoji prefix
            if thread.name != OPEN_DISCUSSION_TITLE:
                updates["name"] = OPEN_DISCUSSION_TITLE
                needs_update = True

            # Check if pinned (using flags for forum threads)
            is_pinned = False
            if hasattr(thread, 'flags') and hasattr(thread.flags, 'pinned'):
                is_pinned = thread.flags.pinned
            elif hasattr(thread, 'pinned'):
                is_pinned = thread.pinned

            if not is_pinned:
                updates["pinned"] = True
                needs_update = True

            # Check if archived
            if thread.archived:
                updates["archived"] = False
                needs_update = True

            if needs_update:
                await thread.edit(**updates)
                logger.tree("Open Discussion Thread Health Restored", [
                    ("Thread ID", str(thread.id)),
                    ("Fixed", ", ".join(updates.keys())),
                ], emoji="💬")

            # Clean up reactions on the original post - only ✅ should be there
            await self._cleanup_reactions(thread)

            # Refresh the original post embed (ensures footer has developer avatar)
            await self._refresh_original_embed(thread)

            # Clean up any existing system messages
            await self._cleanup_system_messages(thread)

        except discord.HTTPException as e:
            logger.warning("Failed To Restore Open Discussion Thread Health", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)),
            ])

    async def _cleanup_reactions(self, thread: discord.Thread) -> None:
        """
        Remove unwanted reactions from the original post.

        Only the acknowledgment emoji (✅) should be present.

        Args:
            thread: The Open Discussion thread
        """
        try:
            # Fetch the starter message (ID equals thread ID for forum threads)
            starter_message = await thread.fetch_message(thread.id)

            # Remove any reactions that aren't the acknowledgment emoji
            for reaction in starter_message.reactions:
                if str(reaction.emoji) != OPEN_DISCUSSION_ACKNOWLEDGMENT_EMOJI:
                    # Remove the bot's reaction if present
                    try:
                        await starter_message.clear_reaction(reaction.emoji)
                        logger.info("Removed Unwanted Reaction from Open Discussion", [
                            ("Emoji", str(reaction.emoji)),
                        ])
                    except discord.HTTPException as e:
                        logger.debug("Could Not Clear Reaction From Open Discussion", [
                            ("Emoji", str(reaction.emoji)),
                            ("Error", str(e)[:50]),
                        ])

        except discord.NotFound:
            logger.debug("Open Discussion Starter Message Not Found (Cleanup Reactions)", [
                ("Thread ID", str(thread.id)),
            ])
        except discord.HTTPException as e:
            logger.debug("Open Discussion Reaction Cleanup Failed", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)[:50]),
            ])

    async def _refresh_original_embed(self, thread: discord.Thread) -> None:
        """
        Refresh the original post embed to ensure content and footer are current.

        Called on startup to keep the rules embed up to date.

        Args:
            thread: The Open Discussion thread
        """
        try:
            # Fetch the starter message (ID equals thread ID for forum threads)
            starter_message = await thread.fetch_message(thread.id)

            # Build fresh embed with current content
            new_embed = self._build_rules_embed()

            # Check if embed needs updating (compare description and footer)
            current_embeds = starter_message.embeds
            needs_update = False

            if current_embeds:
                current_embed = current_embeds[0]
                # Update if description or footer changed
                if current_embed.description != new_embed.description:
                    needs_update = True
                elif current_embed.footer.icon_url != new_embed.footer.icon_url:
                    needs_update = True
            else:
                needs_update = True

            if needs_update:
                await starter_message.edit(embed=new_embed)
                logger.info("Open Discussion Embed Refreshed", [
                    ("Thread ID", str(thread.id)),
                    ("Reason", "Content updated"),
                ])

        except discord.NotFound:
            logger.debug("Open Discussion Starter Message Not Found (Refresh Embed)", [
                ("Thread ID", str(thread.id)),
            ])
        except discord.HTTPException as e:
            logger.debug("Could Not Refresh Open Discussion Embed", [
                ("Thread ID", str(thread.id)),
                ("Error", str(e)[:50]),
            ])

    async def _cleanup_system_messages(self, thread: discord.Thread) -> None:
        """
        Delete existing system messages in the Open Discussion thread.

        System messages include "changed the post title", pins, etc.

        Args:
            thread: The Open Discussion thread
        """
        deleted_count = 0
        try:
            # Fetch recent messages (system messages are usually recent)
            async for message in thread.history(limit=50):
                # Skip the original post (starter message)
                if message.id == thread.id:
                    continue

                # Delete system message types (allow default and replies)
                if message.type not in ALLOWED_MESSAGE_TYPES:
                    try:
                        await message.delete()
                        deleted_count += 1
                    except discord.HTTPException as e:
                        logger.debug("Could Not Delete System Message In Open Discussion", [
                            ("Message ID", str(message.id)),
                            ("Type", str(message.type)),
                            ("Error", str(e)[:50]),
                        ])

            if deleted_count > 0:
                logger.info("Open Discussion System Messages Cleaned", [
                    ("Thread ID", str(thread.id)),
                    ("Deleted", str(deleted_count)),
                ])

        except discord.HTTPException as e:
            logger.debug("Could Not Cleanup System Messages", [
                ("Error", str(e)),
            ])

    # -------------------------------------------------------------------------
    # Rules Embed
    # -------------------------------------------------------------------------

    def _build_rules_embed(self) -> discord.Embed:
        """
        Build the rules embed for the original post.

        Returns:
            Configured Discord embed with rules
        """
        embed = discord.Embed(
            title=f"{EmbedIcons.INFO} Open Discussion Guidelines",
            description=RULES_DESCRIPTION,
            color=EmbedColors.GREEN,
        )
        set_footer(embed)
        return embed

    # -------------------------------------------------------------------------
    # Message Handler
    # -------------------------------------------------------------------------

    async def on_message(self, message: discord.Message) -> bool:
        """
        Handle a message in the Open Discussion thread.

        Called for every message in the thread. Checks for bans but no
        verification needed - anyone can post freely. Cleans up system messages.

        Args:
            message: The message that was sent

        Returns:
            True if this is the Open Discussion thread (to skip karma tracking)
        """
        # Check if this is the Open Discussion thread
        if not isinstance(message.channel, discord.Thread):
            return False

        open_discussion_id = self._db.get_open_discussion_thread_id()
        if not open_discussion_id or message.channel.id != open_discussion_id:
            return False

        # Delete system messages (e.g., "changed the post title")
        if message.type not in ALLOWED_MESSAGE_TYPES:
            try:
                await message.delete()
                logger.debug("Open Discussion System Message Deleted", [
                    ("Type", str(message.type)),
                ])
            except discord.HTTPException:
                pass
            return True

        # Skip ban check for privileged users (mods/developers)
        if isinstance(message.author, discord.Member) and should_skip_access_control(message.author):
            return True

        # Check if user is banned (uses centralized function with proper logging)
        if not await check_user_ban(self._bot, message):
            return True

        # No verification needed - everyone can post freely
        return True

    async def _has_user_acknowledged(
        self,
        thread: discord.Thread,
        user: discord.User | discord.Member
    ) -> bool:
        """
        Check if a user has acknowledged the Open Discussion rules.

        Users must react to the original post (starter message) to gain posting access.
        The starter message ID equals the thread ID for forum threads.

        Args:
            thread: The Open Discussion thread
            user: User to check

        Returns:
            True if user has acknowledged rules
        """
        try:
            # For forum threads, the starter message ID equals the thread ID
            starter_message = await thread.fetch_message(thread.id)

            # Check if user has reacted with acknowledgment emoji
            for reaction in starter_message.reactions:
                if str(reaction.emoji) == OPEN_DISCUSSION_ACKNOWLEDGMENT_EMOJI:
                    async for reactor in reaction.users():
                        if reactor.id == user.id:
                            return True

            return False

        except discord.NotFound:
            return True  # Starter message not found = allow access (fail open)
        except discord.HTTPException:
            return True  # Error = allow access (fail open)

    async def _send_acknowledgment_reminder(
        self,
        thread: discord.Thread,
        user: discord.User | discord.Member
    ) -> None:
        """
        Send an auto-deleting reminder to the user to acknowledge the rules.

        The message is deleted after 8 seconds to keep the channel clean.

        Args:
            thread: The Open Discussion thread
            user: User to remind
        """
        try:
            # Build the message link to the original post
            # Format: https://discord.com/channels/{guild_id}/{channel_id}/{message_id}
            message_link = f"https://discord.com/channels/{thread.guild.id}/{thread.id}/{thread.id}"

            embed = discord.Embed(
                title=f"{EmbedIcons.WARNING} Acknowledge Rules First",
                description=(
                    f"{user.mention}, your message was removed.\n\n"
                    f"Please react with {OPEN_DISCUSSION_ACKNOWLEDGMENT_EMOJI} "
                    f"to the **[rules message]({message_link})** before posting.\n\n"
                    "*This is a one-time acknowledgment.*"
                ),
                color=EmbedColors.GOLD,
            )
            set_footer(embed)

            # Send message and delete after 8 seconds (consistent with regular debates)
            reminder_msg = await thread.send(embed=embed)
            await reminder_msg.delete(delay=8)

        except discord.HTTPException as e:
            logger.warning("Failed To Send Acknowledgment Reminder", [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Error", str(e)),
            ])
        except Exception as e:
            logger.warning("Unexpected Error Sending Acknowledgment Reminder", [
                ("Error Type", type(e).__name__),
                ("Error", str(e)),
            ])

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def is_open_discussion_thread(self, thread_id: int) -> bool:
        """
        Check if a thread is the Open Discussion thread.

        Args:
            thread_id: Thread ID to check

        Returns:
            True if this is the Open Discussion thread
        """
        open_discussion_id = self._db.get_open_discussion_thread_id()
        return open_discussion_id is not None and thread_id == open_discussion_id

    def get_thread_id(self) -> Optional[int]:
        """
        Get the Open Discussion thread ID.

        Returns:
            Thread ID or None if not set
        """
        return self._db.get_open_discussion_thread_id()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["OpenDiscussionService"]
