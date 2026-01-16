"""
OthmanBot - Combined Debates Database
===============================================

SQLite database combining all mixins for debate management.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.services.debates.db.core import DatabaseCore, UserKarma
from src.services.debates.db.karma import KarmaMixin
from src.services.debates.db.bans import BansMixin
from src.services.debates.db.leaderboard import LeaderboardMixin
from src.services.debates.db.analytics import AnalyticsMixin
from src.services.debates.db.threads import ThreadsMixin
from src.services.debates.db.cases import CasesMixin, CacheMixin
from src.services.debates.db.appeals import AppealsMixin


class DebatesDatabase(
    KarmaMixin,
    BansMixin,
    LeaderboardMixin,
    AnalyticsMixin,
    ThreadsMixin,
    CasesMixin,
    CacheMixin,
    AppealsMixin,
    DatabaseCore
):
    """
    Complete debates database with all functionality.

    Inherits from:
    - DatabaseCore: Connection handling, schema, migrations
    - KarmaMixin: Vote and karma operations
    - BansMixin: Ban management
    - LeaderboardMixin: Rankings and stats
    - AnalyticsMixin: User analytics and streaks
    - ThreadsMixin: Thread data management
    - CasesMixin: Case log operations
    - CacheMixin: User cache operations
    - AppealsMixin: Appeal management operations
    """

    def __init__(self, db_path: str = "data/othman.db") -> None:
        """Initialize database with all mixins."""
        super().__init__(db_path)

    def audit_log(
        self,
        action: str,
        actor_id: int = None,
        target_id: int = None,
        target_type: str = None,
        old_value: str = None,
        new_value: str = None,
        metadata: dict = None
    ) -> None:
        """Log an audit event (placeholder for future implementation)."""
        # Audit logging can be implemented later if needed
        pass

    def get_karma_changes_today(self, user_ids: list[int]) -> dict[int, int]:
        """Get karma changes for a list of users today."""
        if not user_ids:
            return {}

        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(user_ids))
            cursor.execute(
                f"""SELECT author_id, SUM(vote_type) FROM votes
                    WHERE author_id IN ({placeholders})
                    AND DATE(created_at) = DATE('now')
                    GROUP BY author_id""",
                user_ids
            )
            return {row[0]: row[1] for row in cursor.fetchall()}


# Re-export for backwards compatibility
__all__ = ["DebatesDatabase", "UserKarma"]
