"""
Clear all forum threads from the news channel.

This script deletes all existing forum posts to start fresh.
Run this once before starting the bot for production.
"""

import os
import asyncio
import discord
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
NEWS_CHANNEL_ID = int(os.getenv("NEWS_CHANNEL_ID"))


async def clear_forum_channel():
    """Delete all threads from the forum channel."""
    # Create bot instance
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"✅ Logged in as {client.user}")

        # Get the forum channel
        channel = client.get_channel(NEWS_CHANNEL_ID)

        if not channel:
            print(f"❌ Channel {NEWS_CHANNEL_ID} not found")
            await client.close()
            return

        if not isinstance(channel, discord.ForumChannel):
            print(f"❌ Channel {NEWS_CHANNEL_ID} is not a forum channel")
            await client.close()
            return

        print(f"📰 Found forum channel: {channel.name}")

        # Get all active threads
        threads = channel.threads
        archived_threads = []

        # Get archived threads too
        async for thread in channel.archived_threads(limit=100):
            archived_threads.append(thread)

        all_threads = list(threads) + archived_threads

        if not all_threads:
            print("✅ No threads to delete - channel is already clean")
            await client.close()
            return

        print(f"🗑️  Found {len(all_threads)} threads to delete")

        # Delete all threads
        deleted = 0
        failed = 0

        for thread in all_threads:
            try:
                await thread.delete()
                deleted += 1
                print(f"✅ Deleted thread {deleted}/{len(all_threads)}: {thread.name}")
                await asyncio.sleep(0.5)  # Rate limit protection
            except Exception as e:
                failed += 1
                print(f"❌ Failed to delete thread '{thread.name}': {e}")

        print(f"\n{'='*50}")
        print(f"✅ Successfully deleted: {deleted} threads")
        if failed > 0:
            print(f"❌ Failed to delete: {failed} threads")
        print(f"{'='*50}")

        await client.close()

    # Run the bot
    await client.start(TOKEN)


if __name__ == "__main__":
    print("🧹 Starting forum cleanup...")
    print(f"📍 Target channel ID: {NEWS_CHANNEL_ID}")
    print(f"{'='*50}\n")

    asyncio.run(clear_forum_channel())

    print("\n✅ Cleanup complete!")
