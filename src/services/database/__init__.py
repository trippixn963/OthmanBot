"""
OthmanBot - Database Module
===========================

Modular SQLite database for all bot features.

Structure:
    - core.py: Base class with connection management and table init
    - ai_cache.py: AI response caching
    - posted_urls.py: Posted article tracking
    - scheduler.py: Scheduler state persistence
    - metrics.py: Scraper metrics recording
    - dead_letter.py: Dead letter queue for failed articles
    - content_hashes.py: Content similarity detection
    - engagement.py: Article engagement tracking

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .core import (
    DatabaseCore,
    DatabaseUnavailableError,
    DB_PATH,
    DATA_DIR,
    AI_CACHE_EXPIRATION_DAYS,
    AI_CACHE_MAX_ENTRIES,
    POSTED_URLS_MAX_PER_TYPE,
    DEAD_LETTER_MAX_FAILURES,
    DEAD_LETTER_QUARANTINE_HOURS,
    CONTENT_HASH_RETENTION_DAYS,
    CONTENT_HASH_MAX_ENTRIES,
)
from .ai_cache import AICacheMixin
from .posted_urls import PostedURLsMixin
from .scheduler import SchedulerMixin
from .metrics import MetricsMixin
from .dead_letter import DeadLetterMixin
from .content_hashes import ContentHashesMixin
from .engagement import EngagementMixin


class Database(
    AICacheMixin,
    PostedURLsMixin,
    SchedulerMixin,
    MetricsMixin,
    DeadLetterMixin,
    ContentHashesMixin,
    EngagementMixin,
    DatabaseCore,
):
    """
    Complete database class combining all mixins.

    Inherits from all feature mixins and the core database class.
    The order matters - DatabaseCore must be last so its __init__ runs.
    """
    pass


# Global singleton instance
_db_instance = None


def get_db() -> Database:
    """Get the global database instance (singleton)."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


# Re-export for backwards compatibility
__all__ = [
    "Database",
    "get_db",
    "DatabaseUnavailableError",
    "DB_PATH",
    "DATA_DIR",
]
