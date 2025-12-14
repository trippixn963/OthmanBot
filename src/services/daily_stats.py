"""
OthmanBot - Daily Stats Service
===============================

Tracks daily statistics and sends a summary webhook at midnight NY_TZ.
All data stored in SQLite - nothing in memory that can be lost on restart.

Features:
- Debate creation/activity tracking
- Karma vote tracking
- News posting stats
- Command usage tracking
- Daily summary webhook at 00:00 NY_TZ
- Weekly summary webhook every Sunday at midnight

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

# Colors
COLOR_GREEN = 0x00FF00
COLOR_BLUE = 0x3498DB


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
                    news_posted INTEGER DEFAULT 0,
                    soccer_posted INTEGER DEFAULT 0,
                    gaming_posted INTEGER DEFAULT 0,
                    commands_used INTEGER DEFAULT 0,
                    users_banned INTEGER DEFAULT 0,
                    users_unbanned INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date)
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

            # Update daily activity
            if is_upvote:
                cursor.execute("""
                    UPDATE daily_activity
                    SET upvotes_given = upvotes_given + 1
                    WHERE date = ?
                """, (date,))
            else:
                cursor.execute("""
                    UPDATE daily_activity
                    SET downvotes_given = downvotes_given + 1
                    WHERE date = ?
                """, (date,))

            # Update top debaters karma received
            karma_change = 1 if is_upvote else -1
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

    def record_user_unbanned(self) -> None:
        """Record a user unban."""
        if not self._db_initialized:
            return

        date = self._get_today()
        self._ensure_daily_record(date)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE daily_activity SET users_unbanned = users_unbanned + 1 WHERE date = ?", (date,))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.debug("Stats DB User Unbanned Error", [("Error", str(e))])

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
                       upvotes_given, downvotes_given, news_posted, soccer_posted,
                       gaming_posted, commands_used, users_banned, users_unbanned
                FROM daily_activity
                WHERE date = ?
            """, (date,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                return None

            # Get top debaters
            cursor.execute("""
                SELECT user_id, user_name, messages, karma_received, debates_started
                FROM top_debaters
                WHERE date = ?
                ORDER BY messages DESC
                LIMIT 10
            """, (date,))
            top_debaters = cursor.fetchall()

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
                "news_posted": row[5] or 0,
                "soccer_posted": row[6] or 0,
                "gaming_posted": row[7] or 0,
                "commands_used": row[8] or 0,
                "users_banned": row[9] or 0,
                "users_unbanned": row[10] or 0,
                "top_debaters": top_debaters,
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
                    SUM(upvotes_given), SUM(downvotes_given),
                    SUM(news_posted), SUM(soccer_posted), SUM(gaming_posted),
                    SUM(commands_used)
                FROM daily_activity
                WHERE date >= ? AND date < ?
            """, (week_ago_str, today_str))
            row = cursor.fetchone()

            # Top debaters for the week
            cursor.execute("""
                SELECT user_id, user_name, SUM(messages) as total_messages,
                       SUM(karma_received) as total_karma
                FROM top_debaters
                WHERE date >= ? AND date < ?
                GROUP BY user_id
                ORDER BY total_messages DESC
                LIMIT 10
            """, (week_ago_str, today_str))
            top_debaters = cursor.fetchall()

            conn.close()

            return {
                "start_date": week_ago_str,
                "end_date": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                "debates_created": row[0] or 0,
                "messages_in_debates": row[1] or 0,
                "upvotes_given": row[2] or 0,
                "downvotes_given": row[3] or 0,
                "news_posted": row[4] or 0,
                "soccer_posted": row[5] or 0,
                "gaming_posted": row[6] or 0,
                "commands_used": row[7] or 0,
                "top_debaters": top_debaters,
            }

        except Exception as e:
            logger.warning("Weekly Stats Query Failed", [("Error", str(e))])
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

        # Debates section
        if stats["debates_created"] > 0 or stats["messages_in_debates"] > 0:
            fields.append({
                "name": "💬 Debates",
                "value": f"Created: `{stats['debates_created']}` | Messages: `{stats['messages_in_debates']}`",
                "inline": True
            })

        # Karma section
        total_votes = stats["upvotes_given"] + stats["downvotes_given"]
        if total_votes > 0:
            fields.append({
                "name": "⬆️ Karma",
                "value": f"Upvotes: `{stats['upvotes_given']}` | Downvotes: `{stats['downvotes_given']}`",
                "inline": True
            })

        # News section
        total_posts = stats["news_posted"] + stats["soccer_posted"] + stats["gaming_posted"]
        if total_posts > 0:
            fields.append({
                "name": "📰 Content Posted",
                "value": f"News: `{stats['news_posted']}` | Soccer: `{stats['soccer_posted']}` | Gaming: `{stats['gaming_posted']}`",
                "inline": False
            })

        # Commands section
        if stats["commands_used"] > 0:
            cmd_list = ", ".join([f"`/{cmd}` ({count})" for cmd, count in stats["top_commands"][:5]])
            fields.append({
                "name": "⚡ Commands Used",
                "value": f"Total: `{stats['commands_used']}`\n{cmd_list}" if cmd_list else f"Total: `{stats['commands_used']}`",
                "inline": False
            })

        # Top debaters
        if stats["top_debaters"]:
            top_list = "\n".join([
                f"**{i+1}.** {name} - `{msgs}` msgs, `{karma:+}` karma"
                for i, (user_id, name, msgs, karma, debates) in enumerate(stats["top_debaters"][:5])
            ])
            fields.append({
                "name": "🏆 Top Debaters",
                "value": top_list,
                "inline": False
            })

        # Moderation
        if stats["users_banned"] > 0 or stats["users_unbanned"] > 0:
            fields.append({
                "name": "🛡️ Moderation",
                "value": f"Banned: `{stats['users_banned']}` | Unbanned: `{stats['users_unbanned']}`",
                "inline": True
            })

        embed = {
            "title": "📊 OthmanBot - Daily Stats",
            "description": f"**Date:** {date}",
            "color": COLOR_BLUE,
            "fields": fields,
            "timestamp": datetime.now(NY_TZ).isoformat(),
            "footer": {"text": "OthmanBot Daily Summary"}
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json={"embeds": [embed]},
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 204:
                        logger.success("Daily Stats Webhook Sent", [
                            ("Date", date),
                            ("Debates", str(stats["debates_created"])),
                            ("Messages", str(stats["messages_in_debates"])),
                        ])
                    else:
                        logger.error("Stats Webhook Failed", [("Status", str(response.status))])
        except Exception as e:
            logger.error("Stats Webhook Error", [("Error", str(e))])

    async def send_weekly_summary(self) -> None:
        """Send weekly stats summary to webhook."""
        if not self.webhook_url:
            return

        weekly = self.get_weekly_stats()
        if not weekly:
            return

        # Build fields
        fields = [
            {
                "name": "💬 Debates",
                "value": f"Created: `{weekly['debates_created']}` | Messages: `{weekly['messages_in_debates']}`",
                "inline": True
            },
            {
                "name": "⬆️ Karma",
                "value": f"Upvotes: `{weekly['upvotes_given']}` | Downvotes: `{weekly['downvotes_given']}`",
                "inline": True
            },
        ]

        # News section
        total_posts = weekly["news_posted"] + weekly["soccer_posted"] + weekly["gaming_posted"]
        if total_posts > 0:
            fields.append({
                "name": "📰 Content Posted",
                "value": f"News: `{weekly['news_posted']}` | Soccer: `{weekly['soccer_posted']}` | Gaming: `{weekly['gaming_posted']}`",
                "inline": False
            })

        # Top debaters
        if weekly["top_debaters"]:
            top_list = "\n".join([
                f"**{i+1}.** {name} - `{msgs}` msgs, `{karma:+}` karma"
                for i, (user_id, name, msgs, karma) in enumerate(weekly["top_debaters"][:5])
            ])
            fields.append({
                "name": "🏆 Top Debaters This Week",
                "value": top_list,
                "inline": False
            })

        embed = {
            "title": "📊 OthmanBot - Weekly Stats",
            "description": f"**Period:** {weekly['start_date']} to {weekly['end_date']}",
            "color": COLOR_GREEN,
            "fields": fields,
            "timestamp": datetime.now(NY_TZ).isoformat(),
            "footer": {"text": "OthmanBot Weekly Summary"}
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json={"embeds": [embed]},
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 204:
                        logger.success("Weekly Stats Webhook Sent", [
                            ("Period", f"{weekly['start_date']} to {weekly['end_date']}"),
                        ])
                    else:
                        logger.error("Weekly Stats Webhook Failed", [("Status", str(response.status))])
        except Exception as e:
            logger.error("Weekly Stats Webhook Error", [("Error", str(e))])

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
                        ("Next Run", tomorrow.strftime('%Y-%m-%d %I:%M %p NY_TZ')),
                        ("Wait", f"{int(wait_seconds)}s"),
                    ])

                    await asyncio.sleep(wait_seconds)

                    # Send daily summary for yesterday
                    yesterday = (datetime.now(NY_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
                    await self.send_daily_summary(yesterday)

                    # If it's Sunday, send weekly summary
                    if datetime.now(NY_TZ).weekday() == 6:
                        await self.send_weekly_summary()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Stats Scheduler Error", [("Error", str(e))])
                    await asyncio.sleep(STATUS_CHECK_INTERVAL)

        self._scheduler_task = asyncio.create_task(scheduler_loop())
        logger.info("Stats Scheduler Started", [
            ("Schedule", "Midnight NY_TZ daily"),
            ("Weekly", "Sunday midnight"),
        ])

    def stop_scheduler(self) -> None:
        """Stop the midnight stats scheduler."""
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DailyStatsService"]
