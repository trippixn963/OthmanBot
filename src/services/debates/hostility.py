"""
Othman Discord Bot - Hostility Detection Service
=================================================

Cost-efficient hostility tracking for debate threads.
Uses keyword pre-filtering + batch AI analysis.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import discord
from openai import OpenAI

from src.core.logger import logger
from src.core.config import MODERATOR_ROLE_ID
from src.utils import get_developer_avatar, send_message_with_retry, edit_thread_with_retry


# =============================================================================
# Constants
# =============================================================================

# Thresholds
WARNING_THRESHOLD = 70.0  # Percentage for warning
CRITICAL_THRESHOLD = 90.0  # Percentage for auto-lock
COOLDOWN_MINUTES = 30  # Min time between warnings

# Batch settings
BATCH_SIZE = 5  # Messages before AI analysis
MIN_MESSAGE_LENGTH = 10  # Only skip very short messages (ok, yes, etc.)

# Score settings
SCORE_DECAY_RATE = 0.95  # Decay per hour
BASE_INCREMENT = 0.0  # Non-hostile messages don't increase meter
KEYWORD_INCREMENT = 3.0  # Score increment for keyword matches

# Hostile keyword patterns (regex)
HOSTILE_PATTERNS = {
    "severe": [
        r"\b(kys|kill yourself|neck yourself)\b",
        r"\b(n[i1]gg[e3]r|f[a4]gg[o0]t|r[e3]t[a4]rd)\b",
        r"\b(die|death to|murder)\b",
    ],
    "high": [
        r"\b(idiot|stupid|dumb|moron|imbecile)\b",
        r"\b(stfu|shut up|shut the fuck)\b",
        r"\b(piece of shit|pos|trash human)\b",
        r"\b(hate you|despise you|loser)\b",
        r"\b(fuck|fucking|fucked|shit|bitch)\b",  # Explicit profanity
        r"\b(dumbass|asshole|dickhead)\b",  # Personal insults
    ],
    "medium": [
        r"\b(wrong|liar|lying|pathetic|clown)\b",
        r"!{3,}|\?{3,}",  # Excessive punctuation (3+ ! or ?)
    ],
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class QueuedMessage:
    """A message queued for batch analysis."""
    message_id: int
    thread_id: int
    user_id: int
    content: str
    timestamp: datetime


@dataclass
class ThreadHostility:
    """Hostility data for a thread."""
    thread_id: int
    cumulative_score: float = 0.0
    message_count: int = 0
    warning_sent: bool = False
    last_warning_at: Optional[datetime] = None
    locked_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=datetime.now)
    last_reported_bucket: int = 0  # Last 10% bucket that was reported (0, 10, 20, etc.)


# =============================================================================
# Hostility Tracker Class
# =============================================================================

class HostilityTracker:
    """
    Cost-efficient hostility tracking for debate threads.

    Uses a multi-tier approach:
    1. Skip rules (bots, short messages, moderators)
    2. Keyword pre-filtering (local regex)
    3. Batch AI analysis (every N messages)
    """

    def __init__(self, database: Any) -> None:
        """
        Initialize hostility tracker.

        Args:
            database: DebatesDatabase instance
        """
        self.db = database
        self.openai_client: Optional[OpenAI] = None
        self._init_openai()

        # In-memory state with bounded size
        self.queues: Dict[int, List[QueuedMessage]] = {}  # thread_id -> messages
        self.thread_scores: Dict[int, ThreadHostility] = {}  # thread_id -> hostility

        # Cache limits to prevent memory leaks
        self._MAX_CACHED_THREADS = 100

        logger.info("🔥 Hostility Tracker Initialized")

    def _init_openai(self) -> None:
        """Initialize OpenAI client."""
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.openai_client = OpenAI(api_key=api_key, timeout=30.0)
            logger.info("🤖 OpenAI Client Initialized For Hostility Detection")
        else:
            logger.warning("🤖 OPENAI_API_KEY Not Set - Hostility AI Analysis Disabled")

    def _cleanup_caches(self) -> None:
        """Remove oldest entries from caches to prevent memory leaks."""
        # Cleanup thread_scores if over limit
        if len(self.thread_scores) > self._MAX_CACHED_THREADS:
            # Sort by updated_at and remove oldest (use list() to avoid dict modification during iteration)
            sorted_threads = sorted(
                list(self.thread_scores.items()),
                key=lambda x: x[1].updated_at
            )
            # Remove oldest 20%
            to_remove = len(self.thread_scores) - int(self._MAX_CACHED_THREADS * 0.8)
            for thread_id, _ in sorted_threads[:to_remove]:
                del self.thread_scores[thread_id]
                # Also clean up empty queues
                if thread_id in self.queues and not self.queues[thread_id]:
                    del self.queues[thread_id]

            logger.debug("🧹 Cleaned Hostility Caches", [
                ("Removed", str(to_remove)),
                ("Remaining", str(len(self.thread_scores))),
            ])

    # -------------------------------------------------------------------------
    # Main Entry Point
    # -------------------------------------------------------------------------

    async def process_message(
        self,
        message: discord.Message,
        bot: Any
    ) -> Optional[float]:
        """
        Process a message for hostility detection.

        Args:
            message: Discord message to analyze
            bot: Bot instance for sending messages

        Returns:
            Current thread hostility score, or None if skipped
        """
        thread = message.channel
        thread_id = thread.id

        # Step 1: Skip checks
        if self._should_skip(message):
            return None

        # Step 2: Ensure thread state exists
        if thread_id not in self.thread_scores:
            self.thread_scores[thread_id] = self._load_thread_hostility(thread_id)

        # Step 3: Keyword pre-filter
        severity, keyword_score = self._keyword_filter(message.content)

        # Step 4: Queue or immediate score
        if severity in ("severe", "high"):
            # High severity - queue for batch analysis
            await self._queue_message(message, severity)

            # Check if batch is ready
            if len(self.queues.get(thread_id, [])) >= BATCH_SIZE:
                await self._analyze_batch(thread_id)
        elif severity == "medium":
            # Medium - add to queue but smaller score increment
            await self._queue_message(message, severity)
        else:
            # No keywords - small base increment
            self._add_score(thread_id, message.id, message.author.id, BASE_INCREMENT)

        # Step 5: Apply decay
        self._apply_decay(thread_id)

        # Step 6: Get current score and check thresholds
        current_score = self.thread_scores[thread_id].cumulative_score

        # Step 7: Check if we crossed a 10% bucket and send meter update
        await self._check_bucket_update(thread, current_score, bot)

        # Step 8: Check thresholds and take action (warning at 70%, lock at 90%)
        await self._check_thresholds(thread, current_score, bot)

        # Step 9: Clean up caches to prevent memory leaks
        self._cleanup_caches()

        return current_score

    # -------------------------------------------------------------------------
    # Skip Rules
    # -------------------------------------------------------------------------

    def _should_skip(self, message: discord.Message) -> bool:
        """
        Determine if message should be skipped.

        Returns:
            True if message should be skipped
        """
        # Skip bot messages
        if message.author.bot:
            return True

        # Skip moderators
        if hasattr(message.author, 'roles'):
            if any(role.id == MODERATOR_ROLE_ID for role in message.author.roles):
                return True

        # For short messages, only skip if NO hostile keywords detected
        # This ensures short insults like "idiot", "kys" are still caught
        if len(message.content) < MIN_MESSAGE_LENGTH:
            severity, _ = self._keyword_filter(message.content)
            if severity == "none":
                return True  # Short and no keywords - skip

        return False

    # -------------------------------------------------------------------------
    # Keyword Pre-Filter
    # -------------------------------------------------------------------------

    def _keyword_filter(self, content: str) -> tuple[str, float]:
        """
        Check content for hostile keywords.

        Args:
            content: Message content

        Returns:
            (severity, score) tuple
        """
        content_lower = content.lower()

        # Check severe patterns
        for pattern in HOSTILE_PATTERNS["severe"]:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return ("severe", 12.0)  # ~9 severe messages to hit 100%

        # Check high patterns
        for pattern in HOSTILE_PATTERNS["high"]:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return ("high", 6.0)  # ~17 high messages to hit 100%

        # Check medium patterns
        medium_count = 0
        for pattern in HOSTILE_PATTERNS["medium"]:
            if re.search(pattern, content_lower, re.IGNORECASE):
                medium_count += 1

        if medium_count >= 2:
            return ("medium", 4.0)  # ~25 medium messages to hit 100%
        elif medium_count == 1:
            return ("low", 2.0)

        # Check caps ratio (yelling)
        if len(content) > 20:
            caps_ratio = sum(1 for c in content if c.isupper()) / len(content)
            if caps_ratio > 0.5:
                return ("medium", 3.0)

        return ("none", 0.0)

    # -------------------------------------------------------------------------
    # Message Queueing
    # -------------------------------------------------------------------------

    async def _queue_message(self, message: discord.Message, severity: str) -> None:
        """
        Add message to batch queue.

        Args:
            message: Discord message
            severity: Detected severity level
        """
        thread_id = message.channel.id

        if thread_id not in self.queues:
            self.queues[thread_id] = []

        queued = QueuedMessage(
            message_id=message.id,
            thread_id=thread_id,
            user_id=message.author.id,
            content=message.content[:500],  # Truncate for token efficiency
            timestamp=datetime.now()
        )

        self.queues[thread_id].append(queued)

        # Add keyword-based score immediately (AI will adjust later)
        _, keyword_score = self._keyword_filter(message.content)
        self._add_score(thread_id, message.id, message.author.id, keyword_score)

        logger.debug("🔥 Queued Message For Hostility Analysis", [
            ("Message ID", str(message.id)),
            ("Severity", severity),
        ])

    # -------------------------------------------------------------------------
    # Batch AI Analysis
    # -------------------------------------------------------------------------

    async def _analyze_batch(self, thread_id: int) -> Dict[int, float]:
        """
        Analyze queued messages using AI.

        Args:
            thread_id: Thread ID to analyze

        Returns:
            Dict mapping message_id to hostility score (0-1)
        """
        if not self.openai_client:
            logger.warning("🤖 OpenAI Client Not Available - Skipping Batch Analysis")
            self.queues[thread_id] = []
            return {}

        queue = self.queues.get(thread_id, [])
        if not queue:
            return {}

        # Build batch prompt
        messages_text = "\n".join([
            f"[MSG_{i}]: {msg.content}"
            for i, msg in enumerate(queue)
        ])

        prompt = f"""Analyze these debate messages for hostility/toxicity.

