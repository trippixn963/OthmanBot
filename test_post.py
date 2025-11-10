"""
Quick test script to trigger immediate news post.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Import bot
from src.bot import OthmanBot

async def test_post():
    """Run a single news post immediately."""
    bot = OthmanBot()

    # Initialize news scraper
    bot.news_scraper = await bot.news_scraper.__aenter__()

    # Trigger immediate post
    print("🧪 Testing immediate news post...")
    await bot.post_news()

    # Cleanup
    await bot.news_scraper.__aexit__(None, None, None)
    print("✅ Test complete!")

if __name__ == "__main__":
    asyncio.run(test_post())
