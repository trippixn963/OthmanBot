"""
One-time script to reset all debate thread reactions and recalculate karma.

This script will:
1. Clear all reactions from starter messages in open debate threads
2. Add the bot's upvote emoji to each starter message
3. Clear all votes from the database
4. Reset all user karma to 0

Run with: python scripts/reset_debate_reactions.py

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
from src.core.emojis import UPVOTE_EMOJI
from src.services.debates.database import DebatesDatabase

print(f"DEBATES_FORUM_ID from config: {DEBATES_FORUM_ID}")


# Rate limiting delays
REACTION_CLEAR_DELAY = 1.0  # Delay between clearing reactions per message
THREAD_DELAY = 0.5  # Delay between processing threads


async def reset_debate_reactions(bot: commands.Bot) -> dict:
    """
    Reset all debate thread reactions and clear karma.

    Returns:
        Dict with stats about the operation
    """
    stats = {
        "threads_processed": 0,
        "reactions_cleared": 0,
        "upvotes_added": 0,
        "votes_cleared": 0,
        "karma_reset": 0,
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

    logger.tree("Starting Debate Reaction Reset", [
        ("Forum", debates_forum.name),
        ("Forum ID", str(DEBATES_FORUM_ID)),
    ], emoji="🔄")

    # Get Open Discussion thread ID to skip it
    open_discussion_thread_id = db.get_open_discussion_thread_id()

    # Collect all open threads (not closed, not deprecated)
    threads_to_process = []

    for thread in debates_forum.threads:
        # Skip deprecated threads
        if thread.name.startswith("[DEPRECATED]"):
            continue
        # Skip closed threads
        if thread.name.startswith("[CLOSED]"):
            continue
        # Skip Open Discussion thread
        if open_discussion_thread_id and thread.id == open_discussion_thread_id:
            continue
        threads_to_process.append(thread)

    logger.tree("Threads to Process", [
        ("Count", str(len(threads_to_process))),
    ], emoji="📋")

    # Process each thread
    for thread in threads_to_process:
        try:
            # Get starter message
            starter_message = thread.starter_message
            if not starter_message:
                try:
                    starter_message = await thread.fetch_message(thread.id)
                except discord.NotFound:
                    logger.warning("Starter message not found", [
                        ("Thread", thread.name[:40]),
                        ("Thread ID", str(thread.id)),
                    ])
                    stats["errors"] += 1
                    continue

            # Clear all reactions from starter message
            try:
                await starter_message.clear_reactions()
                stats["reactions_cleared"] += 1
                logger.debug("Cleared reactions", [
                    ("Thread", thread.name[:40]),
                ])
            except discord.Forbidden:
                logger.warning("Cannot clear reactions (no permission)", [
                    ("Thread", thread.name[:40]),
                ])
                stats["errors"] += 1
                continue
            except discord.HTTPException as e:
                logger.warning("Failed to clear reactions", [
                    ("Thread", thread.name[:40]),
                    ("Error", str(e)[:50]),
                ])
                stats["errors"] += 1
                continue

            await asyncio.sleep(REACTION_CLEAR_DELAY)

            # Add upvote emoji
            try:
                await starter_message.add_reaction(UPVOTE_EMOJI)
                stats["upvotes_added"] += 1
            except discord.HTTPException as e:
                logger.warning("Failed to add upvote emoji", [
                    ("Thread", thread.name[:40]),
                    ("Error", str(e)[:50]),
                ])

            stats["threads_processed"] += 1

            if stats["threads_processed"] % 10 == 0:
                logger.tree("Progress", [
                    ("Processed", str(stats["threads_processed"])),
                    ("Total", str(len(threads_to_process))),
                ], emoji="⏳")

            await asyncio.sleep(THREAD_DELAY)

        except Exception as e:
            logger.error("Error processing thread", [
                ("Thread", thread.name[:40] if thread else "Unknown"),
                ("Error", str(e)[:80]),
            ])
            stats["errors"] += 1
            continue

    # Clear all votes from database
    logger.tree("Clearing Votes Database", [], emoji="🗑️")
    try:
        with db._lock:
            conn = db._get_connection()
            cursor = conn.cursor()

            # Count votes before clearing
            cursor.execute("SELECT COUNT(*) FROM votes")
            vote_count = cursor.fetchone()[0]
            stats["votes_cleared"] = vote_count

            # Clear all votes
            cursor.execute("DELETE FROM votes")

            # Reset all user karma
            cursor.execute("SELECT COUNT(*) FROM user_karma WHERE total_karma != 0")
            karma_count = cursor.fetchone()[0]
            stats["karma_reset"] = karma_count

            cursor.execute("UPDATE user_karma SET total_karma = 0, upvotes_received = 0, downvotes_received = 0")

            conn.commit()

        logger.tree("Database Cleared", [
            ("Votes Deleted", str(stats["votes_cleared"])),
            ("Karma Reset", str(stats["karma_reset"])),
        ], emoji="✅")

    except Exception as e:
        logger.error("Failed to clear database", [
            ("Error", str(e)),
        ])
        stats["errors"] += 1

    # Final summary
    logger.tree("Debate Reaction Reset Complete", [
        ("Threads Processed", str(stats["threads_processed"])),
        ("Reactions Cleared", str(stats["reactions_cleared"])),
        ("Upvotes Added", str(stats["upvotes_added"])),
        ("Votes Cleared", str(stats["votes_cleared"])),
        ("Karma Reset", str(stats["karma_reset"])),
        ("Errors", str(stats["errors"])),
    ], emoji="✅")

    return stats


async def main():
    """Main entry point for the script."""
    token = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set in .env")
        print(f"Checked env file at: {env_path}")
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
        print(f"Running reaction reset...")

        try:
            stats = await reset_debate_reactions(bot)
            print(f"\nOperation complete!")
            print(f"  Threads processed: {stats['threads_processed']}")
            print(f"  Reactions cleared: {stats['reactions_cleared']}")
            print(f"  Upvotes added: {stats['upvotes_added']}")
            print(f"  Votes cleared: {stats['votes_cleared']}")
            print(f"  Karma reset: {stats['karma_reset']}")
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