Messages:
{messages_text}

For each message, provide a hostility score (0.0 to 1.0):
- 0.0-0.3: Normal debate, respectful disagreement
- 0.4-0.6: Dismissive, rude, or condescending
- 0.7-0.8: Personal attacks, insults
- 0.9-1.0: Hate speech, threats, severe hostility

IMPORTANT: Strong disagreement is NOT hostility. Only flag genuine attacks on people.

Output JSON only: {{"MSG_0": 0.2, "MSG_1": 0.7}}"""

        try:
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a content moderation assistant. Output only valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.1
            )

            result_text = response.choices[0].message.content.strip()
            scores = json.loads(result_text)

            # Apply AI scores to thread
            for key, ai_score in scores.items():
                # Validate key format
                if not isinstance(key, str) or not key.startswith("MSG_"):
                    logger.warning("🔥 Invalid AI Response Key", [
                        ("Key", str(key)),
                    ])
                    continue

                try:
                    idx = int(key.split("_")[1])
                except (ValueError, IndexError):
                    logger.warning("🔥 Invalid AI Response Key Format", [
                        ("Key", str(key)),
                    ])
                    continue

                if idx < 0 or idx >= len(queue):
                    continue

                # Validate AI score is a number and clamp to 0-1 range
                try:
                    ai_score = float(ai_score)
                except (TypeError, ValueError):
                    logger.warning("🔥 Invalid AI Score Value", [
                        ("Key", key),
                        ("Value", str(ai_score)),
                    ])
                    continue

                # Clamp to valid range (0.0 to 1.0)
                ai_score = max(0.0, min(1.0, ai_score))

                msg = queue[idx]
                # AI score is 0-1, convert to 0-12 range (matching severe keyword score)
                score_addition = ai_score * 12
                self._add_score(thread_id, msg.message_id, msg.user_id, score_addition)

            logger.info("🔥 Analyzed Hostility Batch", [
                ("Messages", str(len(queue))),
                ("Thread ID", str(thread_id)),
            ])

        except json.JSONDecodeError as e:
            logger.warning("🔥 Failed To Parse AI Response", [
                ("Error", str(e)),
            ])
        except Exception as e:
            logger.error("🔥 Batch Analysis Failed", [
                ("Error", str(e)),
            ])

        # Clear queue
        self.queues[thread_id] = []
        return {}

    # -------------------------------------------------------------------------
    # Score Management
    # -------------------------------------------------------------------------

    def _add_score(
        self,
        thread_id: int,
        message_id: int,
        user_id: int,
        score: float
    ) -> None:
        """
        Add hostility score for a message.

        Args:
            thread_id: Thread ID
            message_id: Message ID
            user_id: User ID
            score: Score to add (0-12 typical range)
        """
        if thread_id not in self.thread_scores:
            self.thread_scores[thread_id] = ThreadHostility(thread_id=thread_id)

        state = self.thread_scores[thread_id]
        state.cumulative_score += score
        state.message_count += 1
        state.updated_at = datetime.now()

        # Clamp to 0-100
        state.cumulative_score = min(100.0, max(0.0, state.cumulative_score))

        # Persist thread hostility to database
        self.db.update_thread_hostility(
            thread_id=thread_id,
            cumulative_score=state.cumulative_score,
            message_count=state.message_count
        )

        # Log individual message hostility for tracking top contributors
        if score > 0:
            self.db.add_message_hostility(
                thread_id=thread_id,
                message_id=message_id,
                user_id=user_id,
                score=score
            )

        logger.debug("🔥 Thread Hostility Updated", [
            ("Thread ID", str(thread_id)),
            ("Score", f"{state.cumulative_score:.1f}%"),
            ("User", str(user_id)),
            ("Added", f"{score:.1f}"),
        ])

    def _apply_decay(self, thread_id: int) -> None:
        """
        Apply time-based decay to hostility score.

        Args:
            thread_id: Thread ID
        """
        if thread_id not in self.thread_scores:
            return

        state = self.thread_scores[thread_id]
        hours_elapsed = (datetime.now() - state.updated_at).total_seconds() / 3600

        if hours_elapsed > 0.1:  # Only decay if > 6 minutes
            decay_factor = SCORE_DECAY_RATE ** hours_elapsed
            state.cumulative_score *= decay_factor
            state.cumulative_score = max(0.0, state.cumulative_score)

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from string or return as-is if already datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return datetime.now()
        return datetime.now()

    def _load_thread_hostility(self, thread_id: int) -> ThreadHostility:
        """
        Load thread hostility from database.

        Args:
            thread_id: Thread ID

        Returns:
            ThreadHostility object
        """
        data = self.db.get_thread_hostility(thread_id)
        if data:
            return ThreadHostility(
                thread_id=thread_id,
                cumulative_score=data.get("cumulative_score", 0.0),
                message_count=data.get("message_count", 0),
                warning_sent=data.get("warning_sent", False),
                last_warning_at=self._parse_datetime(data.get("last_warning_at")),
                locked_at=self._parse_datetime(data.get("locked_at")),
                updated_at=self._parse_datetime(data.get("updated_at")) or datetime.now()
            )
        return ThreadHostility(thread_id=thread_id)

    # -------------------------------------------------------------------------
    # Bucket Updates (10% increments)
    # -------------------------------------------------------------------------

    async def _check_bucket_update(
        self,
        thread: discord.Thread,
        score: float,
        bot: Any
    ) -> None:
        """
        Check if score crossed a new 10% bucket and send meter update.

        Args:
            thread: Discord thread
            score: Current hostility score
            bot: Bot instance for avatar
        """
        thread_id = thread.id
        state = self.thread_scores.get(thread_id)
        if not state:
            return

        # Calculate current bucket (0, 10, 20, ..., 100)
        current_bucket = int(score // 10) * 10

        # Only send if we've crossed into a new bucket (and bucket > 0)
        if current_bucket > state.last_reported_bucket and current_bucket > 0:
            await self._send_meter_update(thread, score, bot)
            state.last_reported_bucket = current_bucket

    async def _send_meter_update(
        self,
        thread: discord.Thread,
        score: float,
        bot: Any
    ) -> None:
        """
        Send hostility meter update to thread.

        Args:
            thread: Discord thread
            score: Current hostility score
            bot: Bot instance for avatar
        """
        meter = generate_hostility_meter(score)

        # Get top hostile user
        top_hostile_user_id = self.db.get_top_hostile_user(thread.id)

        # Choose message based on severity
        if score >= 60:
            description = f"Things are heating up! Please keep it civil."
        elif score >= 40:
            description = f"The debate is getting intense."
        else:
            description = f"Debate activity update."

        # Add top hostile user mention
        if top_hostile_user_id:
            description += f"\n\n**Top contributor:** <@{top_hostile_user_id}>"

        embed = discord.Embed(
            title="Hostility Meter",
            description=f"{meter} **{score:.0f}%**\n\n{description}",
            color=discord.Color.gold() if score < 60 else discord.Color.orange()
        )

        # Add standard footer
        developer_avatar_url = await get_developer_avatar(bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        try:
            await send_message_with_retry(thread, embed=embed)
            logger.info("🔥 Sent Hostility Meter Update", [
                ("Thread ID", str(thread.id)),
                ("Score", f"{score:.0f}%"),
            ])
        except discord.HTTPException as e:
            logger.error("🔥 Failed To Send Meter Update", [
                ("Error", str(e)),
            ])

    # -------------------------------------------------------------------------
    # Threshold Actions
    # -------------------------------------------------------------------------

    async def _check_thresholds(
        self,
        thread: discord.Thread,
        score: float,
        bot: Any
    ) -> None:
        """
        Check score against thresholds and take action.

        Args:
            thread: Discord thread
            score: Current hostility score
            bot: Bot instance
        """
        thread_id = thread.id
        state = self.thread_scores.get(thread_id)
        if not state:
            return

        # Check if already locked
        if state.locked_at:
            return

        # Critical threshold - auto-lock
        if score >= CRITICAL_THRESHOLD:
            await self._auto_lock_thread(thread, score, bot)
            return

        # Warning threshold
        if score >= WARNING_THRESHOLD:
            # Check cooldown
            if state.last_warning_at:
                elapsed = (datetime.now() - state.last_warning_at).total_seconds() / 60
                if elapsed < COOLDOWN_MINUTES:
                    return  # Still in cooldown

            await self._send_warning(thread, score, bot)

    async def _send_warning(
        self,
        thread: discord.Thread,
        score: float,
        bot: Any
    ) -> None:
        """
        Send hostility warning to thread.

        Args:
            thread: Discord thread
            score: Current hostility score
            bot: Bot instance
        """
        meter = generate_hostility_meter(score)

        # Get top hostile user
        top_hostile_user_id = self.db.get_top_hostile_user(thread.id)
        top_user_text = f"\n\n**Top contributor:** <@{top_hostile_user_id}>" if top_hostile_user_id else ""

        embed = discord.Embed(
            title="Hostility Warning",
            description=(
                f"{meter} **{score:.0f}%**\n\n"
                f"This debate is getting heated.\n"
                f"Please remain civil or the thread will be auto-locked.\n\n"
                f"At **90%**, this thread will be locked for moderator review."
                f"{top_user_text}"
            ),
            color=discord.Color.orange()
        )

        # Add standard footer
        developer_avatar_url = await get_developer_avatar(bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        try:
            await send_message_with_retry(thread, content="@here", embed=embed)

            # Update state
            state = self.thread_scores[thread.id]
            state.warning_sent = True
            state.last_warning_at = datetime.now()

            # Persist
            self.db.mark_warning_sent(thread.id)

            logger.info("🔥 Sent Hostility Warning", [
                ("Thread ID", str(thread.id)),
                ("Score", f"{score:.0f}%"),
            ])

        except discord.HTTPException as e:
            logger.error("🔥 Failed To Send Warning", [
                ("Error", str(e)),
            ])

    async def _auto_lock_thread(
        self,
        thread: discord.Thread,
        score: float,
        bot: Any
    ) -> None:
        """
        Auto-lock thread due to critical hostility.

        Args:
            thread: Discord thread
            score: Current hostility score
            bot: Bot instance
        """
        meter = generate_hostility_meter(score)

        # Get top hostile user
        top_hostile_user_id = self.db.get_top_hostile_user(thread.id)
        top_user_text = f"\n\n**Top contributor:** <@{top_hostile_user_id}>" if top_hostile_user_id else ""

        embed = discord.Embed(
            title="Thread Locked - Excessive Hostility",
            description=(
                f"{meter} **{score:.0f}%**\n\n"
                f"This thread has been automatically locked due to excessive hostility.\n\n"
                f"A moderator will review this thread."
                f"{top_user_text}"
            ),
            color=discord.Color.red()
        )

        # Add standard footer
        developer_avatar_url = await get_developer_avatar(bot)
        embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar_url)

        try:
            # Send message and ping moderators with rate limit handling
            await send_message_with_retry(
                thread,
                content=f"<@&{MODERATOR_ROLE_ID}>",
                embed=embed
            )

            # Lock thread with rate limit handling
            await edit_thread_with_retry(thread, locked=True)

            # Update state
            state = self.thread_scores[thread.id]
            state.locked_at = datetime.now()

            # Persist
            self.db.mark_thread_locked(thread.id)

            logger.info("🔒 Auto-Locked Thread Due To Hostility", [
                ("Thread ID", str(thread.id)),
                ("Score", f"{score:.0f}%"),
            ])

        except discord.HTTPException as e:
            logger.error("🔒 Failed To Lock Thread", [
                ("Error", str(e)),
            ])

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_thread_score(self, thread_id: int) -> float:
        """
        Get current hostility score for a thread.

        Args:
            thread_id: Thread ID

        Returns:
            Hostility score (0-100)
        """
        if thread_id in self.thread_scores:
            return self.thread_scores[thread_id].cumulative_score

        # Load from database
        data = self.db.get_thread_hostility(thread_id)
        if data:
            return data.get("cumulative_score", 0.0)

        return 0.0


# =============================================================================
# Utility Functions
# =============================================================================

def generate_hostility_meter(score: float) -> str:
    """
    Generate visual hostility meter.

    Args:
        score: Hostility score (0-100)

    Returns:
        Visual meter string like "🟢🟢🟡🔴🔴"
    """
    if score <= 20:
        return "🟢🟢🟢🟢🟢"
    elif score <= 40:
        return "🟢🟢🟢🟢🟡"
    elif score <= 60:
        return "🟢🟢🟢🟡🟡"
    elif score <= 70:
        return "🟢🟢🟡🟡🔴"
    elif score <= 80:
        return "🟢🟡🟡🔴🔴"
    elif score <= 90:
        return "🟡🟡🔴🔴🔴"
    else:
        return "🔴🔴🔴🔴🔴"


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["HostilityTracker", "generate_hostility_meter"]
