"""
Othman Discord Bot - Scrapers Package
======================================

Content scraper modules for news, soccer, and gaming.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.services.scrapers.base import BaseScraper, Article
from src.services.scrapers.news import NewsScraper
from src.services.scrapers.soccer import SoccerScraper
from src.services.scrapers.gaming import GamingScraper

__all__ = [
    "BaseScraper",
    "Article",
    "NewsScraper",
    "SoccerScraper",
    "GamingScraper",
]
