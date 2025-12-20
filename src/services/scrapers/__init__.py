"""
Othman Discord Bot - Scrapers Package
======================================

Content scraper modules for news and soccer.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.services.scrapers.base import BaseScraper, Article
from src.services.scrapers.news import NewsScraper
from src.services.scrapers.soccer import SoccerScraper

__all__ = [
    "BaseScraper",
    "Article",
    "NewsScraper",
    "SoccerScraper",
]
