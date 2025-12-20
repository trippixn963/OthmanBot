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
)

# Schedulers
from src.services.schedulers import (
    BaseScheduler,
    ContentRotationScheduler,
    ContentType,
)

# Webhook Alerts
from src.services.webhook_alerts import (
    WebhookAlertService,
    get_alert_service,
)

# Interaction Logger
from src.services.interaction_logger import InteractionLogger

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
    # Webhook Alerts
    "WebhookAlertService",
    "get_alert_service",
    # Interaction Logger
    "InteractionLogger",
    # Case Log
    "CaseLogService",
]
