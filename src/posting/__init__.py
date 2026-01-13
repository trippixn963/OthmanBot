"""
OthmanBot - Posting Package
=====================================

Content posting modules for news and soccer.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.posting.poster import download_media, cleanup_temp_file
from src.posting.news import post_news, post_article_to_forum
from src.posting.soccer import post_soccer_news, post_soccer_article_to_forum
from src.posting.announcements import (
    send_general_announcement,
    send_soccer_announcement,
)

__all__ = [
    "download_media",
    "cleanup_temp_file",
    "post_news",
    "post_article_to_forum",
    "post_soccer_news",
    "post_soccer_article_to_forum",
    "send_general_announcement",
    "send_soccer_announcement",
]
