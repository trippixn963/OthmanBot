"""
Rebuild karma from existing reactions on all debate posts and comments.

This script will:
1. Scan all debate threads (active + archived)
2. Find all messages with upvote/downvote reactions
3. Record each reaction as a vote in the database
4. Rebuild karma totals for all users

Run with: python scripts/rebuild_karma_from_reactions.py

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
MESSAGE_DELAY = 0.1  # Delay between messages
THREAD_DELAY = 0.5   # Delay between threads

# Emoji IDs to look for (both old and new)
UPVOTE_EMOJI_IDS = [
    1460602851331014811,  # Current upvote emoji
    # Add any old emoji IDs here if they were different
]
DOWNVOTE_EMOJI_IDS = [
    1460603397748035606,  # Current downvote emoji
    # Add any old emoji IDs here if they were different
]

# Also check for standard emoji names (in case custom ones weren't used)
UPVOTE_NAMES = ["upvote", "up", "thumbsup", "\U0001f44d"]  # thumbs up unicode
DOWNVOTE_NAMES = ["downvote", "down", "thumbsdown", "\U0001f44e"]  # thumbs down unicode


def is_upvote(emoji) -> bool:
    """Check if emoji is an upvote."""
    if hasattr(emoji, 'id') and emoji.id:
        return emoji.id in UPVOTE_EMOJI_IDS
    if hasattr(emoji, 'name'):
        return emoji.name.lower() in UPVOTE_NAMES
    return str(emoji) in UPVOTE_NAMES


def is_downvote(emoji) -> bool:
    """Check if emoji is a downvote."""
    if hasattr(emoji, 'id') and emoji.id:
        return emoji.id in DOWNVOTE_EMOJI_IDS
    if hasattr(emoji, 'name'):
        return emoji.name.lower() in DOWNVOTE_NAMES
    return str(emoji) in DOWNVOTE_NAMES


async def rebuild_karma(bot: commands.Bot) -> dict:
    """
    Rebuild karma from all existing reactions.

    Returns:
        Dict with stats about the operation
    """
    stats = {
        "threads_scanned": 0,
        "messages_scanned": 0,
        "upvotes_found": 0,
        "downvotes_found": 0,
        "votes_recorded": 0,
        "users_updated": 0,
        "errors": 0,
    }

    # Initialize database
    db = DebatesDatabase()

    # First, clear all existing votes and karma
    logger.tree("Clearing Existing Votes/Karma", [], emoji="🗑️")
    try:
        with db._lock:
            conn = db._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM votes")
            cursor.execute("UPDATE users SET total_karma = 0, upvotes_received = 0, downvotes_received = 0")
            conn.commit()
        logger.tree("Database Cleared", [], emoji="✅")
    except Exception as e:
        logger.tree("Failed to Clear Database", [("Error", str(e))], emoji="❌")
        return stats

    # Get debates forum
    debates_forum = bot.get_channel(DEBATES_FORUM_ID)
    if not debates_forum:
        logger.tree("Debates Forum Not Found", [
            ("Forum ID", str(DEBATES_FORUM_ID)),
        ], emoji="❌")
        return stats

    logger.tree("Starting Karma Rebuild", [
        ("Forum", debates_forum.name),
        ("Forum ID", str(DEBATES_FORUM_ID)),
    ], emoji="🔄")

    # Get Open Discussion thread ID to potentially handle differently
    open_discussion_thread_id = db.get_open_discussion_thread_id()

    # Collect all threads (active + archived)
    all_threads = list(debates_forum.threads)
    logger.tree("Active Threads Found", [("Count", str(len(all_threads)))], emoji="📋")

    # Fetch archived threads
    try:
        archived_count = 0
        async for archived_thread in debates_forum.archived_threads(limit=None):
            all_threads.append(archived_thread)
            archived_count += 1
        logger.tree("Archived Threads Found", [("Count", str(archived_count))], emoji="📋")
    except Exception as e:
        logger.tree("Failed to Fetch Archived Threads", [("Error", str(e)[:50])], emoji="⚠️")

    logger.tree("Total Threads to Scan", [("Count", str(len(all_threads)))], emoji="📊")

    # Track karma changes per user
    user_karma = {}  # user_id -> {"upvotes": 0, "downvotes": 0}

    # Process each thread
    for thread in all_threads:
        stats["threads_scanned"] += 1

        # Skip closed/deprecated threads
        if thread.name.startswith("[CLOSED]") or thread.name.startswith("[DEPRECATED]"):
            continue

        try:
            # Fetch all messages in thread
            messages = []
            async for message in thread.history(limit=None, oldest_first=True):
                messages.append(message)

            logger.tree("Scanning Thread", [
                ("Thread", thread.name[:40]),
                ("Messages", str(len(messages))),
            ], emoji="🔍")

            for message in messages:
                stats["messages_scanned"] += 1

                # Skip bot messages
                if message.author.bot:
                    continue

                # Check reactions
                for reaction in message.reactions:
                    emoji = reaction.emoji

                    vote_type = None
                    if is_upvote(emoji):
                        vote_type = 1
                    elif is_downvote(emoji):
                        vote_type = -1

                    if vote_type is None:
                        continue

                    # Get all users who reacted
                    try:
                        async for user in reaction.users():
                            # Skip bots
                            if user.bot:
                                continue

                            # Skip self-votes
                            if user.id == message.author.id:
                                continue

                            # Record this vote
                            try:
                                db.add_vote(
                                    voter_id=user.id,
                                    message_id=message.id,
                                    author_id=message.author.id,
                                    vote_type=vote_type
                                )
                                stats["votes_recorded"] += 1

                                if vote_type == 1:
                                    stats["upvotes_found"] += 1
                                else:
                                    stats["downvotes_found"] += 1

                                # Track for summary
                                if message.author.id not in user_karma:
                                    user_karma[message.author.id] = {"upvotes": 0, "downvotes": 0}

                                if vote_type == 1:
                                    user_karma[message.author.id]["upvotes"] += 1
                                else:
                                    user_karma[message.author.id]["downvotes"] += 1

                            except Exception as e:
                                # Vote might already exist or other error
                                pass

                    except discord.HTTPException as e:
                        logger.tree("Failed to Fetch Reaction Users", [
                            ("Error", str(e)[:50]),
                        ], emoji="⚠️")
                        stats["errors"] += 1

                await asyncio.sleep(MESSAGE_DELAY)

            await asyncio.sleep(THREAD_DELAY)

        except discord.Forbidden:
            logger.tree("No Access to Thread", [("Thread", thread.name[:40])], emoji="🚫")
            stats["errors"] += 1
        except Exception as e:
            logger.tree("Error Processing Thread", [
                ("Thread", thread.name[:40]),
                ("Error", str(e)[:50]),
            ], emoji="❌")
            stats["errors"] += 1

        # Progress update every 10 threads
        if stats["threads_scanned"] % 10 == 0:
            logger.tree("Progress", [
                ("Threads", str(stats["threads_scanned"])),
                ("Messages", str(stats["messages_scanned"])),
                ("Votes", str(stats["votes_recorded"])),
            ], emoji="⏳")

    stats["users_updated"] = len(user_karma)

    # Final summary
    logger.tree("Karma Rebuild Complete", [
        ("Threads Scanned", str(stats["threads_scanned"])),
        ("Messages Scanned", str(stats["messages_scanned"])),
        ("Upvotes Found", str(stats["upvotes_found"])),
        ("Downvotes Found", str(stats["downvotes_found"])),
        ("Votes Recorded", str(stats["votes_recorded"])),
        ("Users Updated", str(stats["users_updated"])),
        ("Errors", str(stats["errors"])),
    ], emoji="✅")

    # Show top 10 karma users
    if user_karma:
        sorted_users = sorted(
            user_karma.items(),
            key=lambda x: x[1]["upvotes"] - x[1]["downvotes"],
            reverse=True
        )[:10]

        print("\n=== Top 10 Karma Users ===")
        for i, (user_id, karma) in enumerate(sorted_users, 1):
            total = karma["upvotes"] - karma["downvotes"]
            print(f"  {i}. User {user_id}: {total} karma (+{karma['upvotes']}/-{karma['downvotes']})")

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
    intents.reactions = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"Bot connected as {bot.user}")
        print(f"Rebuilding karma from reactions...")
        print(f"This may take a while for large forums...\n")

        try:
            stats = await rebuild_karma(bot)
            print(f"\n=== Operation Complete ===")
            print(f"  Threads scanned: {stats['threads_scanned']}")
            print(f"  Messages scanned: {stats['messages_scanned']}")
            print(f"  Upvotes found: {stats['upvotes_found']}")
            print(f"  Downvotes found: {stats['downvotes_found']}")
            print(f"  Votes recorded: {stats['votes_recorded']}")
            print(f"  Users updated: {stats['users_updated']}")
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
