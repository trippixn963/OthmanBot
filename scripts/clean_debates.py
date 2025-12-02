#!/usr/bin/env python3
"""
Clean all deprecated debate threads:
- Remove all reactions from all messages
- Delete all bot messages (analytics embeds)
"""

import asyncio
import discord
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path("/root/OthmanBot")
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.core.config import DEBATES_FORUM_ID

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    print("DISCORD_TOKEN not set")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True

client = discord.Client(intents=intents)


async def clean_thread(thread: discord.Thread) -> dict:
    """Clean a single thread - remove reactions and bot messages."""
    stats = {"reactions_removed": 0, "messages_deleted": 0, "messages_checked": 0}

    try:
        # Unarchive if needed
        was_archived = thread.archived
        if was_archived:
            await thread.edit(archived=False)
            await asyncio.sleep(0.5)

        # Go through all messages
        async for message in thread.history(limit=None):
            stats["messages_checked"] += 1

            # Remove all reactions from this message
            if message.reactions:
                for reaction in message.reactions:
                    try:
                        await message.clear_reaction(reaction.emoji)
                        stats["reactions_removed"] += reaction.count
                        await asyncio.sleep(0.3)
                    except discord.HTTPException:
                        pass

            # Delete bot messages (analytics embeds, etc)
            if message.author.bot:
                try:
                    await message.delete()
                    stats["messages_deleted"] += 1
                    await asyncio.sleep(0.3)
                except discord.HTTPException:
                    pass

        # Re-archive and lock
        if was_archived:
            await thread.edit(archived=True, locked=True)

    except Exception as e:
        print(f"   Error: {e}")

    return stats


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    debates_forum = client.get_channel(DEBATES_FORUM_ID)
    if not debates_forum:
        print("Could not find debates forum")
        await client.close()
        return

    print(f"Found debates forum: {debates_forum.name}")
    print()

    total_reactions = 0
    total_deleted = 0
    total_messages = 0
    threads_processed = 0

    # Process active threads
    print("=" * 80)
    print("PROCESSING ACTIVE THREADS")
    print("=" * 80)

    for thread in debates_forum.threads:
        if not thread.name.startswith("[DEPRECATED]"):
            continue

        print(f"Cleaning: {thread.name[:60]}...")
        stats = await clean_thread(thread)
        total_reactions += stats["reactions_removed"]
        total_deleted += stats["messages_deleted"]
        total_messages += stats["messages_checked"]
        threads_processed += 1
        r = stats["reactions_removed"]
        d = stats["messages_deleted"]
        print(f"   Done: {r} reactions, {d} bot msgs deleted")
        await asyncio.sleep(1)

    print()
    print("=" * 80)
    print("PROCESSING ARCHIVED THREADS")
    print("=" * 80)

    async for thread in debates_forum.archived_threads(limit=None):
        if not thread.name.startswith("[DEPRECATED]"):
            continue

        print(f"Cleaning: {thread.name[:60]}...")
        stats = await clean_thread(thread)
        total_reactions += stats["reactions_removed"]
        total_deleted += stats["messages_deleted"]
        total_messages += stats["messages_checked"]
        threads_processed += 1
        r = stats["reactions_removed"]
        d = stats["messages_deleted"]
        print(f"   Done: {r} reactions, {d} bot msgs deleted")
        await asyncio.sleep(1)

    print()
    print("=" * 80)
    print("CLEANUP SUMMARY")
    print("=" * 80)
    print(f"Threads processed: {threads_processed}")
    print(f"Messages checked: {total_messages}")
    print(f"Reactions removed: {total_reactions}")
    print(f"Bot messages deleted: {total_deleted}")
    print()

    await client.close()

if __name__ == "__main__":
    try:
        client.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        print("Interrupted")
    except Exception as e:
        print(f"Error: {e}")
