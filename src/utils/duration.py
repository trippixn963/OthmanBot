"""
OthmanBot - Duration Parsing Utility
====================================

Reusable duration parsing and formatting functions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import timedelta
from typing import Optional


# =============================================================================
# Duration Suggestions for Autocomplete
# =============================================================================

DURATION_SUGGESTIONS = [
    ("1 Hour", "1h"),
    ("6 Hours", "6h"),
    ("12 Hours", "12h"),
    ("1 Day", "1d"),
    ("3 Days", "3d"),
    ("1 Week", "1w"),
    ("2 Weeks", "2w"),
    ("1 Month", "1mo"),
    ("3 Months", "3mo"),
    ("Permanent", "permanent"),
]


# =============================================================================
# Duration Parser
# =============================================================================

def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse a duration string into a timedelta.

    Supported formats:
    - 1m, 5m, 30m (minutes)
    - 1h, 6h, 12h, 24h (hours)
    - 1d, 3d, 7d (days)
    - 1w, 2w (weeks)
    - 1mo, 3mo, 6mo (months, approximated as 30 days)
    - permanent, perm, forever (returns None for permanent)

    Returns:
        timedelta if parsed successfully, None for permanent bans

    Raises:
        ValueError: If duration format is invalid
    """
    duration_str = duration_str.lower().strip()

    # Check for permanent ban keywords
    if duration_str in ("permanent", "perm", "forever", "inf"):
        return None

    # Pattern: number followed by unit
    match = re.match(
        r'^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|week|weeks|mo|month|months)$',
        duration_str
    )

    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}")

    value = int(match.group(1))
    unit = match.group(2)

    # Validate positive duration
    if value <= 0:
        raise ValueError("Duration must be a positive number")

    if unit in ("m", "min", "mins", "minute", "minutes"):
        return timedelta(minutes=value)
    elif unit in ("h", "hr", "hrs", "hour", "hours"):
        return timedelta(hours=value)
    elif unit in ("d", "day", "days"):
        return timedelta(days=value)
    elif unit in ("w", "wk", "week", "weeks"):
        return timedelta(weeks=value)
    elif unit in ("mo", "month", "months"):
        return timedelta(days=value * 30)  # Approximate month as 30 days

    raise ValueError(f"Unknown duration unit: {unit}")


def format_duration(td: Optional[timedelta]) -> str:
    """
    Format a timedelta into a human-readable string.

    Args:
        td: timedelta to format, or None for permanent

    Returns:
        Human-readable duration string
    """
    if td is None:
        return "Permanent"

    total_seconds = int(td.total_seconds())

    if total_seconds < 3600:  # Less than 1 hour
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif total_seconds < 86400:  # Less than 1 day
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    elif total_seconds < 604800:  # Less than 1 week
        days = total_seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"
    elif total_seconds < 2592000:  # Less than 30 days
        weeks = total_seconds // 604800
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    else:
        months = total_seconds // 2592000
        return f"{months} month{'s' if months != 1 else ''}"


def get_remaining_duration(total_seconds: int) -> str:
    """
    Format remaining seconds into a human-readable string.

    Args:
        total_seconds: Number of seconds remaining

    Returns:
        Human-readable remaining time string
    """
    if total_seconds <= 0:
        return "Expired"

    if total_seconds < 60:
        return f"{total_seconds}s left"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes}m left"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours}h left"
    else:
        days = total_seconds // 86400
        return f"{days}d left"


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "DURATION_SUGGESTIONS",
    "parse_duration",
    "format_duration",
    "get_remaining_duration",
]
