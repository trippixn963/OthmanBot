"""
Othman Discord Bot - Main Entry Point
=====================================

Automated news bot that posts hourly Middle East news updates with images
and creates discussion threads for each article.

Features:
- Hourly automated news posts from RSS feeds
- Thread creation for discussions
- Image embedding from news articles
- Al Jazeera and Middle East news focus
- Clean, professional news embeds

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import sys
from dotenv import load_dotenv

from src.core.logger import logger
from src.bot import OthmanBot


def main() -> None:
    """Main entry point for the Othman Discord bot."""
    # Load environment variables from .env file
    load_dotenv()

    # Get bot token from environment
    token: str | None = os.getenv("DISCORD_TOKEN")

    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables")
        logger.error("Please create a .env file with your bot token")
        sys.exit(1)

    # Create and run the bot
    try:
        logger.tree(
            "Starting Othman News Bot",
            [
                ("Purpose", "Automated Middle East News"),
                ("Frequency", "Hourly updates"),
                ("Structure", "Organized with src/"),
                ("Features", "Thread posts, images, RSS feeds"),
            ],
            emoji="📰",
        )

        bot: OthmanBot = OthmanBot()
        bot.run(token)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
