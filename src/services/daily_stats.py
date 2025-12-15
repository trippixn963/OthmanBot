"""
OthmanBot - Daily Stats Service
===============================

Tracks daily and weekly statistics and sends summary webhooks at midnight NY_TZ.
All data stored in SQLite - nothing in memory that can be lost on restart.

Features:
- Debate creation/activity tracking
- Karma vote tracking (with net karma)
- News posting stats
- Command usage tracking
- Moderation tracking (bans, unbans, auto-unbans)
- Hot debate tracking
- Bot health tracking (uptime, disconnects, restarts)
- Daily summary webhook at 00:00 NY_TZ
- Weekly summary webhook every Sunday at midnight
- Weekly health report every Sunday at midnight
- Week-over-week trend comparisons

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import NY_TZ, STATUS_CHECK_INTERVAL

# Database path
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DATA_DIR / "stats.db"

# Colors for embeds
COLOR_GREEN = 0x00FF00
COLOR_BLUE = 0x3498DB
COLOR_GOLD = 0xFFD700
COLOR_ORANGE = 0xFF6B00
COLOR_RED = 0xFF0000
COLOR_PURPLE = 0x9B59B6


class DailyStatsService:
    """
    Tracks daily activity statistics with full SQLite persistence.

    DESIGN: Everything stored in database. No in-memory state that can be lost.
    """

    def __init__(self, webhook_url: Optional[str] = None) -> None:
        """Initialize the daily stats service."""
        self.webhook_url = webhook_url or os.getenv("STATS_WEBHOOK_URL")
        self.bot: Optional[discord.Client] = None
        self._scheduler_task: Optional[asyncio.Task] = None
        self._db_initialized = False

        # Initialize database
        self._init_database()

        logger.tree("Daily Stats Service Initialized", [
            ("Database", "Ready" if self._db_initialized else "Failed"),
            ("DB Path", str(DB_PATH) if self._db_initialized else "N/A"),
            ("Webhook", "Configured" if self.webhook_url else "Not set"),
        ], emoji="📊")

    # =========================================================================
    # Database Operations
    # =========================================================================

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(DB_PATH)

    def _init_database(self) -> None:
        """Initialize SQLite database with required tables."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            conn = self._get_connection()
            cursor = conn.cursor()

            # Table for daily activity stats
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    debates_created INTEGER DEFAULT 0,
                    debates_deleted INTEGER DEFAULT 0,
                    messages_in_debates INTEGER DEFAULT 0,
                    upvotes_given INTEGER DEFAULT 0,
                    downvotes_given INTEGER DEFAULT 0,
                    net_karma INTEGER DEFAULT 0,
                    news_posted INTEGER DEFAULT 0,
                    soccer_posted INTEGER DEFAULT 0,
                    gaming_posted INTEGER DEFAULT 0,
                    commands_used INTEGER DEFAULT 0,
                    users_banned INTEGER DEFAULT 0,
                    users_unbanned INTEGER DEFAULT 0,
                    auto_unbans INTEGER DEFAULT 0,
                    hot_debates INTEGER DEFAULT 0,
                    unique_participants INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date)
                )
            """)

            # Table for bot health events
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_health_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    reason TEXT,
                    details TEXT
                )
            """)

            # Table for downtime tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS downtime_periods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    disconnect_time TEXT NOT NULL,
                    reconnect_time TEXT,
                    downtime_minutes REAL,
                    date TEXT NOT NULL,
                    reason TEXT
                )
            """)

            # Table for top debaters per day
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS top_debaters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    messages INTEGER DEFAULT 0,
                    karma_received INTEGER DEFAULT 0,
                    debates_started INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, user_id)
                )
            """)

            # Table for debate stats
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS debate_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    thread_id INTEGER NOT NULL,
                    thread_name TEXT,
                    creator_id INTEGER,
                    creator_name TEXT,
                    messages INTEGER DEFAULT 0,
                    participants INTEGER DEFAULT 0,
                    upvotes INTEGER DEFAULT 0,
                    downvotes INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, thread_id)
                )
            """)

            # Table for command usage
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS command_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    command_name TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    UNIQUE(date, command_name)
                )
            """)

            # Indexes for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_activity_date
                ON daily_activity(date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_debaters_date
                ON top_debaters(date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_debate_stats_date
                ON debate_stats(date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_health_date
                ON bot_health_events(date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_downtime_date
                ON downtime_periods(date)
            """)

            conn.commit()
            conn.close()
            self._db_initialized = True

        except Exception as e:
            logger.error("Stats Database Init Failed", [("Error", str(e))])
            self._db_initialized = False

    def _get_today(self) -> str:
        """Get today's date string in NY_TZ."""
        return datetime.now(NY_TZ).strftime("%Y-%m-%d")

    def _ensure_daily_record(self, date: str) -> None:
        """Ensure a daily activity record exists for the date."""
        if not self._db_initialized:
            return

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO daily_activity (date)
                VALUES (?)
            """, (date,))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB Insert Error", [("Error", str(e))])

    # =========================================================================
    # Tracking Methods
    # =========================================================================

    def record_debate_created(self, thread_id: int, thread_name: str, creator_id: int, creator_name: str) -> None:
        """Record a new debate creation."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Update daily activity
            cursor.execute("""
                UPDATE daily_activity
                SET debates_created = debates_created + 1
                WHERE date = ?
            """, (date,))

            # Record debate stats
            cursor.execute("""
                INSERT OR REPLACE INTO debate_stats (date, thread_id, thread_name, creator_id, creator_name)
                VALUES (?, ?, ?, ?, ?)
            """, (date, thread_id, thread_name, creator_id, creator_name))

            # Update top debaters
            cursor.execute("""
                INSERT INTO top_debaters (date, user_id, user_name, debates_started)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(date, user_id) DO UPDATE SET
                    debates_started = debates_started + 1,
                    user_name = excluded.user_name
            """, (date, creator_id, creator_name))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to record debate", [("Error", str(e))])

    def record_debate_message(self, thread_id: int, user_id: int, user_name: str) -> None:
        """Record a message in a debate thread."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Update daily activity
            cursor.execute("""
                UPDATE daily_activity
                SET messages_in_debates = messages_in_debates + 1
                WHERE date = ?
            """, (date,))

            # Update debate stats
            cursor.execute("""
                UPDATE debate_stats
                SET messages = messages + 1
                WHERE date = ? AND thread_id = ?
            """, (date, thread_id))

            # Update top debaters
            cursor.execute("""
                INSERT INTO top_debaters (date, user_id, user_name, messages)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(date, user_id) DO UPDATE SET
                    messages = messages + 1,
                    user_name = excluded.user_name
            """, (date, user_id, user_name))

            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB Debate Activity Error", [("Error", str(e))])

    def record_karma_vote(self, recipient_id: int, recipient_name: str, is_upvote: bool) -> None:
        """Record a karma vote."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Update daily activity with net karma tracking
            karma_change = 1 if is_upvote else -1
            if is_upvote:
                cursor.execute("""
                    UPDATE daily_activity
                    SET upvotes_given = upvotes_given + 1, net_karma = net_karma + 1
                    WHERE date = ?
                """, (date,))
            else:
                cursor.execute("""
                    UPDATE daily_activity
                    SET downvotes_given = downvotes_given + 1, net_karma = net_karma - 1
                    WHERE date = ?
                """, (date,))

            # Update top debaters karma received
            cursor.execute("""
                INSERT INTO top_debaters (date, user_id, user_name, karma_received)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date, user_id) DO UPDATE SET
                    karma_received = karma_received + ?,
                    user_name = excluded.user_name
            """, (date, recipient_id, recipient_name, karma_change, karma_change))

            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB Karma Vote Error", [("Error", str(e))])

    def record_news_posted(self, content_type: str = "news") -> None:
        """Record a news/content post."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if content_type == "news":
                cursor.execute("UPDATE daily_activity SET news_posted = news_posted + 1 WHERE date = ?", (date,))
            elif content_type == "soccer":
                cursor.execute("UPDATE daily_activity SET soccer_posted = soccer_posted + 1 WHERE date = ?", (date,))
            elif content_type == "gaming":
                cursor.execute("UPDATE daily_activity SET gaming_posted = gaming_posted + 1 WHERE date = ?", (date,))

            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB News Posted Error", [("Error", str(e))])

    def record_command_used(self, command_name: str) -> None:
        """Record a command usage."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Update daily activity
            cursor.execute("""
                UPDATE daily_activity
                SET commands_used = commands_used + 1
                WHERE date = ?
            """, (date,))

            # Update command usage
            cursor.execute("""
                INSERT INTO command_usage (date, command_name, usage_count)
                VALUES (?, ?, 1)
                ON CONFLICT(date, command_name) DO UPDATE SET
                    usage_count = usage_count + 1
            """, (date, command_name))

            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB Command Usage Error", [("Error", str(e))])

    def record_user_banned(self) -> None:
        """Record a user ban."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE daily_activity SET users_banned = users_banned + 1 WHERE date = ?", (date,))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB User Banned Error", [("Error", str(e))])

    def record_user_unbanned(self, auto: bool = False) -> None:
        """Record a user unban (manual or auto)."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            if auto:
                cursor.execute("UPDATE daily_activity SET auto_unbans = auto_unbans + 1 WHERE date = ?", (date,))
            else:
                cursor.execute("UPDATE daily_activity SET users_unbanned = users_unbanned + 1 WHERE date = ?", (date,))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB User Unbanned Error", [("Error", str(e))])

    def record_hot_debate(self) -> None:
        """Record a debate becoming hot."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE daily_activity SET hot_debates = hot_debates + 1 WHERE date = ?", (date,))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB Hot Debate Error", [("Error", str(e))])

    # =========================================================================
    # Bot Health Tracking
    # =========================================================================

    def record_bot_start(self) -> None:
        """Record bot startup event."""
        if not self._db_initialized:
            return

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now(NY_TZ)

            cursor.execute("""
                INSERT INTO bot_health_events (event_type, timestamp, date, reason)
                VALUES (?, ?, ?, ?)
            """, ("start", now.isoformat(), now.strftime("%Y-%m-%d"), "Bot started"))

            conn.commit()
            conn.close()
            logger.debug("Bot Start Recorded")
        except Exception as e:
            logger.warning("Failed to Record Bot Start", [("Error", str(e))])

    def record_disconnect(self, reason: str = "Unknown") -> None:
        """Record a disconnect event."""
        if not self._db_initialized:
            return

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now(NY_TZ)

            cursor.execute("""
                INSERT INTO bot_health_events (event_type, timestamp, date, reason)
                VALUES (?, ?, ?, ?)
            """, ("disconnect", now.isoformat(), now.strftime("%Y-%m-%d"), reason))

            cursor.execute("""
                INSERT INTO downtime_periods (disconnect_time, date, reason)
                VALUES (?, ?, ?)
            """, (now.isoformat(), now.strftime("%Y-%m-%d"), reason))

            conn.commit()
            conn.close()
            logger.debug("Disconnect Recorded", [("Reason", reason)])
        except Exception as e:
            logger.warning("Failed to Record Disconnect", [("Error", str(e))])

    def record_reconnect(self) -> None:
        """Record a reconnect event and calculate downtime."""
        if not self._db_initialized:
            return

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now(NY_TZ)

            cursor.execute("""
                INSERT INTO bot_health_events (event_type, timestamp, date, reason)
                VALUES (?, ?, ?, ?)
            """, ("reconnect", now.isoformat(), now.strftime("%Y-%m-%d"), "Reconnected"))

            # Close open downtime period
            cursor.execute("""
                SELECT id, disconnect_time FROM downtime_periods
                WHERE reconnect_time IS NULL
                ORDER BY id DESC LIMIT 1
            """)
            open_period = cursor.fetchone()

            if open_period:
                period_id, disconnect_time_str = open_period
                disconnect_time = datetime.fromisoformat(disconnect_time_str)
                downtime_mins = (now - disconnect_time).total_seconds() / 60

                cursor.execute("""
                    UPDATE downtime_periods
                    SET reconnect_time = ?, downtime_minutes = ?
                    WHERE id = ?
                """, (now.isoformat(), downtime_mins, period_id))

                logger.debug("Reconnect Recorded", [("Downtime", f"{downtime_mins:.1f}m")])

            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to Record Reconnect", [("Error", str(e))])

    # =========================================================================
    # Query Methods
    # =========================================================================

    def _get_daily_stats(self, date: str) -> Optional[Dict]:
        """Get stats for a specific date."""
        if not self._db_initialized:
            return None

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Get daily activity
            cursor.execute("""
                SELECT debates_created, debates_deleted, messages_in_debates,
                       upvotes_given, downvotes_given, net_karma, news_posted, soccer_posted,
                       gaming_posted, commands_used, users_banned, users_unbanned,
                       auto_unbans, hot_debates
                FROM daily_activity
                WHERE date = ?
            """, (date,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                return None

            # Get unique participants count
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id) FROM top_debaters WHERE date = ?
            """, (date,))
            unique_participants = cursor.fetchone()[0] or 0

            # Get top debaters by karma
            cursor.execute("""
                SELECT user_id, user_name, messages, karma_received, debates_started
                FROM top_debaters
                WHERE date = ? AND karma_received > 0
                ORDER BY karma_received DESC
                LIMIT 5
            """, (date,))
            top_karma_earners = cursor.fetchall()

            # Get most active by messages
            cursor.execute("""
                SELECT user_id, user_name, messages, karma_received, debates_started
                FROM top_debaters
                WHERE date = ?
                ORDER BY messages DESC
                LIMIT 5
            """, (date,))
            most_active = cursor.fetchall()

            # Get top commands
            cursor.execute("""
                SELECT command_name, usage_count
                FROM command_usage
                WHERE date = ?
                ORDER BY usage_count DESC
                LIMIT 5
            """, (date,))
            top_commands = cursor.fetchall()

            conn.close()

            return {
                "debates_created": row[0] or 0,
                "debates_deleted": row[1] or 0,
                "messages_in_debates": row[2] or 0,
                "upvotes_given": row[3] or 0,
                "downvotes_given": row[4] or 0,
                "net_karma": row[5] or 0,
                "news_posted": row[6] or 0,
                "soccer_posted": row[7] or 0,
                "gaming_posted": row[8] or 0,
                "commands_used": row[9] or 0,
                "users_banned": row[10] or 0,
                "users_unbanned": row[11] or 0,
                "auto_unbans": row[12] or 0,
                "hot_debates": row[13] or 0,
                "unique_participants": unique_participants,
                "top_karma_earners": top_karma_earners,
                "most_active": most_active,
                "top_commands": top_commands,
            }

        except Exception as e:
            logger.warning("Daily Stats Query Failed", [("Error", str(e))])
            return None

    def get_weekly_stats(self) -> Dict:
        """Get aggregated stats for the past 7 days."""
        if not self._db_initialized:
            return {}

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            today = datetime.now(NY_TZ).date()
            week_ago = today - timedelta(days=7)
            week_ago_str = week_ago.strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")

            # Aggregate stats
            cursor.execute("""
                SELECT
                    SUM(debates_created), SUM(messages_in_debates),
                    SUM(upvotes_given), SUM(downvotes_given), SUM(net_karma),
                    SUM(news_posted), SUM(soccer_posted), SUM(gaming_posted),
                    SUM(commands_used), SUM(users_banned), SUM(users_unbanned),
                    SUM(auto_unbans), SUM(hot_debates)
                FROM daily_activity
                WHERE date >= ? AND date < ?
            """, (week_ago_str, today_str))
            row = cursor.fetchone()

            # Unique participants
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id) FROM top_debaters
                WHERE date >= ? AND date < ?
            """, (week_ago_str, today_str))
            unique_participants = cursor.fetchone()[0] or 0

            # Top karma earners for the week
            cursor.execute("""
                SELECT user_id, user_name, SUM(karma_received) as total_karma
                FROM top_debaters
                WHERE date >= ? AND date < ?
                GROUP BY user_id
                HAVING total_karma > 0
                ORDER BY total_karma DESC
                LIMIT 5
            """, (week_ago_str, today_str))
            top_karma_earners = cursor.fetchall()

            # Most active for the week
            cursor.execute("""
                SELECT user_id, user_name, SUM(messages) as total_messages
                FROM top_debaters
                WHERE date >= ? AND date < ?
                GROUP BY user_id
                ORDER BY total_messages DESC
                LIMIT 5
            """, (week_ago_str, today_str))
            most_active = cursor.fetchall()

            # Daily breakdown
            cursor.execute("""
                SELECT date, debates_created, messages_in_debates, net_karma
                FROM daily_activity
                WHERE date >= ? AND date < ?
                ORDER BY date
            """, (week_ago_str, today_str))
            daily_breakdown = cursor.fetchall()

            conn.close()

            return {
                "start_date": week_ago_str,
                "end_date": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                "debates_created": row[0] or 0,
                "messages_in_debates": row[1] or 0,
                "upvotes_given": row[2] or 0,
                "downvotes_given": row[3] or 0,
                "net_karma": row[4] or 0,
                "news_posted": row[5] or 0,
                "soccer_posted": row[6] or 0,
                "gaming_posted": row[7] or 0,
                "commands_used": row[8] or 0,
                "users_banned": row[9] or 0,
                "users_unbanned": row[10] or 0,
                "auto_unbans": row[11] or 0,
                "hot_debates": row[12] or 0,
                "unique_participants": unique_participants,
                "top_karma_earners": top_karma_earners,
                "most_active": most_active,
                "daily_breakdown": daily_breakdown,
            }

        except Exception as e:
            logger.warning("Weekly Stats Query Failed", [("Error", str(e))])
            return {}

    def _get_previous_week_stats(self) -> Optional[Dict]:
        """Get stats from previous week for trend comparison."""
        if not self._db_initialized:
            return None

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            today = datetime.now(NY_TZ).date()
            two_weeks_ago = (today - timedelta(days=14)).strftime("%Y-%m-%d")
            one_week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")

            cursor.execute("""
                SELECT
                    SUM(debates_created),
                    SUM(messages_in_debates),
                    SUM(net_karma),
                    COUNT(DISTINCT date)
                FROM daily_activity
                WHERE date >= ? AND date < ?
            """, (two_weeks_ago, one_week_ago))
            row = cursor.fetchone()

            conn.close()

            if row and row[3]:  # Has data
                return {
                    "debates_created": row[0] or 0,
                    "messages_in_debates": row[1] or 0,
                    "net_karma": row[2] or 0,
                }
            return None
        except Exception:
            return None

    def _get_weekly_health_stats(self) -> Dict:
        """Get bot health stats for the past 7 days."""
        if not self._db_initialized:
            return {}

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            today = datetime.now(NY_TZ).date()
            week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")

            # Count events
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN event_type = 'disconnect' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN event_type = 'start' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN event_type = 'reconnect' THEN 1 ELSE 0 END)
                FROM bot_health_events
                WHERE date >= ? AND date < ?
            """, (week_ago, today_str))
            row = cursor.fetchone()

            # Total downtime
            cursor.execute("""
                SELECT SUM(downtime_minutes) FROM downtime_periods
                WHERE date >= ? AND date < ? AND downtime_minutes IS NOT NULL
            """, (week_ago, today_str))
            downtime = cursor.fetchone()[0] or 0

            # Calculate uptime percentage
            total_mins = 7 * 24 * 60
            uptime_pct = ((total_mins - downtime) / total_mins) * 100 if total_mins > 0 else 100

            # Daily breakdown
            cursor.execute("""
                SELECT date,
                    SUM(CASE WHEN event_type = 'disconnect' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN event_type = 'start' THEN 1 ELSE 0 END)
                FROM bot_health_events
                WHERE date >= ? AND date < ?
                GROUP BY date
                ORDER BY date
            """, (week_ago, today_str))
            daily_breakdown = cursor.fetchall()

            conn.close()

            return {
                "total_disconnects": row[0] or 0,
                "total_starts": row[1] or 0,
                "total_reconnects": row[2] or 0,
                "total_downtime_mins": downtime,
                "uptime_percentage": min(uptime_pct, 100),
                "daily_breakdown": daily_breakdown,
            }
        except Exception as e:
            logger.warning("Weekly Health Stats Query Failed", [("Error", str(e))])
            return {}

    # =========================================================================
    # Webhook Methods
    # =========================================================================

    async def send_daily_summary(self, date: Optional[str] = None) -> None:
        """Send daily stats summary to webhook."""
        if not self.webhook_url:
            logger.warning("Stats Webhook Not Configured")
            return

        if date is None:
            date = self._get_today()

        stats = self._get_daily_stats(date)
        if not stats:
            logger.warning("No Stats Available", [("Date", date)])
            return

        # Build fields
        fields = []

        # Main stats row
        fields.append({
            "name": "📝 Debates Created",
            "value": f"`{stats['debates_created']}`",
            "inline": True
        })
        fields.append({
            "name": "💬 Messages Sent",
            "value": f"`{stats['messages_in_debates']}`",
            "inline": True
        })
        fields.append({
            "name": "👥 Participants",
            "value": f"`{stats['unique_participants']}`",
            "inline": True
        })

        # Karma row
        fields.append({
            "name": "⬆️ Upvotes",
            "value": f"`{stats['upvotes_given']}`",
            "inline": True
        })
        fields.append({
            "name": "⬇️ Downvotes",
            "value": f"`{stats['downvotes_given']}`",
            "inline": True
        })
        net_karma_str = f"+{stats['net_karma']}" if stats['net_karma'] >= 0 else str(stats['net_karma'])
        fields.append({
            "name": "✨ Net Karma",
            "value": f"`{net_karma_str}`",
            "inline": True
        })

        # Moderation stats (only if any)
        mod_actions = stats['users_banned'] + stats['users_unbanned'] + stats['auto_unbans']
        if mod_actions > 0:
            mod_str = f"🚫 Bans: `{stats['users_banned']}` • ✅ Unbans: `{stats['users_unbanned']}` • ⏰ Auto: `{stats['auto_unbans']}`"
            fields.append({
                "name": "⚖️ Moderation",
                "value": mod_str,
                "inline": False
            })

        # Hot debates
        if stats['hot_debates'] > 0:
            fields.append({
                "name": "🔥 Hot Debates",
                "value": f"`{stats['hot_debates']}`",
                "inline": True
            })

        # Top karma earners
        if stats["top_karma_earners"]:
            top_list = "\n".join([
                f"**{i+1}.** {name} `[{user_id}]` - `+{karma}`"
                for i, (user_id, name, msgs, karma, debates) in enumerate(stats["top_karma_earners"][:5])
            ])
            fields.append({
                "name": "🏆 Top Karma Earners",
                "value": top_list,
                "inline": False
            })

        # Most active
        if stats["most_active"]:
            active_list = ", ".join([
                f"{name} (`{msgs}`)"
                for _, name, msgs, _, _ in stats["most_active"][:5]
            ])
            fields.append({
                "name": "💬 Most Active",
                "value": active_list,
                "inline": False
            })

        # Commands section
        if stats["commands_used"] > 0 and stats["top_commands"]:
            cmd_list = ", ".join([f"`/{cmd}` ({count})" for cmd, count in stats["top_commands"][:5]])
            fields.append({
                "name": "⚡ Commands Used",
                "value": f"Total: `{stats['commands_used']}` • {cmd_list}",
                "inline": False
            })

        embed = {
            "title": "📊 OthmanBot - Daily Stats",
            "description": f"**Date:** {date}",
            "color": COLOR_BLUE,
            "fields": fields,
            "timestamp": datetime.now(NY_TZ).isoformat(),
            "footer": {"text": "OthmanBot Daily Summary"}
        }

        await self._send_webhook(embed)
        logger.info("Daily Stats Webhook Sent", [
            ("Date", date),
            ("Debates", str(stats["debates_created"])),
            ("Messages", str(stats["messages_in_debates"])),
        ])

    async def send_weekly_summary(self) -> None:
        """Send weekly stats summary to webhook."""
        if not self.webhook_url:
            return

        weekly = self.get_weekly_stats()
        if not weekly:
            return

        # Get previous week for trend comparison
        prev_week = self._get_previous_week_stats()

        def get_trend(current: float, previous: float) -> str:
            if not previous or previous == 0:
                return ""
            change = ((current - previous) / previous) * 100
            if change > 0:
                return f" ↑{change:.0f}%"
            elif change < 0:
                return f" ↓{abs(change):.0f}%"
            return ""

        debates_trend = get_trend(weekly['debates_created'], prev_week['debates_created']) if prev_week else ""
        messages_trend = get_trend(weekly['messages_in_debates'], prev_week['messages_in_debates']) if prev_week else ""
        karma_trend = get_trend(weekly['net_karma'], prev_week['net_karma']) if prev_week and prev_week['net_karma'] else ""

        # Build fields
        fields = [
            {
                "name": "📝 Debates Created",
                "value": f"`{weekly['debates_created']}`{debates_trend}",
                "inline": True
            },
            {
                "name": "💬 Messages Sent",
                "value": f"`{weekly['messages_in_debates']}`{messages_trend}",
                "inline": True
            },
            {
                "name": "👥 Participants",
                "value": f"`{weekly['unique_participants']}`",
                "inline": True
            },
            {
                "name": "⬆️ Upvotes",
                "value": f"`{weekly['upvotes_given']}`",
                "inline": True
            },
            {
                "name": "⬇️ Downvotes",
                "value": f"`{weekly['downvotes_given']}`",
                "inline": True
            },
        ]

        net_karma_str = f"+{weekly['net_karma']}" if weekly['net_karma'] >= 0 else str(weekly['net_karma'])
        fields.append({
            "name": "✨ Net Karma",
            "value": f"`{net_karma_str}`{karma_trend}",
            "inline": True
        })

        # Moderation stats (only if any)
        mod_actions = weekly['users_banned'] + weekly['users_unbanned'] + weekly['auto_unbans']
        if mod_actions > 0:
            mod_str = f"🚫 Bans: `{weekly['users_banned']}` • ✅ Unbans: `{weekly['users_unbanned']}` • ⏰ Auto: `{weekly['auto_unbans']}`"
            fields.append({
                "name": "⚖️ Moderation",
                "value": mod_str,
                "inline": False
            })

        # Hot debates
        if weekly['hot_debates'] > 0:
            fields.append({
                "name": "🔥 Hot Debates",
                "value": f"`{weekly['hot_debates']}`",
                "inline": True
            })

        # Daily breakdown
        if weekly["daily_breakdown"]:
            daily_list = "\n".join([
                f"`{date}` - {debates} debates, {msgs} msgs, {'+' if karma >= 0 else ''}{karma} karma"
                for date, debates, msgs, karma in weekly["daily_breakdown"]
            ])
            fields.append({
                "name": "📅 Daily Breakdown",
                "value": daily_list,
                "inline": False
            })

        # Top karma earners
        if weekly["top_karma_earners"]:
            top_list = "\n".join([
                f"**{i+1}.** {name} `[{user_id}]` - `+{karma}`"
                for i, (user_id, name, karma) in enumerate(weekly["top_karma_earners"][:5])
            ])
            fields.append({
                "name": "🏆 Top Karma Earners",
                "value": top_list,
                "inline": False
            })

        # Most active
        if weekly["most_active"]:
            active_list = ", ".join([
                f"{name} (`{msgs}`)"
                for _, name, msgs in weekly["most_active"][:5]
            ])
            fields.append({
                "name": "💬 Most Active",
                "value": active_list,
                "inline": False
            })

        embed = {
            "title": "📊 OthmanBot - Weekly Stats",
            "description": f"**Week:** {weekly['start_date']} → {weekly['end_date']}",
            "color": COLOR_GOLD,
            "fields": fields,
            "timestamp": datetime.now(NY_TZ).isoformat(),
            "footer": {"text": "OthmanBot Weekly Summary"}
        }

        await self._send_webhook(embed)
        logger.info("Weekly Stats Webhook Sent", [
            ("Week", f"{weekly['start_date']} → {weekly['end_date']}"),
            ("Debates", str(weekly['debates_created'])),
        ])

    async def send_weekly_health_report(self) -> None:
        """Send weekly bot health report."""
        if not self.webhook_url:
            return

        health = self._get_weekly_health_stats()
        if not health:
            return

        uptime = health["uptime_percentage"]
        if uptime >= 99:
            color = COLOR_GREEN
            status = "Excellent"
        elif uptime >= 95:
            color = COLOR_ORANGE
            status = "Good"
        else:
            color = COLOR_RED
            status = "Needs Attention"

        fields = [
            {"name": "⏱️ Uptime", "value": f"`{uptime:.2f}%` ({status})", "inline": True},
            {"name": "⚠️ Disconnects", "value": f"`{health['total_disconnects']}`", "inline": True},
            {"name": "🔄 Restarts", "value": f"`{health['total_starts']}`", "inline": True},
            {"name": "⏰ Total Downtime", "value": f"`{health['total_downtime_mins']:.1f}` minutes", "inline": True},
        ]

        # Daily breakdown
        if health["daily_breakdown"]:
            daily_list = "\n".join([
                f"`{date}` - {disc} disconnects, {starts} restarts"
                for date, disc, starts in health["daily_breakdown"]
                if disc > 0 or starts > 0
            ])
            if daily_list:
                fields.append({
                    "name": "📅 Daily Events",
                    "value": daily_list,
                    "inline": False
                })

        embed = {
            "title": "🤖 OthmanBot - Weekly Health Report",
            "color": color,
            "fields": fields,
            "timestamp": datetime.now(NY_TZ).isoformat(),
            "footer": {"text": "OthmanBot Weekly Health Report"}
        }

        await self._send_webhook(embed)
        logger.info("Weekly Health Report Sent", [
            ("Uptime", f"{uptime:.2f}%"),
            ("Disconnects", str(health['total_disconnects'])),
        ])

    async def _send_webhook(self, embed: dict) -> None:
        """Send an embed to the webhook."""
        if not self.webhook_url:
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json={"embeds": [embed]},
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status not in (200, 204):
                        logger.warning("Stats Webhook Error", [("Status", str(response.status))])
        except Exception as e:
            logger.warning("Stats Webhook Failed", [("Error", str(e))])

    # =========================================================================
    # Scheduler
    # =========================================================================

    async def start_scheduler(self) -> None:
        """Start the midnight stats scheduler."""
        if not self.webhook_url:
            logger.info("Stats Scheduler Not Started", [("Reason", "No webhook configured")])
            return

        async def scheduler_loop():
            while True:
                try:
                    now = datetime.now(NY_TZ)

                    # Calculate time until midnight
                    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    wait_seconds = (tomorrow - now).total_seconds()

                    logger.debug("Stats Scheduler Waiting", [
                        ("Next Run", tomorrow.strftime('%Y-%m-%d %H:%M EST')),
                        ("Wait", f"{wait_seconds / 3600:.1f}h"),
                    ])

                    await asyncio.sleep(wait_seconds)

                    # Send daily summary for yesterday
                    yesterday = (datetime.now(NY_TZ) - timedelta(seconds=1)).strftime("%Y-%m-%d")
                    await self.send_daily_summary(yesterday)

                    # If it's Sunday, send weekly summaries
                    if datetime.now(NY_TZ).weekday() == 6:
                        await asyncio.sleep(2)
                        await self.send_weekly_summary()
                        await asyncio.sleep(2)
                        await self.send_weekly_health_report()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Stats Scheduler Error", [("Error", str(e))])
                    await asyncio.sleep(60)

        self._scheduler_task = asyncio.create_task(scheduler_loop())
        logger.info("Stats Scheduler Started", [
            ("Daily", "00:00 EST"),
            ("Weekly", "Sunday 00:00 EST"),
        ])

    async def stop_scheduler(self) -> None:
        """Stop the midnight stats scheduler."""
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
            logger.info("Stats Scheduler Stopped")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DailyStatsService"]
