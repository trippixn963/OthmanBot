"""
OthmanBot - Debate Tags Configuration
=====================================

Debate forum tag definitions and AI-powered auto-tagging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
import os
from typing import List

from openai import OpenAI

from src.core.logger import logger
from src.core.config import DEBATE_TAGS

# Tag descriptions for AI classification
TAG_DESCRIPTIONS = {
    "politics": "Political topics including Democracy, Middle East, Syria, Governance, Secularism",
    "social": "Social issues including LGBT, Gender, Rights, Culture, Family",
    "science": "Scientific topics, research, technology, health",
    "philosophy": "Philosophy, Ethics, Moral discussions, Logical arguments",
    "history": "Historical events, debates, and discussions",
    "sports": "Sports-related topics and discussions",
}


# =============================================================================
# AI-Powered Tag Detection
# =============================================================================

async def detect_debate_tags(title: str, description: str = "") -> List[int]:
    """
    Use AI to detect appropriate tags for a debate thread.

    Args:
        title: The debate thread title
        description: Optional description/initial post content

    Returns:
        List of Discord tag IDs (1-2 tags maximum)

    DESIGN:
    - Uses OpenAI to analyze the debate content
    - Returns 1-2 most relevant tags
    - Never includes "hot" tag (that's added dynamically based on activity)
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY Not Found", [
                ("Feature", "Tag detection"),
                ("Action", "Returning empty tags"),
            ])
            return []

        client = OpenAI(api_key=api_key, timeout=30.0)

        # Build the tag options for the AI
        tag_options = "\n".join([
            f"- {name}: {desc}"
            for name, desc in TAG_DESCRIPTIONS.items()
        ])

        # Combine title and description for analysis
        content = f"Title: {title}"
        if description:
            content += f"\n\nDescription: {description[:500]}"  # Limit description length

        prompt = f"""Analyze this debate topic and select 1-2 most relevant tags from the list below.

Debate content:
{content}

Available tags:
{tag_options}

Instructions:
- Select ONLY 1-2 tags that are most relevant
- Return ONLY the tag names, comma-separated
- Do not include any explanation or additional text
- Example response: "religion, politics" or "philosophy"

Tags:"""

        # Run OpenAI call in thread pool to avoid blocking the event loop
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a debate topic classifier. Return only tag names, comma-separated, no explanation."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=50,
            temperature=0.3
        )

        # Parse the response
        tag_names_str = response.choices[0].message.content.strip().lower()
        tag_names = [name.strip() for name in tag_names_str.split(",")]

        # Convert tag names to Discord tag IDs
        tag_ids = []
        for name in tag_names:
            if name in DEBATE_TAGS and name != "hot":  # Never auto-add "hot" tag
                tag_ids.append(DEBATE_TAGS[name])

        # Limit to 2 tags maximum
        tag_ids = tag_ids[:2]

        logger.info("AI Detected Tags", [
            ("Title", title[:50]),
            ("Tags", ", ".join(tag_names)),
            ("IDs", str(tag_ids)),
        ])
        return tag_ids

    except Exception as e:
        logger.error("Failed To Detect Debate Tags", [
            ("Error", str(e)),
        ])
        return []


# =============================================================================
# Religion Debate Detection
# =============================================================================

# Prompt tuned for Syrian dialect (same approach as AzabBot)
RELIGION_DETECTION_PROMPT = """You detect if a debate topic is PRIMARILY about religion.

CRITICAL: Syrian/Arabic uses religious words casually. These are NOT religious debates:
- "والله", "يا الله", "الله يلعنك" = casual expressions
- "يلعن دينك" = common curse, NOT theological
- Questions about people's behavior = NOT religious
- Historical/political topics involving religious groups = NOT religious
- Jokes, regional banter = NOT religious

ONLY flag as religious debate if the PRIMARY PURPOSE is:
- Debating existence of God/gods or theological claims
- Comparing religions ("Islam vs Christianity")
- Attacking religious figures/prophets theologically
- Sectarian debates ("Sunnis vs Shias are wrong because...")
- Proselytizing or quoting scripture to prove religious points
- "Is [religion] true/false?" type debates

If ambiguous or could be casual/political/historical, answer NO.
Respond with ONLY: {"religious": true/false, "reason": "brief explanation"}"""


