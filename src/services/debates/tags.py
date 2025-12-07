"""
Othman Discord Bot - Debate Tags Configuration
===============================================

Debate forum tag definitions and AI-powered auto-tagging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
from typing import List

from openai import OpenAI

from src.core.logger import logger
from src.core.config import DEBATE_TAGS

# Tag descriptions for AI classification
TAG_DESCRIPTIONS = {
    "religion": "Religious topics including Islam, Christianity, Atheism, Theology, Sectarianism",
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
            logger.error("OPENAI_API_KEY not found - cannot detect tags")
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
# Hot Tag Management
# =============================================================================

def should_add_hot_tag(message_count: int, time_elapsed_hours: float) -> bool:
    """
    Determine if a debate thread should get the "Hot" tag.

    Args:
        message_count: Number of messages in the thread
        time_elapsed_hours: Hours since thread creation

    Returns:
        True if thread is "hot" (high activity)

    DESIGN:
    - "Hot" criteria: >= 10 messages in first hour, or >= 20 messages in first 6 hours
    - Encourages active, engaging debates
    """
    if time_elapsed_hours < 1:
        return message_count >= 10
    elif time_elapsed_hours < 6:
        return message_count >= 20
    elif time_elapsed_hours < 24:
        return message_count >= 40
    else:
        return message_count >= 100


def should_remove_hot_tag(message_count: int, hours_since_last_message: float) -> bool:
    """
    Determine if a debate thread should lose the "Hot" tag.

    Args:
        message_count: Total messages in the thread
        hours_since_last_message: Hours since last activity

    Returns:
        True if thread is no longer "hot"

    DESIGN:
    - Remove "Hot" if no activity for 6+ hours
    - Keeps the tag fresh and relevant
    """
    return hours_since_last_message >= 6


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DEBATE_TAGS",
    "TAG_DESCRIPTIONS",
    "detect_debate_tags",
    "should_add_hot_tag",
    "should_remove_hot_tag",
]
