"""
Othman Discord Bot - Data Models
=================================

Shared data models used across the bot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MatchEvent:
    """Live match event data for score notifications."""
    event_type: str  # start, goal, halftime, fulltime, goal_cancelled, red_card, yellow_card, substitution, penalty, var
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    minute: str
    home_logo: str = ""
    away_logo: str = ""
    league: str = ""
    team_scored: Optional[str] = None  # For goal events
    detail: Optional[str] = None  # Additional info like "Goal Cancelled", "VAR Decision", etc.
    scorer: Optional[str] = None  # Goal scorer name
    assist: Optional[str] = None  # Assist provider name
    team: Optional[str] = None  # Team involved in event (for cards, substitutions)
    player: Optional[str] = None  # Player name (for cards)
    player_in: Optional[str] = None  # Player coming in (for substitutions)
    player_out: Optional[str] = None  # Player going out (for substitutions)


__all__ = ["MatchEvent"]
