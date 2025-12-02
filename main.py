"""
Othman Discord Bot - Main Entry Point
======================================

Application entry point with single-instance enforcement and graceful startup.

This module handles:
- Single-instance lock acquisition (prevents duplicate bots)
- Environment configuration loading
- Graceful error handling and logging
- Bot initialization and execution

Usage:
    python main.py

    Or with a process manager:
    nohup python main.py > /dev/null 2>&1 &

Environment Variables:
    DISCORD_TOKEN: Required. Discord bot authentication token.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import sys
import fcntl
import tempfile
from pathlib import Path
from typing import NoReturn

from dotenv import load_dotenv

from src.core.logger import logger
from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

LOCK_FILE_PATH = Path(tempfile.gettempdir()) / "othman_bot.lock"
"""Path to the lock file used for single-instance enforcement."""


# =============================================================================
# Single Instance Lock
# =============================================================================

def acquire_lock() -> int:
    """
    Acquire an exclusive file lock to ensure only one bot instance runs.

    Uses fcntl.flock() for atomic lock acquisition. The lock is automatically
    released when the process terminates (even on crash), preventing stale locks.

    Returns:
        File descriptor of the lock file (kept open for lock lifetime).

    Raises:
        SystemExit: If another instance is already running.

    Example:
        >>> lock_fd = acquire_lock()
        >>> # Bot runs with lock held
        >>> # Lock automatically released on exit
    """
    try:
        # Create or open lock file
        fd = os.open(str(LOCK_FILE_PATH), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        logger.error(f"Failed to open lock file {LOCK_FILE_PATH}: {e}")
        sys.exit(1)

    try:
        # Attempt non-blocking exclusive lock
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Lock acquired - write our PID
        os.truncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())

        logger.info(f"Lock acquired successfully (PID: {os.getpid()})")
        return fd

    except (IOError, OSError):
        # Lock held by another process - check if it's stale
        if _is_stale_lock(fd):
            # Stale lock - try to clean up and acquire
            os.close(fd)
            try:
                LOCK_FILE_PATH.unlink()
                logger.warning("Removed stale lock file from dead process")
                return acquire_lock()  # Retry
            except OSError:
                pass

        _report_existing_instance(fd)
        os.close(fd)
        sys.exit(1)


def _is_stale_lock(fd: int) -> bool:
    """
    Check if the lock is stale (process no longer running).

    Args:
        fd: File descriptor of the lock file.

    Returns:
        True if the PID in the lock file is not running.
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        pid_str = os.read(fd, 100).decode().strip()

        if not pid_str:
            return False

        pid = int(pid_str)

        # Check if process exists (signal 0 doesn't kill, just checks)
        os.kill(pid, 0)
        return False  # Process exists

    except (OSError, ValueError):
        # Process doesn't exist or invalid PID
        return True


def _report_existing_instance(fd: int) -> None:
    """
    Log information about the existing bot instance holding the lock.

    Args:
        fd: File descriptor of the lock file.
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        existing_pid = os.read(fd, 100).decode().strip()

        if existing_pid:
            logger.error(
                f"Another instance is already running (PID: {existing_pid}). "
                f"Kill it with: kill {existing_pid}"
            )
        else:
            logger.error("Another instance is already running (PID unknown)")

    except (OSError, ValueError) as e:
        logger.error(f"Another instance is already running (could not read PID: {e})")


# =============================================================================
# Configuration
# =============================================================================

def load_configuration() -> str:
    """
    Load and validate environment configuration.

    Loads variables from .env file and validates required settings.

    Returns:
        Discord bot token.

    Raises:
        SystemExit: If required configuration is missing.
    """
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN")

    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables")
        logger.error("Please create a .env file with: DISCORD_TOKEN=your_token_here")
        sys.exit(1)

    # Log configuration status (without sensitive data)
    logger.info("Configuration loaded successfully")

    return token


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> NoReturn:
    """
    Main entry point for the Othman Discord bot.

    Execution flow:
    1. Acquire single-instance lock
    2. Load environment configuration
    3. Initialize and start bot
    4. Handle shutdown gracefully

    Raises:
        SystemExit: On startup failure or clean shutdown.
    """
    # Step 1: Ensure single instance
    lock_fd = acquire_lock()

    # Step 2: Load configuration
    token = load_configuration()

    # Step 3: Initialize and run bot
    try:
        logger.tree(
            "Starting Othman News Bot",
            [
                ("Purpose", "Automated Middle East News"),
                ("Features", "Live scores, news, gaming updates"),
                ("Lock File", str(LOCK_FILE_PATH)),
                ("PID", str(os.getpid())),
            ],
            emoji="📰",
        )

        bot = OthmanBot()
        bot.run(token)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user (Ctrl+C)")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error during bot execution: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)

    finally:
        # Explicitly close lock file descriptor for clarity
        if 'lock_fd' in locals():
            try:
                os.close(lock_fd)
            except OSError:
                pass
        logger.info("Bot shutdown complete")


# =============================================================================
# Script Execution
# =============================================================================

if __name__ == "__main__":
    main()
