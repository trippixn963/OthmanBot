"""
OthmanBot - Debate Analytics
============================

Live-updating analytics for debate threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, List, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from src.bot import OthmanBot
    from src.services.debates.database import DebatesDatabase

from src.core.logger import logger
from src.core.config import NY_TZ, LOG_TITLE_PREVIEW_LENGTH, EmbedColors
from src.core.colors import EmbedIcons
from src.core.emojis import UPVOTE_EMOJI, DOWNVOTE_EMOJI
from src.utils.footer import set_footer

import math

# =============================================================================
# Constants
# =============================================================================

THREAD_HISTORY_TIMEOUT: float = 30.0
"""Maximum seconds to wait when fetching thread history."""


# =============================================================================
# Helper Functions
# =============================================================================

def _calculate_avg_response_time(messages: List[discord.Message]) -> Optional[float]:
    """
    Calculate average time between consecutive messages in minutes.

    Args:
        messages: List of Discord messages (should be non-bot messages)

    Returns:
        Average response time in minutes, or None if not enough messages
    """
    if len(messages) < 2:
        return None

    # Sort messages by creation time (oldest first)
    sorted_msgs = sorted(messages, key=lambda m: m.created_at)

    # Calculate time differences between consecutive messages
    response_times = []
    for i in range(1, len(sorted_msgs)):
        delta = (sorted_msgs[i].created_at - sorted_msgs[i-1].created_at).total_seconds()
        # Only count reasonable response times (< 24 hours) to filter outliers
        if delta < 86400:  # 24 hours in seconds
            response_times.append(delta / 60.0)  # Convert to minutes

    if not response_times:
        return None

    return sum(response_times) / len(response_times)


def _calculate_diversity_score(reply_counts: Dict[int, int]) -> Optional[float]:
    """
    Calculate participation diversity using normalized entropy.

    A diversity score of 1.0 means everyone participates equally.
    A score of 0.0 means one person dominates completely.

    Args:
        reply_counts: Dict mapping user_id to their reply count

    Returns:
        Diversity score between 0 and 1, or None if not enough participants

    DESIGN: Uses Shannon entropy normalized by log(n) where n = participant count.
    This gives us a score between 0-1 regardless of participant count.
    """
    if len(reply_counts) < 2:
        return None

    total = sum(reply_counts.values())
    if total == 0:
        return None

    # Calculate Shannon entropy
    entropy = 0.0
    for count in reply_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    # Normalize by maximum possible entropy (log2 of participant count)
    max_entropy = math.log2(len(reply_counts))
    if max_entropy == 0:
        return None

    return entropy / max_entropy


async def _collect_messages_with_timeout(
    thread: discord.Thread,
    timeout: float = THREAD_HISTORY_TIMEOUT
) -> tuple[List[discord.Message], bool]:
    """
    Collect all messages from a thread with a timeout.

    Args:
        thread: Discord thread to fetch messages from
        timeout: Maximum seconds to wait

    Returns:
        Tuple of (messages, is_complete) where is_complete is False on timeout

    DESIGN: Prevents bot from hanging indefinitely on large threads
    or slow Discord API responses. Returns partial results on timeout.
    """
    messages = []
    is_complete = True
    max_messages = 1000  # Reasonable limit to prevent memory issues
    try:
        async def collect():
            async for message in thread.history(limit=max_messages):
                messages.append(message)
        await asyncio.wait_for(collect(), timeout=timeout)
    except asyncio.TimeoutError:
        is_complete = False
        logger.warning("Thread History Fetch Timed Out", [
            ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
            ("Timeout", f"{timeout}s"),
            ("Messages Collected", str(len(messages))),
            ("Data Complete", "No"),
        ])
    return messages, is_complete


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
        created_at: Optional[datetime] = None,
        top_contributor: Optional[tuple[str, int]] = None,  # (username, reply_count) - legacy
        top_contributors: Optional[List[tuple[int, int]]] = None,  # Top 3: [(user_id, reply_count), ...]
        activity_graph: str = "",
        avg_response_minutes: Optional[float] = None,  # Average time between posts
        diversity_score: Optional[float] = None,  # How evenly distributed participation is (0-1)
    ):
        """
        Initialize debate analytics container.

        Args:
            participants: Number of unique users who participated in the debate.
            total_replies: Total number of replies in the thread.
            total_karma: Sum of all karma earned in this debate.
            last_activity: Timestamp of the most recent message.
            created_at: When the debate thread was created.
            top_contributor: Tuple of (username, reply_count) for top participant (legacy).
            top_contributors: List of top 3 contributors as [(user_id, reply_count), ...].
            activity_graph: ASCII representation of activity over time.
            avg_response_minutes: Average time between consecutive posts in minutes.
            diversity_score: Participation diversity (0-1, higher = more evenly distributed).
        """
        self.participants = participants
        self.total_replies = total_replies
        self.total_karma = total_karma
        self.last_activity = last_activity
        self.created_at = created_at
        self.top_contributor = top_contributor
        self.top_contributors = top_contributors or []
        self.activity_graph = activity_graph
        self.avg_response_minutes = avg_response_minutes
        self.diversity_score = diversity_score


# =============================================================================
# Analytics Calculation
# =============================================================================

async def calculate_debate_analytics(
    thread: discord.Thread,
    database: "DebatesDatabase"
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
        last_activity = datetime.min.replace(tzinfo=NY_TZ)  # Start with oldest possible
        hourly_activity: List[int] = [0] * 5  # Last 5 hours
        total_thread_karma = 0  # Track karma earned from votes in THIS thread

        # Get all messages from the thread (with timeout)
        messages, data_complete = await _collect_messages_with_timeout(thread)
        if not data_complete:
            logger.debug("Analytics Using Partial Data", [
                ("Thread", thread.name[:LOG_TITLE_PREVIEW_LENGTH]),
                ("Messages", str(len(messages))),
            ])
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
                if emoji_str == UPVOTE_EMOJI:
                    async for user in reaction.users():
                        if not user.bot:
                            upvotes += 1
                elif emoji_str == DOWNVOTE_EMOJI:
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
            hours_ago = (datetime.now(NY_TZ) - message.created_at).total_seconds() / 3600
            if hours_ago < 5:
                hour_index = int(hours_ago)
                hourly_activity[hour_index] += 1

        # If no messages found, set last_activity to now
        if last_activity == datetime.min.replace(tzinfo=NY_TZ):
            last_activity = datetime.now(NY_TZ)

        # Find top 3 contributors (by reply count, not including OP's starter message)
        top_contributor = None
        top_contributors: List[tuple[str, int]] = []
        if reply_counts:
            # Sort by reply count descending
            sorted_contributors = sorted(reply_counts.items(), key=lambda x: x[1], reverse=True)[:3]

            # Build user_id -> username mapping from messages
            user_names: Dict[int, str] = {}
            for message in messages:
                if message.author.id not in user_names:
                    user_names[message.author.id] = message.author.display_name

            # Build top contributors list (store user IDs for mention format)
            for user_id, count in sorted_contributors:
                top_contributors.append((user_id, count))

            # Legacy: set top_contributor to the #1 contributor (username format)
            if top_contributors:
                first_user_id, first_count = top_contributors[0]
                username = user_names.get(first_user_id, f"User {first_user_id}")
                top_contributor = (username, first_count)

        # Generate activity graph
        activity_graph = generate_activity_graph(hourly_activity)

        # Calculate quality metrics
        # Filter non-bot messages for response time calculation
        non_bot_messages = [m for m in messages if not m.author.bot]
        avg_response_minutes = _calculate_avg_response_time(non_bot_messages)
        diversity_score = _calculate_diversity_score(reply_counts)

        return DebateAnalytics(
            participants=len(participants),
            total_replies=total_replies,
            total_karma=total_thread_karma,  # Now shows karma earned in THIS thread
            last_activity=last_activity,
            created_at=thread.created_at,
            top_contributor=top_contributor,
            top_contributors=top_contributors,
            activity_graph=activity_graph,
            avg_response_minutes=avg_response_minutes,
            diversity_score=diversity_score,
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
            last_activity=datetime.now(NY_TZ),
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
        color=EmbedColors.INFO,
    )

    # Format created_at as relative time using Discord's timestamp format
    if analytics.created_at:
        created_timestamp = int(analytics.created_at.timestamp())
        created_str = f"<t:{created_timestamp}:R>"
    else:
        created_str = "Unknown"

    # Stats field (compact)
    stats = (
        f"👥 `{analytics.participants}` participants\n"
        f"💬 `{analytics.total_replies}` replies\n"
        f"⬆️ `+{analytics.total_karma}` karma\n"
        f"📅 {created_str}"
    )
    embed.add_field(name="📊 Stats", value=stats, inline=True)

    # Top Contributors field (show top 3 with mentions)
    if analytics.top_contributors:
        medals = ["🥇", "🥈", "🥉"]
        contributor_lines = []
        for i, (user_id, count) in enumerate(analytics.top_contributors[:3]):
            medal = medals[i] if i < len(medals) else "•"
            contributor_lines.append(f"{medal} <@{user_id}> `{count}`")
        embed.add_field(name="🏆 Top Contributors", value="\n".join(contributor_lines), inline=True)

    # Quality metrics field
    quality_lines = []

    # Response time (format nicely)
    if analytics.avg_response_minutes is not None:
        if analytics.avg_response_minutes < 60:
            response_str = f"`{analytics.avg_response_minutes:.0f}m`"
        else:
            hours = analytics.avg_response_minutes / 60
            response_str = f"`{hours:.1f}h`"
        quality_lines.append(f"⏱️ {response_str} avg response")

    # Diversity score (show as percentage with emoji indicator)
    if analytics.diversity_score is not None:
        pct = analytics.diversity_score * 100
        if pct >= 80:
            diversity_emoji = "🟢"
        elif pct >= 50:
            diversity_emoji = "🟡"
        else:
            diversity_emoji = "🔴"
        quality_lines.append(f"{diversity_emoji} `{pct:.0f}%` diversity")

    # Only show quality field if we have metrics
    if quality_lines:
        embed.add_field(name="📈 Quality", value="\n".join(quality_lines), inline=True)

    # Rules field (compact)
    rules = (
        "• Be respectful\n"
        "• No hate speech\n"
        "• Stay on topic\n"
        "• No spam\n\n"
        f"{EmbedIcons.PARTICIPATE} React below to join"
    )
    embed.add_field(name="📜 Rules", value=rules, inline=True)

    # Add standard footer
    set_footer(embed)

    return embed


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DebateAnalytics",
    "calculate_debate_analytics",
    "generate_analytics_embed",
]
