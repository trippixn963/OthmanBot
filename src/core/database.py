"""
OthmanBot - Database (Backwards Compatibility)
==============================================

This file is kept for backwards compatibility.
All database code has been moved to src/services/database/

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Re-export everything from the new location
from src.services.database import (
    Database,
    get_db,
    DatabaseUnavailableError,
    DB_PATH,
    DATA_DIR,
)

# For any code that used DatabaseManager directly
DatabaseManager = Database

__all__ = [
    "Database",
    "DatabaseManager",
    "get_db",
    "DatabaseUnavailableError",
    "DB_PATH",
    "DATA_DIR",
]
