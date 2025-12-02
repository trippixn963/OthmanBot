"""
Othman Discord Bot - Configuration Module
==========================================

Channel ID loading and environment configuration helpers.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
from typing import Optional

from src.core.logger import logger


# =============================================================================
# Discord Server/Guild IDs
# =============================================================================

SYRIA_GUILD_ID: int = 1228455909827805308


# =============================================================================
# Discord Role IDs
# =============================================================================

MODERATOR_ROLE_ID: int = 1445008687038075001
DEVELOPER_ID: int = 259725211664908288


# =============================================================================
# Discord Channel/Forum IDs
# =============================================================================

DEBATES_FORUM_ID: int = 1391070464406978701


# =============================================================================
# News Forum Tag IDs
# =============================================================================

NEWS_FORUM_TAGS: dict[str, int] = {
    "military": 1382114547996954664,
    "breaking_news": 1382114954165092565,
    "politics": 1382115092077871174,
    "economy": 1382115132317892619,
    "health": 1382115182184235088,
    "international": 1382115248814690354,
    "social": 1382115306842882118,
}


# =============================================================================
# Soccer Forum Tag IDs
# =============================================================================

SOCCER_TEAM_TAG_IDS: dict[str, int] = {
    "Barcelona": 1440030683992031282,
    "Real Madrid": 1440030713498828860,
    "Atletico Madrid": 1440030801508176014,
    "Liverpool": 1440030822496473189,
    "Bayern Munich": 1440030846416588861,
    "Manchester City": 1440030866452648057,
    "Manchester United": 1440030888128675881,
    "Arsenal": 1440030901512966185,
    "Chelsea": 1440030915182198866,
    "Paris Saint-Germain": 1440030936254255164,
    "Juventus": 1440030956806471752,
    "AC Milan": 1440030976288755937,
    "Inter Milan": 1440030992701198377,
    "Napoli": 1440031006236344595,
    "Borussia Dortmund": 1440031046069518448,
    "Roma": 1440031084845858928,
    "Tottenham Hotspur": 1440031117016043614,
    "International": 1440031141884334311,
    "Champions League": 1440031161094242365,
}


# =============================================================================
# Debates Forum Tag IDs
# =============================================================================

DEBATE_TAGS: dict[str, int] = {
    "religion": 1392215942519586816,
    "politics": 1392215786067857519,
    "social": 1392216048648060970,
    "science": 1392216005819764777,
    "philosophy": 1392216091068993666,
    "history": 1392216143149797568,
    "sports": 1411304663193620580,
    "hot": 1392216232614166639,
}


# =============================================================================
# Channel ID Loading
# =============================================================================

def load_channel_id(env_var: str, name: str) -> Optional[int]:
    """
    Load a channel ID from environment variable.

    Args:
        env_var: Environment variable name
        name: Human-readable channel name for logging

    Returns:
        Channel ID as int or None if not configured

    DESIGN: Centralized channel ID loading with validation
    Validates that channel ID is numeric before converting
    Returns None if not configured (allows optional channels)
    """
    channel_id_str: Optional[str] = os.getenv(env_var)
    if channel_id_str and channel_id_str.isdigit():
        return int(channel_id_str)
    return None


def load_news_channel_id() -> Optional[int]:
    """Load news channel ID from NEWS_CHANNEL_ID."""
    return load_channel_id("NEWS_CHANNEL_ID", "news")


def load_soccer_channel_id() -> Optional[int]:
    """Load soccer channel ID from SOCCER_CHANNEL_ID."""
    return load_channel_id("SOCCER_CHANNEL_ID", "soccer")


def load_gaming_channel_id() -> Optional[int]:
    """Load gaming channel ID from GAMING_CHANNEL_ID."""
    return load_channel_id("GAMING_CHANNEL_ID", "gaming")


def load_general_channel_id() -> Optional[int]:
    """Load general channel ID from GENERAL_CHANNEL_ID."""
    return load_channel_id("GENERAL_CHANNEL_ID", "general")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "SYRIA_GUILD_ID",
    "MODERATOR_ROLE_ID",
    "DEVELOPER_ID",
    "DEBATES_FORUM_ID",
    "NEWS_FORUM_TAGS",
    "SOCCER_TEAM_TAG_IDS",
    "DEBATE_TAGS",
    "load_channel_id",
    "load_news_channel_id",
    "load_soccer_channel_id",
    "load_gaming_channel_id",
    "load_general_channel_id",
]
