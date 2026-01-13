"""
OthmanBot - Stats API Package
=============================

HTTP API server for OthmanBot Dashboard.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.services.stats_api.api import OthmanAPI
from src.services.stats_api.constants import STATS_API_PORT, STATS_API_HOST

__all__ = ["OthmanAPI", "STATS_API_PORT", "STATS_API_HOST"]
