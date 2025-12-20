"""
Othman Discord Bot - Database Backup System
============================================

Automated SQLite database backup with daily rotation and retention policy.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.core.logger import logger
from src.core.config import NY_TZ

# =============================================================================
# Constants
# =============================================================================

BACKUP_DIR = Path("data/backups")
DATABASE_PATH = Path("data/othman.db")
BACKUP_RETENTION_DAYS = 7
BACKUP_HOUR_EST = 0  # Midnight EST (same as TahaBot)
KB_DIVISOR = 1024
SECONDS_PER_HOUR = 3600


# =============================================================================
# Backup Functions
# =============================================================================

def create_backup() -> Optional[Path]:
    """
    Create a backup of the SQLite database.

    Uses shutil.copy2 to preserve metadata.
    Names backup with timestamp: othman_YYYY-MM-DD_HH-MM-SS.db

    Returns:
        Path to backup file, or None if backup failed
    """
    if not DATABASE_PATH.exists():
        logger.warning("Database Backup Skipped", [
            ("Reason", "Database file does not exist"),
            ("Path", str(DATABASE_PATH)),
        ])
        return None

    # Ensure backup directory exists
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Generate backup filename with timestamp
    timestamp = datetime.now(NY_TZ).strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"othman_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_filename

    try:
        # Copy database file (WAL mode handles this safely)
        shutil.copy2(DATABASE_PATH, backup_path)

        # Get file sizes for logging
        backup_size = backup_path.stat().st_size

        logger.tree("Database Backup Created", [
            ("Backup", backup_filename),
            ("Size", f"{backup_size / KB_DIVISOR:.1f} KB"),
            ("Location", str(BACKUP_DIR)),
        ], emoji="💾")

        return backup_path

    except Exception as e:
        logger.error("Database Backup Failed", [
            ("Error", str(e)),
            ("Path", str(DATABASE_PATH)),
        ])
        return None


def cleanup_old_backups() -> int:
    """
    Remove backups older than BACKUP_RETENTION_DAYS.

    Returns:
        Number of backups removed
    """
    if not BACKUP_DIR.exists():
        return 0

    cutoff_date = datetime.now(NY_TZ) - timedelta(days=BACKUP_RETENTION_DAYS)
    removed_count = 0

    for backup_file in BACKUP_DIR.glob("othman_*.db"):
        try:
            # Extract date from filename: othman_YYYY-MM-DD_HH-MM-SS.db
            # More robust parsing with regex validation
            filename = backup_file.stem  # othman_YYYY-MM-DD_HH-MM-SS
            parts = filename.split("_")

            # Validate format: should have at least 3 parts (othman, date, time)
            if len(parts) < 2 or parts[0] != "othman":
                logger.debug("Skipping Non-Standard Backup File", [
                    ("File", backup_file.name),
                    ("Reason", "Invalid filename format"),
                ])
                continue

            date_str = parts[1]  # YYYY-MM-DD

            # Validate date format
            if len(date_str) != 10 or date_str.count("-") != 2:
                logger.debug("Skipping Backup With Invalid Date", [
                    ("File", backup_file.name),
                    ("Date String", date_str),
                ])
                continue

            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            file_date = file_date.replace(tzinfo=NY_TZ)

            if file_date < cutoff_date:
                backup_file.unlink()
                removed_count += 1
                logger.debug("Removed Old Backup", [
                    ("File", backup_file.name),
                    ("Age", f">{BACKUP_RETENTION_DAYS} days"),
                ])

        except ValueError as e:
            logger.debug("Skipping Backup Parse Error", [
                ("File", backup_file.name),
                ("Error", str(e)),
            ])
            continue
        except OSError as e:
            logger.warning("Failed To Remove Backup", [
                ("File", backup_file.name),
                ("Error", str(e)),
            ])
            continue

    if removed_count > 0:
        logger.info("Old Backups Cleaned Up", [
            ("Removed", str(removed_count)),
            ("Retention", f"{BACKUP_RETENTION_DAYS} days"),
        ])

    return removed_count


def list_backups() -> list[dict]:
    """
    List all available backups with their metadata.

    Returns:
        List of dicts with backup info (path, size, date)
    """
    if not BACKUP_DIR.exists():
        return []

    backups = []
    for backup_file in sorted(BACKUP_DIR.glob("othman_*.db"), reverse=True):
        try:
            stat = backup_file.stat()
            backups.append({
                "path": backup_file,
                "name": backup_file.name,
                "size_kb": stat.st_size / KB_DIVISOR,
                "created": datetime.fromtimestamp(stat.st_mtime, tz=NY_TZ),
            })
        except OSError:
            continue

    return backups


def get_latest_backup() -> Optional[Path]:
    """
    Get the most recent backup file.

    Returns:
        Path to latest backup, or None if no backups exist
    """
    backups = list_backups()
    return backups[0]["path"] if backups else None


# =============================================================================
# Backup Scheduler
# =============================================================================

class BackupScheduler:
    """
    Schedules daily database backups at a specific time.

    DESIGN: Runs backup at midnight EST daily.
    Also cleans up old backups after each backup.
    """

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, run_immediately: bool = True) -> None:
        """
        Start the backup scheduler.

        Args:
            run_immediately: If True, create a backup if none exists for today
        """
        if self._running:
            return

        self._running = True

        # Only backup on startup if no backup exists for today
        if run_immediately and not self._has_backup_today():
            await asyncio.to_thread(create_backup)

        # Always cleanup old backups on startup
        await asyncio.to_thread(cleanup_old_backups)

        # Start the scheduler loop
        self._task = asyncio.create_task(self._scheduler_loop())

        logger.tree("Backup Scheduler Started", [
            ("Schedule", f"Daily at {BACKUP_HOUR_EST}:00 AM EST"),
            ("Retention", f"{BACKUP_RETENTION_DAYS} days"),
        ], emoji="💾")

    async def stop(self) -> None:
        """Stop the backup scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop - runs daily at configured time."""
        while self._running:
            try:
                # Calculate seconds until next backup time
                seconds_until_backup = self._seconds_until_next_backup()

                # Wait until backup time
                await asyncio.sleep(seconds_until_backup)

                if not self._running:
                    break

                # Run backup
                await asyncio.to_thread(create_backup)
                await asyncio.to_thread(cleanup_old_backups)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Backup Scheduler Error", [
                    ("Error", str(e)),
                ])
                # Wait 1 hour before retrying on error
                await asyncio.sleep(SECONDS_PER_HOUR)

    def _seconds_until_next_backup(self) -> float:
        """Calculate seconds until next scheduled backup time."""
        now = datetime.now(NY_TZ)
        target = now.replace(hour=BACKUP_HOUR_EST, minute=0, second=0, microsecond=0)

        # If we've passed today's backup time, schedule for tomorrow
        if now >= target:
            target += timedelta(days=1)

        return (target - now).total_seconds()

    def _has_backup_today(self) -> bool:
        """Check if a backup already exists for today."""
        if not BACKUP_DIR.exists():
            return False

        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
        for backup_file in BACKUP_DIR.glob(f"othman_{today}_*.db"):
            return True
        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "create_backup",
    "cleanup_old_backups",
    "list_backups",
    "get_latest_backup",
    "BackupScheduler",
    "BACKUP_DIR",
    "DATABASE_PATH",
    "BACKUP_RETENTION_DAYS",
]
