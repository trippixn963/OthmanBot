"""
Othman Discord Bot - Logger
============================

Custom logging system with tree-style formatting and EST timezone support.
Provides structured logging for Discord bot events with visual formatting
and file output for debugging and monitoring.

Features:
- Unique run ID generation for tracking bot sessions
- EST/EDT timezone timestamp formatting (auto-adjusts)
- Tree-style log formatting for structured data
- Nested tree support for hierarchical data
- Console and file output simultaneously
- Emoji-enhanced log levels for visual clarity
- Daily log folders with separate log and error files
- Automatic cleanup of old logs (7+ days)

Log Structure:
    logs/
    ├── 2025-12-06/
    │   ├── Othman-2025-12-06.log
    │   └── Othman-Errors-2025-12-06.log
    ├── 2025-12-07/
    │   ├── Othman-2025-12-07.log
    │   └── Othman-Errors-2025-12-07.log
    └── ...

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import re
import shutil
import uuid
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Any, Dict
from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

# Log retention period in days
LOG_RETENTION_DAYS = 7

# Regex to match emojis
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
    HEADER = "┌─"      # Tree header
    FOOTER = "└─"      # Tree footer


# =============================================================================
# MiniTreeLogger
# =============================================================================

class MiniTreeLogger:
    """Custom logger with tree-style formatting and EST timezone support."""

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """Initialize the logger with unique run ID and daily log folder rotation."""
        self.run_id: str = str(uuid.uuid4())[:8]

        # Base logs directory
        self.logs_base_dir = Path(__file__).parent.parent.parent / "logs"
        self.logs_base_dir.mkdir(exist_ok=True)

        # Timezone for date calculations
        self._timezone = ZoneInfo("America/New_York")

        # Get current date in EST timezone
        self.current_date = datetime.now(self._timezone).strftime("%Y-%m-%d")

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

    def _check_date_rotation(self) -> None:
        """Check if date has changed and rotate to new log folder if needed."""
        current_date = datetime.now(self._timezone).strftime("%Y-%m-%d")

        if current_date != self.current_date:
            # Date has changed - rotate to new folder
            self.current_date = current_date
            self.log_dir = self.logs_base_dir / self.current_date
            self.log_dir.mkdir(exist_ok=True)
            self.log_file = self.log_dir / f"Othman-{self.current_date}.log"
            self.error_file = self.log_dir / f"Othman-Errors-{self.current_date}.log"

            # Write continuation header to new log files
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

    def _cleanup_old_logs(self) -> None:
        """Clean up log folders older than retention period (7 days)."""
        try:
            eastern = ZoneInfo("America/New_York")
            now = datetime.now(eastern)
            deleted_count = 0

            # Iterate through date folders in the logs directory
            for folder in self.logs_base_dir.iterdir():
                if not folder.is_dir():
                    continue

                # Skip non-date folders (e.g., .sync-daemon.log)
                folder_name = folder.name
                try:
                    folder_date = datetime.strptime(folder_name, "%Y-%m-%d")
                    folder_date = folder_date.replace(tzinfo=eastern)
                except ValueError:
                    continue

                # Delete folders older than retention period
                days_old = (now - folder_date).days
                if days_old > LOG_RETENTION_DAYS:
                    shutil.rmtree(folder)
                    deleted_count += 1

            if deleted_count > 0:
                print(f"[LOG CLEANUP] Deleted {deleted_count} old log folders (>{LOG_RETENTION_DAYS} days)")
        except Exception as e:
            print(f"[LOG CLEANUP ERROR] {e}")

    def _write_session_header(self) -> None:
        """Write session header to both log file and error log file."""
        header = (
            f"\n{'='*60}\n"
            f"NEW SESSION - RUN ID: {self.run_id}\n"
            f"{self._get_timestamp()}\n"
            f"{'='*60}\n\n"
        )
        try:
            # Write to main log
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(header)
            # Write to error log
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
            eastern = ZoneInfo("America/New_York")
            current_time = datetime.now(eastern)
            tz_name = current_time.strftime("%Z")
            return current_time.strftime(f"[%I:%M:%S %p {tz_name}]")
        except Exception:
            return datetime.now().strftime("[%I:%M:%S %p]")

    def _strip_emojis(self, text: str) -> str:
        """Remove emojis from text to avoid duplicate emojis in output."""
        return EMOJI_PATTERN.sub("", text).strip()

    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write log message to both console and file."""
        # Check if we need to rotate to a new date folder
        self._check_date_rotation()

        # Strip any emojis from the message to avoid duplicates
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

    def _write_error(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write error message to both main log and error log file."""
        # Check if we need to rotate to a new date folder
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        try:
            # Write to main log
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
            # Write to error log
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    def _tree_error(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌"
    ) -> None:
        """Log structured error data in tree format to both log files."""
        self._write_error(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}", also_to_error=True)

        self._write_raw("", also_to_error=True)  # Empty line after tree

    # =========================================================================
    # Public Methods - Log Levels (All output as tree format)
    # =========================================================================

    def info(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an informational message as a tree."""
        if details:
            self.tree(msg, details, emoji="ℹ️")
        else:
            self._write(msg, "ℹ️")
            self._write_raw(f"  {TreeSymbols.LAST} Status: OK")
            self._write_raw("")  # Empty line after tree

    def success(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a success message as a tree."""
        if details:
            self.tree(msg, details, emoji="✅")
        else:
            self._write(msg, "✅")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Complete")
            self._write_raw("")  # Empty line after tree

    def error(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an error message as a tree (also writes to error log)."""
        if details:
            self._tree_error(msg, details, emoji="❌")
        else:
            self._write_error(msg, "❌")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Failed", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree

    def warning(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a warning message as a tree (also writes to error log)."""
        if details:
            self._tree_error(msg, details, emoji="⚠️")
        else:
            self._write_error(msg, "⚠️")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Warning", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree

    def debug(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a debug message (only if DEBUG env var is set)."""
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            if details:
                self.tree(msg, details, emoji="🔍")
            else:
                self._write(msg, "🔍")
                self._write_raw(f"  {TreeSymbols.LAST} Status: Debug")
                self._write_raw("")  # Empty line after tree

    def critical(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a critical/fatal error message as a tree (also writes to error log)."""
        if details:
            self._tree_error(msg, details, emoji="🚨")
        else:
            self._write_error(msg, "🚨")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Critical", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree

    def exception(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an exception with full traceback as a tree (also writes to error log)."""
        if details:
            self._tree_error(msg, details, emoji="💥")
        else:
            self._write_error(msg, "💥")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Exception", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree
        try:
            tb = traceback.format_exc()
            # Write traceback to main log
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
            # Write traceback to error log
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
        self._write(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}")

        self._write_raw("")  # Empty line after tree

    def tree_nested(
        self,
        title: str,
        data: Dict[str, Any],
        emoji: str = "📦",
        indent: int = 0
    ) -> None:
        """
        Log nested/hierarchical data in tree format.

        Example output:
            [12:00:00 PM EST] 📦 Game Session
              ├─ Players
              │   ├─ Player1: John
              │   └─ Player2: Jane
              └─ Settings
                  ├─ Bet: 100
                  └─ Type: tictactoe

        Args:
            title: Tree title/header
            data: Nested dictionary
            emoji: Emoji prefix for title
            indent: Current indentation level
        """
        if indent == 0:
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
            self._write_raw("")  # Empty line after tree

    def _render_nested(self, data: Dict[str, Any], indent: int, parent_is_last: bool) -> None:
        """Recursively render nested tree data."""
        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH

            # Build proper indentation with pipes
            indent_str = ""
            for level in range(indent):
                if level == indent - 1:
                    indent_str += TreeSymbols.SPACE if parent_is_last else TreeSymbols.PIPE
                else:
                    indent_str += "  "
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
        """
        Log a simple list in tree format.

        Example output:
            [12:00:00 PM EST] 📋 Active Games
              ├─ Game #1234
              ├─ Game #5678
              └─ Game #9012

        Args:
            title: Tree title/header
            items: List of string items
            emoji: Emoji prefix for title
        """
        self._write(title, emoji)

        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {item}")

        self._write_raw("")  # Empty line after tree

    def tree_section(
        self,
        title: str,
        sections: Dict[str, List[Tuple[str, Any]]],
        emoji: str = "📊"
    ) -> None:
        """
        Log multiple sections in tree format.

        Example output:
            [12:00:00 PM EST] 📊 Player Stats
              ├─ Performance
              │   ├─ Wins: 10
              │   └─ Losses: 5
              └─ Economy
                  ├─ Balance: 1000
                  └─ Total Earned: 5000

        Args:
            title: Tree title/header
            sections: Dict of section_name -> [(key, value), ...]
            emoji: Emoji prefix for title
        """
        self._write(title, emoji)

        section_names = list(sections.keys())
        for si, section_name in enumerate(section_names):
            section_is_last = si == len(section_names) - 1
            section_prefix = TreeSymbols.LAST if section_is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {section_prefix} {section_name}")

            items = sections[section_name]
            for ii, (key, value) in enumerate(items):
                item_is_last = ii == len(items) - 1
                item_prefix = TreeSymbols.LAST if item_is_last else TreeSymbols.BRANCH

                # Use pipe continuation for non-last sections
                continuation = TreeSymbols.SPACE if section_is_last else TreeSymbols.PIPE
                self._write_raw(f"  {continuation} {item_prefix} {key}: {value}")

        self._write_raw("")  # Empty line after tree

    def error_tree(
        self,
        title: str,
        error: Exception,
        context: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log an error with context in tree format.

        Example output:
            [12:00:00 PM EST] ❌ Database Error
              ├─ Type: ConnectionError
              ├─ Message: Failed to connect
              ├─ User ID: 123456
              └─ Action: create_game

        Args:
            title: Error title/description
            error: The exception that occurred
            context: Additional context as (key, value) tuples
        """
        items: List[Tuple[str, Any]] = [
            ("Type", type(error).__name__),
            ("Message", str(error)),
        ]

        if context:
            items.extend(context)

        self.tree(title, items, emoji="❌")

    def news_tree(
        self,
        action: str,
        source: str,
        title: str,
        category: str,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log news events in a standardized tree format.

        Example output:
            [12:00:00 PM EST] 📰 News Posted
              ├─ Source: Enab Baladi
              ├─ Title: Breaking news...
              ├─ Category: Politics
              └─ Has Image: Yes

        Args:
            action: What happened (Posted, Fetched, etc.)
            source: News source name
            title: Article title
            category: News category
            extra: Additional context
        """
        items: List[Tuple[str, Any]] = [
            ("Source", source),
            ("Title", title[:50] + "..." if len(title) > 50 else title),
            ("Category", category),
        ]

        if extra:
            items.extend(extra)

        self.tree(action, items, emoji="📰")

    def startup_tree(
        self,
        bot_name: str,
        bot_id: int,
        guilds: int,
        latency: float,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log bot startup information in tree format.

        Args:
            bot_name: Name of the bot
            bot_id: Discord bot ID
            guilds: Number of guilds
            latency: WebSocket latency in ms
            extra: Additional startup info
        """
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

logger = MiniTreeLogger()

__all__ = ["logger", "MiniTreeLogger", "TreeSymbols"]
