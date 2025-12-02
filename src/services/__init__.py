"""
Othman Discord Bot - Services Package
======================================

Backend services for content scraping and scheduling.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Scrapers
from src.services.scrapers import (
    BaseScraper,
    Article,
    NewsScraper,
    SoccerScraper,
    GamingScraper,
)
from src.services.scrapers.gaming import GamingArticle

# Schedulers
from src.services.schedulers import (
    BaseScheduler,
    ContentRotationScheduler,
    ContentType,
)

__all__ = [
    # Scrapers
    "BaseScraper",
    "Article",
    "NewsScraper",
    "SoccerScraper",
    "GamingScraper",
    "GamingArticle",
    # Schedulers
    "BaseScheduler",
    "ContentRotationScheduler",
    "ContentType",
]
