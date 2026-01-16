"""
One-time script to delete debate threads where the starter message was deleted.

These are orphaned threads with no original content to debate.

Run with: python scripts/delete_orphaned_threads.py

Author: Claude Code
"""

import asyncio
import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Load .env BEFORE importing config
from dotenv import load_dotenv
env_path = os.path.join(project_root, ".env")
load_dotenv(env_path)

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import DEBATES_FORUM_ID
from src.services.debates.database import DebatesDatabase


# Rate limiting delays
THREAD_CHECK_DELAY = 0.5
THREAD_DELETE_DELAY = 1.0


async def find_and_delete_orphaned_threads(bot: commands.Bot) -> dict:
    """
    Find and delete threads where the starter message was deleted.

    Returns:
        Dict with stats about the operation
    """
    stats = {
        "threads_checked": 0,
        "orphaned_found": 0,
        "threads_deleted": 0,
        "errors": 0,
    }

    # Initialize database
    db = DebatesDatabase()

    # Get debates forum
    debates_forum = bot.get_channel(DEBATES_FORUM_ID)
    if not debates_forum:
        logger.error("Debates forum not found", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
        ])
        return stats

    logger.tree("Starting Orphaned Thread Cleanup", [
        ("Forum", debates_forum.name),
        ("Forum ID", str(DEBATES_FORUM_ID)),
    ], emoji="🧹")

    # Get Open Discussion thread ID to skip it
    open_discussion_thread_id = db.get_open_discussion_thread_id()

    # Collect orphaned threads
    orphaned_threads = []

    for thread in debates_forum.threads:
        stats["threads_checked"] += 1

        # Skip already closed/deprecated threads
        if thread.name.startswith("[CLOSED]") or thread.name.startswith("[DEPRECATED]"):
            continue

        # Skip Open Discussion thread
        if open_discussion_thread_id and thread.id == open_discussion_thread_id:
            continue

        # Check if starter message exists
        try:
            starter_message = thread.starter_message
            if starter_message is None:
                # Try to fetch it
                try:
                    starter_message = await thread.fetch_message(thread.id)
                except discord.NotFound:
                    # Starter message was deleted - this is an orphaned thread
                    orphaned_threads.append(thread)
                    stats["orphaned_found"] += 1
                    logger.tree("Found Orphaned Thread", [
                        ("Thread", thread.name[:50]),
                        ("ID", str(thread.id)),
                    ], emoji="🗑️")

            await asyncio.sleep(THREAD_CHECK_DELAY)

        except discord.NotFound:
            # Thread or message not found
            orphaned_threads.append(thread)
            stats["orphaned_found"] += 1
        except Exception as e:
            logger.warning("Error checking thread", [
                ("Thread", thread.name[:40]),
                ("Error", str(e)[:50]),
            ])
            stats["errors"] += 1

    logger.tree("Orphaned Threads Found", [
        ("Count", str(len(orphaned_threads))),
        ("Threads Checked", str(stats["threads_checked"])),
    ], emoji="📋")

    if not orphaned_threads:
        logger.tree("No Orphaned Threads to Delete", [], emoji="✅")
        return stats

    # Delete orphaned threads
    for thread in orphaned_threads:
        try:
            thread_name = thread.name
            thread_id = thread.id

            await thread.delete()
            stats["threads_deleted"] += 1

            logger.tree("Deleted Orphaned Thread", [
                ("Thread", thread_name[:50]),
                ("ID", str(thread_id)),
            ], emoji="🗑️")

            # Clean up database entries for this thread
            try:
                db.delete_thread_data(thread_id)
            except Exception:
                pass  # Best effort cleanup

            await asyncio.sleep(THREAD_DELETE_DELAY)

        except discord.Forbidden:
            logger.warning("Cannot delete thread (no permission)", [
                ("Thread", thread.name[:40]),
            ])
            stats["errors"] += 1
        except discord.NotFound:
            # Already deleted
            stats["threads_deleted"] += 1
        except Exception as e:
            logger.warning("Failed to delete thread", [
                ("Thread", thread.name[:40]),
                ("Error", str(e)[:50]),
            ])
            stats["errors"] += 1

    # Final summary
    logger.tree("Orphaned Thread Cleanup Complete", [
        ("Threads Checked", str(stats["threads_checked"])),
        ("Orphaned Found", str(stats["orphaned_found"])),
        ("Threads Deleted", str(stats["threads_deleted"])),
        ("Errors", str(stats["errors"])),
    ], emoji="✅")

    return stats


async def main():
    """Main entry point for the script."""
    token = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set in .env")
        sys.exit(1)

    # Create minimal bot just for this operation
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"Bot connected as {bot.user}")
        print(f"Finding and deleting orphaned threads...")

        try:
            stats = await find_and_delete_orphaned_threads(bot)
            print(f"\nOperation complete!")
            print(f"  Threads checked: {stats['threads_checked']}")
            print(f"  Orphaned found: {stats['orphaned_found']}")
            print(f"  Threads deleted: {stats['threads_deleted']}")
            print(f"  Errors: {stats['errors']}")
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await bot.close()

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
