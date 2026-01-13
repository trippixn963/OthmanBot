"""
OthmanBot - Stats API Constants
===============================

Configuration constants for the stats API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os

# API server configuration
STATS_API_PORT = 8085
STATS_API_HOST = "0.0.0.0"

# Cache duration in seconds
CACHE_TTL = 30

# Bot home directory (for git log)
BOT_HOME = os.environ.get("BOT_HOME", "/root/OthmanBot")

# Tier thresholds for karma
TIER_THRESHOLDS = {
    "diamond": 500,
    "gold": 250,
    "silver": 100,
    "bronze": 50,
}


def get_tier(karma: int) -> str | None:
    """Get tier based on karma thresholds."""
    if karma >= TIER_THRESHOLDS["diamond"]:
        return "diamond"
    elif karma >= TIER_THRESHOLDS["gold"]:
        return "gold"
    elif karma >= TIER_THRESHOLDS["silver"]:
        return "silver"
    elif karma >= TIER_THRESHOLDS["bronze"]:
        return "bronze"
    return None


__all__ = [
    "STATS_API_PORT",
    "STATS_API_HOST",
    "CACHE_TTL",
    "BOT_HOME",
    "TIER_THRESHOLDS",
    "get_tier",
]
