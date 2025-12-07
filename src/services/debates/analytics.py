"""
Othman Discord Bot - Debate Analytics
======================================

Live-updating analytics for debate threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, List, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from src.bot import OthmanBot

from src.core.logger import logger
from src.utils import get_developer_avatar


# =============================================================================
# Constants
# =============================================================================

THREAD_HISTORY_TIMEOUT: float = 30.0
"""Maximum seconds to wait when fetching thread history."""


# =============================================================================
# Helper Functions
# =============================================================================

async def _collect_messages_with_timeout(
    thread: discord.Thread,
    timeout: float = THREAD_HISTORY_TIMEOUT
) -> List[discord.Message]:
    """
    Collect all messages from a thread with a timeout.

    Args:
        thread: Discord thread to fetch messages from
        timeout: Maximum seconds to wait

    Returns:
        List of messages, or empty list on timeout

    DESIGN: Prevents bot from hanging indefinitely on large threads
    or slow Discord API responses. Returns partial results on timeout.
    """
    messages = []
    try:
        async def collect():
            async for message in thread.history(limit=None):
                messages.append(message)
        await asyncio.wait_for(collect(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Thread History Fetch Timed Out", [
            ("Thread", thread.name[:30]),
            ("Timeout", f"{timeout}s"),
            ("Messages Collected", str(len(messages))),
        ])
    return messages


# =============================================================================
# Analytics Data Structures
# =============================================================================

class DebateAnalytics:
    """Container for debate thread statistics."""

    def __init__(
        self,
        participants: int,
        total_replies: int,
        total_karma: int,
        last_activity: datetime,
        top_contributor: Optional[tuple[str, int]] = None,  # (username, reply_count)
        activity_graph: str = "",
    ):
        """
        Initialize debate analytics container.

        Args:
            participants: Number of unique users who participated in the debate.
            total_replies: Total number of replies in the thread.
            total_karma: Sum of all karma earned in this debate.
            last_activity: Timestamp of the most recent message.
            top_contributor: Tuple of (username, reply_count) for top participant.
            activity_graph: ASCII representation of activity over time.
        """
        self.participants = participants
        self.total_replies = total_replies
        self.total_karma = total_karma
        self.last_activity = last_activity
        self.top_contributor = top_contributor
        self.activity_graph = activity_graph


# =============================================================================
# Analytics Calculation
# =============================================================================

async def calculate_debate_analytics(
    thread: discord.Thread,
    database
) -> DebateAnalytics:
    """
    Calculate analytics for a debate thread.

    Args:
        thread: Discord thread object
        database: DebatesDatabase instance

    Returns:
        DebateAnalytics object with calculated statistics
    """
    try:
        # Fetch all messages in the thread with timeout protection
        participants = set()
        reply_counts: Dict[int, int] = {}  # user_id -> count
        total_replies = 0
        last_activity = datetime.min.replace(tzinfo=timezone.utc)  # Start with oldest possible
        hourly_activity: List[int] = [0] * 5  # Last 5 hours
        total_thread_karma = 0  # Track karma earned from votes in THIS thread

        # Get all messages from the thread (with timeout)
        messages = await _collect_messages_with_timeout(thread)
        for message in messages:
            # Skip bot messages (analytics embed)
            if message.author.bot:
                continue

            # Add all human message authors as participants (including OP)
            participants.add(message.author.id)

            # Track last activity from any message
            if message.created_at > last_activity:
                last_activity = message.created_at

            # Count votes (upvotes - downvotes) on this message for thread karma
            upvotes = 0
            downvotes = 0
            for reaction in message.reactions:
                emoji_str = str(reaction.emoji)
                if emoji_str == "\u2b06\ufe0f":  # ⬆️
                    async for user in reaction.users():
                        if not user.bot:
                            upvotes += 1
                elif emoji_str == "\u2b07\ufe0f":  # ⬇️
                    async for user in reaction.users():
                        if not user.bot:
                            downvotes += 1
            total_thread_karma += upvotes - downvotes

            # Skip the original post for reply counting
            if message.id == thread.id:
                continue

            total_replies += 1

            # Count replies per user
            user_id = message.author.id
            reply_counts[user_id] = reply_counts.get(user_id, 0) + 1

            # Calculate hourly activity (for graph)
            hours_ago = (datetime.now(timezone.utc) - message.created_at).total_seconds() / 3600
            if hours_ago < 5:
                hour_index = int(hours_ago)
                hourly_activity[hour_index] += 1

        # If no messages found, set last_activity to now
        if last_activity == datetime.min.replace(tzinfo=timezone.utc):
            last_activity = datetime.now(timezone.utc)

        # Find top contributor (by reply count, not including OP's starter message)
        top_contributor = None
        if reply_counts:
            top_user_id = max(reply_counts, key=reply_counts.get)
            top_reply_count = reply_counts[top_user_id]

            # Get username from already-collected messages (no need to re-fetch)
            for message in messages:
                if message.author.id == top_user_id:
                    top_contributor = (message.author.name, top_reply_count)
                    break

        # Generate activity graph
        activity_graph = generate_activity_graph(hourly_activity)

        return DebateAnalytics(
            participants=len(participants),
            total_replies=total_replies,
            total_karma=total_thread_karma,  # Now shows karma earned in THIS thread
            last_activity=last_activity,
            top_contributor=top_contributor,
            activity_graph=activity_graph,
        )

    except Exception as e:
        logger.error("Failed To Calculate Debate Analytics", [
            ("Error", str(e)),
        ])
        # Return default analytics
        return DebateAnalytics(
            participants=0,
            total_replies=0,
            total_karma=0,
            last_activity=datetime.now(timezone.utc),
            activity_graph="⚪⚪⚪⚪⚪",
        )


def generate_activity_graph(hourly_activity: List[int]) -> str:
    """
    Generate visual activity graph using emoji blocks.

    Args:
        hourly_activity: List of message counts for last 5 hours (recent to oldest)

    Returns:
        String like "🟢🟢🟢🟡⚪" representing activity levels

    DESIGN:
    - 🟢 Green: >= 5 messages
    - 🟡 Yellow: 2-4 messages
    - ⚪ White: 0-1 messages
    """
    if not hourly_activity or sum(hourly_activity) == 0:
        return "⚪⚪⚪⚪⚪"

    graph = ""
    for count in hourly_activity:
        if count >= 5:
            graph += "🟢"
        elif count >= 2:
            graph += "🟡"
        else:
            graph += "⚪"

    return graph


# =============================================================================
# Embed Generation
# =============================================================================

async def generate_analytics_embed(bot: "OthmanBot", analytics: DebateAnalytics) -> discord.Embed:
    """
    Generate Discord embed for debate analytics.

    Args:
        analytics: DebateAnalytics object

    Returns:
        Discord embed with formatted statistics using fields for cleaner layout
    """
    embed = discord.Embed(
        color=discord.Color.orange(),
    )

    # Format last activity as relative time
    now = datetime.now(timezone.utc)
    delta = now - analytics.last_activity

    if delta.total_seconds() < 60:
        last_activity_str = "Just now"
    elif delta.total_seconds() < 3600:
        minutes = int(delta.total_seconds() / 60)
        last_activity_str = f"{minutes}m ago"
    elif delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        last_activity_str = f"{hours}h ago"
    else:
        days = int(delta.total_seconds() / 86400)
        last_activity_str = f"{days}d ago"

    # Stats field (compact)
    stats = (
        f"👥 `{analytics.participants}` participants\n"
        f"💬 `{analytics.total_replies}` replies\n"
        f"⬆️ `+{analytics.total_karma}` karma\n"
        f"⏱️ {last_activity_str}"
    )
    embed.add_field(name="📊 Stats", value=stats, inline=True)

    # Rules field (compact)
    rules = (
        "• Be respectful\n"
        "• No hate speech\n"
        "• Stay on topic\n"
        "• No spam\n\n\n"
        "✅ React below to join"
    )
    embed.add_field(name="📜 Rules", value=rules, inline=True)

    # Add standard footer
    developer_avatar_url = await get_developer_avatar(bot)
    embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

    return embed


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DebateAnalytics",
    "calculate_debate_analytics",
    "generate_analytics_embed",
]
