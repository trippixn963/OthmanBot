"""
OthmanBot - Services Package
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
)

# Schedulers
from src.services.schedulers import (
    BaseScheduler,
    ContentRotationScheduler,
    ContentType,
)

# Status Webhook
from src.services.status_webhook import (
    StatusWebhookService,
    get_status_service,
)

# Case Log
from src.services.case_log import CaseLogService

__all__ = [
    # Scrapers
    "BaseScraper",
    "Article",
    "NewsScraper",
    "SoccerScraper",
    # Schedulers
    "BaseScheduler",
    "ContentRotationScheduler",
    "ContentType",
    # Status Webhook
    "StatusWebhookService",
    "get_status_service",
    # Case Log
    "CaseLogService",
]