async def is_religion_debate(title: str, description: str = "") -> bool:
    """
    Use AI to detect if a debate is primarily about religion.

    Args:
        title: The debate thread title
        description: Optional description/initial post content

    Returns:
        True if the debate is primarily religious in nature

    DESIGN:
    - Uses same prompt approach as AzabBot content moderation
    - Tuned for Syrian dialect to avoid false positives
    - Returns False on errors (fail-open)
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY Not Found", [
                ("Feature", "Religion detection"),
                ("Action", "Allowing debate (fail-open)"),
            ])
            return False

        client = OpenAI(api_key=api_key, timeout=30.0)

        content = f"Title: {title}"
        if description:
            content += f"\nDescription: {description[:500]}"

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": RELIGION_DETECTION_PROMPT},
                {"role": "user", "content": f"Debate topic:\n{content}"}
            ],
            max_tokens=100,
            temperature=0.1
        )

        response_text = response.choices[0].message.content.strip()

        # Parse JSON response
        try:
            # Handle potential markdown wrapping
            json_text = response_text
            if json_text.startswith("```"):
                parts = json_text.split("```")
                if len(parts) >= 2:
                    json_text = parts[1]
                    if json_text.startswith("json"):
                        json_text = json_text[4:]
                    json_text = json_text.strip()

            result = json.loads(json_text)
            is_religious = result.get("religious", False)
            reason = result.get("reason", "No reason")
        except json.JSONDecodeError:
            # Fallback: check for "true" in response
            is_religious = '"religious": true' in response_text.lower() or '"religious":true' in response_text.lower()
            reason = response_text[:50]

        logger.info("Religion Detection Result", [
            ("Title", title[:50]),
            ("Is Religious", str(is_religious)),
            ("Reason", reason[:50]),
        ])

        return is_religious

    except Exception as e:
        logger.error("Failed To Detect Religion Debate", [
            ("Error", str(e)),
            ("Action", "Allowing debate (fail-open)"),
        ])
        return False


# =============================================================================
# Hot Tag Management (Daily Evaluation at Midnight EST)
# =============================================================================

# Hot tag thresholds
HOT_MIN_MESSAGES: int = 50
"""Minimum messages required to be considered hot."""

HOT_MAX_INACTIVITY_HOURS: float = 24.0
"""Maximum hours since last message to keep hot tag (1 day)."""


def should_have_hot_tag(message_count: int, hours_since_last_message: float) -> bool:
    """
    Determine if a debate thread should have the "Hot" tag.

    Evaluated once daily at midnight EST. A thread is "hot" if:
    1. It has at least HOT_MIN_MESSAGES (50) messages
    2. It had activity within the last 24 hours

    Args:
        message_count: Total messages in the thread
        hours_since_last_message: Hours since last activity

    Returns:
        True if thread deserves the "Hot" tag

    DESIGN:
    - Simple criteria: high message count + active within last day
    - Evaluated daily at midnight to prevent notification spam
    - 50 messages is a meaningful threshold for engagement
    - 24 hour window ensures any activity that day counts
    - Thread keeps hot tag if it had activity since last midnight
    """
    has_enough_messages = message_count >= HOT_MIN_MESSAGES
    is_recently_active = hours_since_last_message <= HOT_MAX_INACTIVITY_HOURS

    return has_enough_messages and is_recently_active


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DEBATE_TAGS",
    "TAG_DESCRIPTIONS",
    "detect_debate_tags",
    "is_religion_debate",
    "should_have_hot_tag",
    "HOT_MIN_MESSAGES",
    "HOT_MAX_INACTIVITY_HOURS",
]
