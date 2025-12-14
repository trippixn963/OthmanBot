"""
Othman Discord Bot - Debates Service
=====================================

High-level service for karma tracking operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass

import discord

from src.core.logger import logger
from src.core.config import NY_TZ
from src.services.debates.database import DebatesDatabase, UserKarma

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class HotDebate:
    """Represents a hot debate with calculated metrics."""
    thread: discord.Thread
    reply_count: int
    karma: int
    hotness_score: float
    top_contributor_id: Optional[int]
    top_contributor_name: str


# =============================================================================
# Debates Service
# =============================================================================

class DebatesService:
    """Service for managing debate karma system."""

    def __init__(self) -> None:
        """Initialize the debates service."""
        self.db = DebatesDatabase()
        logger.info("Debates Service Initialized", [
            ("Database", "Connected"),
        ])

    def record_upvote(
        self,
        voter_id: int,
        message_id: int,
        author_id: int
    ) -> bool:
        """
        Record an upvote on a message.

        Args:
            voter_id: User who upvoted
            message_id: Message being upvoted
            author_id: Author of the message

        Returns:
            True if vote was recorded
        """
        if voter_id == author_id:
            return False  # No self-voting

        result = self.db.add_vote(voter_id, message_id, author_id, 1)
        if result:
            logger.debug("⬆️ Upvote Recorded", [
                ("Voter", str(voter_id)),
                ("Message", str(message_id)),
            ])
        return result

    def record_downvote(
        self,
        voter_id: int,
        message_id: int,
        author_id: int
    ) -> bool:
        """
        Record a downvote on a message.

        Args:
            voter_id: User who downvoted
            message_id: Message being downvoted
            author_id: Author of the message

        Returns:
            True if vote was recorded
        """
        if voter_id == author_id:
            return False  # No self-voting

        result = self.db.add_vote(voter_id, message_id, author_id, -1)
        if result:
            logger.debug("⬇️ Downvote Recorded", [
                ("Voter", str(voter_id)),
                ("Message", str(message_id)),
            ])
        return result

    async def record_upvote_async(
        self,
        voter_id: int,
        message_id: int,
        author_id: int
    ) -> bool:
        """
        Async version of record_upvote with retry logic.
        """
        if voter_id == author_id:
            return False  # No self-voting

        result = await self.db.add_vote_async(voter_id, message_id, author_id, 1)
        if result:
            logger.debug("⬆️ Upvote Recorded (Async)", [
                ("Voter", str(voter_id)),
                ("Message", str(message_id)),
            ])
        return result

    async def record_downvote_async(
        self,
        voter_id: int,
        message_id: int,
        author_id: int
    ) -> bool:
        """
        Async version of record_downvote with retry logic.
        """
        if voter_id == author_id:
            return False  # No self-voting

        result = await self.db.add_vote_async(voter_id, message_id, author_id, -1)
        if result:
            logger.debug("⬇️ Downvote Recorded (Async)", [
                ("Voter", str(voter_id)),
                ("Message", str(message_id)),
            ])
        return result

    def remove_vote(
        self,
        voter_id: int,
        message_id: int
    ) -> bool:
        """
        Remove a vote from a message.

        Args:
            voter_id: User who is removing their vote
            message_id: Message to remove vote from

        Returns:
            True if vote was removed
        """
        author_id = self.db.remove_vote(voter_id, message_id)
        if author_id:
            logger.debug("🗑️ Vote Removed", [
                ("Voter", str(voter_id)),
                ("Message", str(message_id)),
            ])
            return True
        return False

    def get_karma(self, user_id: int) -> UserKarma:
        """
        Get karma stats for a user.

        Args:
            user_id: User ID

        Returns:
            UserKarma data
        """
        return self.db.get_user_karma(user_id)

    def get_leaderboard(self, limit: int = 10) -> list[UserKarma]:
        """
        Get karma leaderboard.

        Args:
            limit: Number of users to return

        Returns:
            List of UserKarma sorted by total_karma
        """
        return self.db.get_leaderboard(limit)

    def get_rank(self, user_id: int) -> int:
        """
        Get user's rank on leaderboard.

        Args:
            user_id: User ID

        Returns:
            Rank (1-indexed)
        """
        return self.db.get_user_rank(user_id)

    async def get_hottest_debate(
        self,
        bot: "OthmanBot",
        forum_id: int
    ) -> Optional[HotDebate]:
        """
        Get the hottest debate from a forum based on activity and karma.

        Args:
            bot: The OthmanBot instance
            forum_id: Discord forum channel ID

        Returns:
            HotDebate object or None if no threads found

        DESIGN: Calculates hotness score based on:
        - Recent activity (replies in last 24 hours)
        - Total karma (net upvotes - downvotes)
        - Total reply count
        Formula: (recent_replies * 2) + (karma * 0.5) + (total_replies * 0.1)
        """
        try:
            forum = bot.get_channel(forum_id)
            if not forum or not isinstance(forum, discord.ForumChannel):
                logger.warning("Forum Not Found Or Invalid", [
                    ("Forum ID", str(forum_id)),
                ])
                return None

            # Get all active threads
            threads = forum.threads
            if not threads:
                logger.info("No threads found in debates forum")
                return None

            hot_debates: list[HotDebate] = []
            cutoff_time = datetime.now(NY_TZ) - timedelta(hours=24)

            for thread in threads:
                if thread.archived:
                    continue

                # Fetch thread messages to count replies and calculate karma
                try:
                    # Get message count (subtract 1 for starter message)
                    reply_count = max(0, thread.message_count - 1) if thread.message_count else 0

                    # Calculate recent activity by fetching recent messages
                    recent_replies = 0
                    total_karma = 0
                    top_contributor: Optional[tuple[int, str, int]] = None  # (user_id, name, karma)

                    async for message in thread.history(limit=None):
                        # Discord message times are UTC-aware, convert for comparison
                        msg_time = message.created_at.astimezone(NY_TZ)
                        if msg_time > cutoff_time:
                            recent_replies += 1

                        # Calculate message karma from reactions
                        message_karma = 0
                        for reaction in message.reactions:
                            if str(reaction.emoji) == "⬆️":
                                message_karma += reaction.count
                            elif str(reaction.emoji) == "⬇️":
                                message_karma -= reaction.count

                        total_karma += message_karma

                        # Track top contributor (exclude thread starter)
                        if message.id != thread.id and message_karma > 0:
                            if not top_contributor or message_karma > top_contributor[2]:
                                top_contributor = (
                                    message.author.id,
                                    message.author.display_name,
                                    message_karma
                                )

                    # Calculate hotness score
                    hotness = (recent_replies * 2) + (total_karma * 0.5) + (reply_count * 0.1)

                    hot_debates.append(HotDebate(
                        thread=thread,
                        reply_count=reply_count,
                        karma=total_karma,
                        hotness_score=hotness,
                        top_contributor_id=top_contributor[0] if top_contributor else None,
                        top_contributor_name=top_contributor[1] if top_contributor else "N/A"
                    ))

                except Exception as e:
                    logger.warning("Failed To Analyze Thread", [
                        ("Thread ID", str(thread.id)),
                        ("Error", str(e)),
                    ])
                    continue

            if not hot_debates:
                logger.info("No active debates found")
                return None

            # Sort by hotness score and return the hottest
            hot_debates.sort(key=lambda x: x.hotness_score, reverse=True)
            return hot_debates[0]

        except Exception as e:
            logger.error("Failed To Get Hottest Debate", [
                ("Error", str(e)),
            ])
            return None


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DebatesService", "HotDebate"]
