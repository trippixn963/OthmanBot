"""
OthmanBot - Logger
==================

Custom logging system with tree-style formatting and EST timezone support.
Provides structured logging for Discord bot events with visual formatting
and file output for debugging and monitoring.

Features:
- Unique run ID generation for tracking bot sessions
- EST/EDT timezone timestamp formatting (auto-adjusts)
- Tree-style log formatting for structured data
- Nested tree support for hierarchical data
- Console and file output simultaneously
- Daily log folders with separate log and error files
- Automatic cleanup of old logs (7+ days)
- Live logs streaming to Discord webhook in tree format
- Separate error webhook for error-only logs

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import re
import shutil
import uuid
import traceback
import asyncio
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Any, Dict
from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

# Timezone for timestamps
TIMEZONE = ZoneInfo("America/New_York")

# Log retention period in days
LOG_RETENTION_DAYS = 7

# Regex to match emojis (for stripping from file logs)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended
    "\U00002300-\U000023FF"  # misc technical
    "]+",
    flags=re.UNICODE
)


# =============================================================================
# Tree Symbols
# =============================================================================

class TreeSymbols:
    """Box-drawing characters for tree formatting."""
    BRANCH = "├─"      # Middle item connector
    LAST = "└─"        # Last item connector
    PIPE = "│ "        # Vertical continuation
    SPACE = "  "       # Empty space for alignment


# =============================================================================
# Logger
# =============================================================================

class Logger:
    """Custom logger with tree-style formatting and webhook streaming."""

    # Error emojis that should route to error webhook
    ERROR_EMOJIS = {"❌", "⚠️", "🚨", "💥"}

    def __init__(self) -> None:
        """Initialize the logger with unique run ID and daily log folder rotation."""
        # Unique run ID for this session
        self.run_id: str = str(uuid.uuid4())[:8]

        # Track last log type for spacing between trees
        self._last_was_tree: bool = False

        # Live logs Discord webhook streaming (from env var)
        self._live_logs_webhook_url: str = os.getenv("LOG_WEBHOOK_URL", "")
        self._live_logs_enabled: bool = bool(self._live_logs_webhook_url)

        # Error webhook (from env var)
        self._error_webhook_url: str = os.getenv("ERROR_WEBHOOK_URL", "")

        # Base logs directory
        self.logs_base_dir = Path(__file__).parent.parent.parent / "logs"
        self.logs_base_dir.mkdir(exist_ok=True)

        # Get current date in EST timezone
        self.current_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

        # Create daily folder (e.g., logs/2025-12-06/)
        self.log_dir = self.logs_base_dir / self.current_date
        self.log_dir.mkdir(exist_ok=True)

        # Create log files inside daily folder
        self.log_file: Path = self.log_dir / f"Othman-{self.current_date}.log"
        self.error_file: Path = self.log_dir / f"Othman-Errors-{self.current_date}.log"

        # Clean up old log folders (older than 7 days)
        self._cleanup_old_logs()

        # Write session header
        self._write_session_header()

    # =========================================================================
    # Private Methods - Setup
    # =========================================================================

    def _cleanup_old_logs(self) -> None:
        """Clean up log folders older than retention period (7 days)."""
        try:
            now = datetime.now(TIMEZONE)
            cutoff_date = now - timedelta(days=LOG_RETENTION_DAYS)
            deleted_count = 0

            for folder in self.logs_base_dir.glob("????-??-??"):
                if not folder.is_dir():
                    continue

                try:
                    folder_date = datetime.strptime(folder.name, "%Y-%m-%d")
                    folder_date = folder_date.replace(tzinfo=TIMEZONE)

                    if folder_date < cutoff_date:
                        shutil.rmtree(folder)
                        deleted_count += 1
                except ValueError:
                    continue

            if deleted_count > 0:
                print(f"[LOG CLEANUP] Deleted {deleted_count} old log folders (>{LOG_RETENTION_DAYS} days)")
        except Exception as e:
            print(f"[LOG CLEANUP ERROR] {type(e).__name__}: {e}")

    def _check_date_rotation(self) -> None:
        """Check if date has changed and rotate to new log folder if needed."""
        current_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

        if current_date != self.current_date:
            self.current_date = current_date
            self.log_dir = self.logs_base_dir / self.current_date
            self.log_dir.mkdir(exist_ok=True)
            self.log_file = self.log_dir / f"Othman-{self.current_date}.log"
            self.error_file = self.log_dir / f"Othman-Errors-{self.current_date}.log"

            header = (
                f"\n{'='*60}\n"
                f"LOG ROTATION - Continuing session {self.run_id}\n"
                f"{self._get_timestamp()}\n"
                f"{'='*60}\n\n"
            )
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(header)
                with open(self.error_file, "a", encoding="utf-8") as f:
                    f.write(header)
            except (OSError, IOError):
                pass

    def _write_session_header(self) -> None:
        """Write session header to both log file and error log file."""
        header = (
            f"\n{'='*60}\n"
            f"NEW SESSION - RUN ID: {self.run_id}\n"
            f"{self._get_timestamp()}\n"
            f"{'='*60}\n\n"
        )
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(header)
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(header)
        except (OSError, IOError):
            pass

    # =========================================================================
    # Private Methods - Formatting
    # =========================================================================

    def _get_timestamp(self) -> str:
        """Get current timestamp in Eastern timezone (auto EST/EDT)."""
        try:
            current_time = datetime.now(TIMEZONE)
            tz_name = current_time.strftime("%Z")
            return f"[{current_time.strftime('%I:%M:%S %p')} {tz_name}]"
        except Exception:
            return datetime.now().strftime("[%I:%M:%S %p]")

    def _strip_emojis(self, text: str) -> str:
        """Remove emojis from text to avoid duplicate emojis in output."""
        return EMOJI_PATTERN.sub("", text).strip()

    def _format_tree(self, items: List[Tuple[str, Any]]) -> str:
        """Format items as a tree."""
        if not items:
            return ""
        lines = []
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            lines.append(f"  {prefix} {key}: {value}")
        return "\n".join(lines)

    # =========================================================================
    # Private Methods - File Writing
    # =========================================================================

    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write log message to both console and file."""
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    def _write_raw(self, message: str, also_to_error: bool = False) -> None:
        """Write raw message without timestamp (for tree branches)."""
        print(message)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{message}\n")
            if also_to_error:
                with open(self.error_file, "a", encoding="utf-8") as f:
                    f.write(f"{message}\n")
        except (OSError, IOError):
            pass

    def _write_to_file_only(self, message: str) -> None:
        """Write to log file only (no console, no webhook - avoids recursion)."""
        self._check_date_rotation()
        timestamp = self._get_timestamp()
        full_message = f"{timestamp} {message}"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    def _write_error(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write error message to both main log and error log file."""
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    # =========================================================================
    # Live Logs - Discord Webhook Streaming
    # =========================================================================

    def _send_live_log(self, formatted_tree: str) -> None:
        """Send a single tree log to Discord webhook immediately."""
        if not self._live_logs_enabled:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_send_live_log(formatted_tree))
        except RuntimeError:
            # No event loop running yet
            pass

    async def _async_send_live_log(self, formatted_tree: str) -> None:
        """Send a single tree log to Discord webhook."""
        payload = {
            "content": f"```\n{formatted_tree}\n```",
            "username": "OthmanBot Logs",
        }
        try:
            await self._async_send_webhook(payload, self._live_logs_webhook_url)
        except Exception:
            pass

    def _send_error_webhook(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌"
    ) -> None:
        """Send error to dedicated error webhook as tree format."""
        if not self._error_webhook_url:
            return

        formatted = self._format_tree_for_live(title, items, emoji)
        payload = {
            "content": f"```\n{formatted}\n```",
            "username": "OthmanBot Errors",
        }

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_send_webhook(payload, self._error_webhook_url))
        except RuntimeError:
            pass

    async def _async_send_webhook(self, payload: dict, webhook_url: str) -> None:
        """Send webhook payload asynchronously."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status >= 400:
                        self._write_to_file_only(
                            f"[WEBHOOK] HTTP {response.status} sending to webhook"
                        )
        except asyncio.TimeoutError:
            self._write_to_file_only("[WEBHOOK] Timeout sending to webhook")
        except aiohttp.ClientError as e:
            self._write_to_file_only(f"[WEBHOOK] Client error: {type(e).__name__}")
        except Exception as e:
            self._write_to_file_only(f"[WEBHOOK] Error: {type(e).__name__}: {e}")

    def _format_tree_for_live(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "📦"
    ) -> str:
        """Format a tree log for the live buffer."""
        timestamp = self._get_timestamp()
        lines = [f"{timestamp} {emoji} {self._strip_emojis(title)}"]

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            lines.append(f"  {prefix} {key}: {value}")

        return "\n".join(lines)

    # =========================================================================
    # Private Methods - Tree Error Logging
    # =========================================================================

    def _tree_error(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌",
    ) -> None:
        """Log structured error data in tree format to both log files and live logs."""
        if not self._last_was_tree:
            self._write_raw("", also_to_error=True)

        self._write_error(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}", also_to_error=True)

        self._write_raw("", also_to_error=True)
        self._last_was_tree = True

        # Send to live logs Discord webhook
        formatted = self._format_tree_for_live(title, items, emoji)
        self._send_live_log(formatted)

        # Also send to dedicated error webhook
        self._send_error_webhook(title, items, emoji)

    # =========================================================================
    # Public Methods - Log Levels
    # =========================================================================

    def info(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an informational message."""
        if details:
            self.tree(message, details, emoji="ℹ️")
        else:
            self._write(message, "ℹ️")
            self._last_was_tree = False

    def success(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a success message."""
        if details:
            self.tree(message, details, emoji="✅")
        else:
            self._write(message, "✅")
            self._last_was_tree = False

    def error(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an error message (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="❌")
        else:
            self._write_error(message, "❌")
            self._last_was_tree = False

    def warning(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a warning message (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="⚠️")
        else:
            self._write_error(message, "⚠️")
            self._last_was_tree = False

    def debug(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a debug message (only if DEBUG env var is set)."""
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            if details:
                self.tree(message, details, emoji="🔍")
            else:
                self._write(message, "🔍")
                self._last_was_tree = False

    def critical(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a critical/fatal error message (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="🚨")
        else:
            self._write_error(message, "🚨")
            self._last_was_tree = False

    def exception(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an exception with full traceback (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="💥")
        else:
            self._write_error(message, "💥")
        try:
            tb = traceback.format_exc()
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
        except (OSError, IOError):
            pass

    # =========================================================================
    # Public Methods - Tree Formatting
    # =========================================================================

    def tree(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "📦"
    ) -> None:
        """
        Log structured data in tree format.

        Example output:

            [12:00:00 PM EST] 📦 Bot Ready
              ├─ Bot ID: 123456789
              ├─ Guilds: 5
              └─ Latency: 50ms

        Args:
            title: Tree title/header
            items: List of (key, value) tuples
            emoji: Emoji prefix for title
        """
        # Check if this is an error-level log based on emoji
        is_error = emoji in self.ERROR_EMOJIS

        if is_error:
            self._tree_error(title, items, emoji)
            return

        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}")

        self._write_raw("")
        self._last_was_tree = True

        # Send to live logs Discord webhook
        formatted = self._format_tree_for_live(title, items, emoji)
        self._send_live_log(formatted)

    def tree_nested(
        self,
        title: str,
        data: Dict[str, Any],
        emoji: str = "📦",
        indent: int = 0
    ) -> None:
        """Log nested/hierarchical data in tree format."""
        if indent == 0:
            if not self._last_was_tree:
                self._write_raw("")
            self._write(title, emoji)

        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            indent_str = "  " * (indent + 1)

            if isinstance(value, dict):
                self._write_raw(f"{indent_str}{prefix} {key}")
                self._render_nested(value, indent + 1, is_last)
            else:
                self._write_raw(f"{indent_str}{prefix} {key}: {value}")

        if indent == 0:
            self._write_raw("")
            self._last_was_tree = True

    def _render_nested(self, data: Dict[str, Any], indent: int, parent_is_last: bool) -> None:
        """Recursively render nested tree data."""
        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            indent_str = "  " * indent

            if isinstance(value, dict):
                self._write_raw(f"{indent_str}  {prefix} {key}")
                self._render_nested(value, indent + 1, is_last)
            else:
                self._write_raw(f"{indent_str}  {prefix} {key}: {value}")

    def tree_list(
        self,
        title: str,
        items: List[str],
        emoji: str = "📋"
    ) -> None:
        """Log a simple list in tree format."""
        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {item}")

        self._write_raw("")
        self._last_was_tree = True

    def error_tree(
        self,
        title: str,
        error: Exception,
        context: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """Log an error with context in tree format."""
        items: List[Tuple[str, Any]] = [
            ("Type", type(error).__name__),
            ("Message", str(error)),
        ]

        if context:
            items.extend(context)

        self._tree_error(title, items, emoji="❌")

    def startup_tree(
        self,
        bot_name: str,
        bot_id: int,
        guilds: int,
        latency: float,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """Log bot startup information in tree format."""
        items: List[Tuple[str, Any]] = [
            ("Bot ID", bot_id),
            ("Guilds", guilds),
            ("Latency", f"{latency:.0f}ms"),
            ("Run ID", self.run_id),
        ]

        if extra:
            items.extend(extra)

        self.tree(f"Bot Ready: {bot_name}", items, emoji="🤖")


# =============================================================================
# Module Export
# =============================================================================

# Create singleton instance
logger = Logger()

# Backwards compatibility alias
log = logger

__all__ = ["logger", "log", "Logger", "TreeSymbols"]
