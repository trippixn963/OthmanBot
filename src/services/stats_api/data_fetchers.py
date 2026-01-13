"""
OthmanBot - Stats API Data Fetchers
===================================

Helper functions for fetching and enriching data for the stats API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from src.core.logger import logger
from src.core.config import NY_TZ, DEBATES_FORUM_ID, SYRIA_GUILD_ID
from src.services.debates.tags import DEBATE_TAGS
from src.services.stats_api.constants import BOT_HOME, get_tier

if TYPE_CHECKING:
    from src.bot import OthmanBot


# Avatar cache: {user_id: (avatar_url, display_name, is_booster)}
# Refreshed daily at 00:00 EST
_avatar_cache: dict[int, tuple[Optional[str], str, bool]] = {}
_avatar_cache_date: Optional[str] = None


def check_cache_refresh() -> None:
    """Clear avatar cache if it's a new day in EST."""
    global _avatar_cache, _avatar_cache_date
    today_est = datetime.now(NY_TZ).strftime("%Y-%m-%d")

    if _avatar_cache_date != today_est:
        old_count = len(_avatar_cache)
        _avatar_cache.clear()
        _avatar_cache_date = today_est
        if old_count > 0:
            logger.info("Avatar Cache Refreshed", [
                ("New Date", today_est),
                ("Cleared Entries", str(old_count)),
            ])


async def fetch_user_data(
    bot: "OthmanBot",
    uid: int,
    fallback_name: str
) -> tuple[Optional[str], str, bool]:
    """Fetch avatar, display name, and booster status for a single user."""
    global _avatar_cache

    check_cache_refresh()

    if uid in _avatar_cache:
        return _avatar_cache[uid]

    if not bot or not bot.is_ready():
        return None, fallback_name, False

    try:
        user = bot.get_user(uid)
        if not user:
            user = await asyncio.wait_for(
                bot.fetch_user(uid),
                timeout=2.0
            )

        if user:
            display_name = user.global_name or user.display_name or user.name
            avatar_url = user.avatar.url if user.avatar else user.default_avatar.url

            # Check booster status via guild member
            is_booster = False
            guild = bot.get_guild(SYRIA_GUILD_ID)
            if guild:
                member = guild.get_member(uid)
                if member and member.premium_since:
                    is_booster = True

            _avatar_cache[uid] = (avatar_url, display_name, is_booster)
            return avatar_url, display_name, is_booster
    except (asyncio.TimeoutError, Exception):
        pass

    return None, fallback_name, False


async def enrich_users_with_avatars(
    bot: "OthmanBot",
    users: list[tuple]
) -> list[dict]:
    """Add avatar URLs, clean usernames, and booster status to user data."""
    if not users:
        return []

    # Fetch all user data concurrently with overall 5s timeout
    try:
        tasks = [fetch_user_data(bot, uid, name) for uid, name, karma in users]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        results = [(None, name, False) for _, name, _ in users]

    # Build enriched list
    enriched = []
    for i, (uid, fallback_name, karma) in enumerate(users):
        result = results[i]
        if isinstance(result, Exception):
            avatar_url, display_name, is_booster = None, fallback_name, False
        else:
            avatar_url, display_name, is_booster = result

        enriched.append({
            "user_id": str(uid),  # String to avoid JS precision loss
            "name": display_name,
            "karma": karma,
            "avatar": avatar_url,
            "is_booster": is_booster,
        })

    return enriched


async def get_changelog() -> list[dict]:
    """Get recent git commits from the OthmanBot repo."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "--oneline", "-10", "--format=%h|%s",
            cwd=BOT_HOME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)

        if proc.returncode != 0:
            logger.debug("Git log failed", [
                ("Return Code", str(proc.returncode)),
                ("Stderr", stderr.decode()[:100] if stderr else "None"),
            ])
            return []

        commits = []
        for line in stdout.decode().strip().split("\n"):
            if "|" in line:
                commit_hash, message = line.split("|", 1)
                msg_lower = message.lower()
                if msg_lower.startswith("fix") or "fix" in msg_lower[:20]:
                    commit_type = "fix"
                elif msg_lower.startswith("add") or msg_lower.startswith("implement"):
                    commit_type = "feature"
                else:
                    commit_type = "improvement"

                commits.append({
                    "commit": commit_hash,
                    "message": message,
                    "type": commit_type
                })
        return commits
    except asyncio.TimeoutError:
        logger.debug("Git log timed out")
        return []
    except Exception as e:
        logger.debug("Git log error", [("Error", str(e))])
        return []


async def get_hot_debate(bot: "OthmanBot") -> Optional[dict]:
    """Get the current hot debate thread info."""
    try:
        if not bot or not bot.is_ready():
            return None

        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            return None

        hot_tag_id = DEBATE_TAGS.get("hot")
        if not hot_tag_id:
            return None

        # Helper to check a thread for hot tag
        async def check_thread(thread) -> Optional[dict]:
            if thread is None:
                return None
            tag_ids = [tag.id for tag in thread.applied_tags]
            if hot_tag_id in tag_ids:
                # Get first image from thread
                image_url = None
                try:
                    starter = await thread.fetch_message(thread.id)
                    if starter and starter.attachments:
                        for attachment in starter.attachments:
                            if attachment.content_type and attachment.content_type.startswith("image/"):
                                image_url = attachment.url
                                break
                except Exception:
                    pass

                return {
                    "title": thread.name,
                    "thread_id": thread.id,
                    "message_count": thread.message_count or 0,
                    "image": image_url,
                }
            return None

        # Check cached active threads first
        for thread in debates_forum.threads:
            result = await check_thread(thread)
            if result:
                return result

        # Also check recently archived threads
        try:
            async for thread in debates_forum.archived_threads(limit=20):
                result = await check_thread(thread)
                if result:
                    return result
        except Exception:
            pass

        return None
    except Exception as e:
        logger.debug("Failed to get hot debate", [("Error", str(e))])
        return None


async def count_forum_threads(bot: "OthmanBot", channel_id: Optional[int]) -> int:
    """Count all threads (active + archived) in a forum channel."""
    if not channel_id or not bot or not bot.is_ready():
        return 0

    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            return 0

        count = len(channel.threads)
        try:
            async for _ in channel.archived_threads(limit=None):
                count += 1
        except Exception:
            pass
        return count
    except Exception as e:
        logger.debug("Failed to count forum threads", [("Channel", str(channel_id)), ("Error", str(e))])
        return 0


async def get_recent_threads(
    bot: "OthmanBot",
    channel_id: Optional[int],
    limit: int = 5
) -> list[dict]:
    """Get the most recent threads from a forum channel."""
    if not channel_id or not bot or not bot.is_ready():
        return []

    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            return []

        all_threads = []

        # Collect active threads
        for thread in channel.threads:
            if thread.created_at:
                all_threads.append(thread)

        # Collect recently archived threads
        try:
            async for thread in channel.archived_threads(limit=20):
                if thread.created_at:
                    all_threads.append(thread)
        except Exception:
            pass

        # Sort by creation time (newest first) and take top N
        all_threads.sort(key=lambda t: t.created_at, reverse=True)
        recent_threads = all_threads[:limit]

        results = []
        for thread in recent_threads:
            # Get image and excerpt from first message
            image_url = None
            excerpt = None
            source = None
            try:
                starter = await thread.fetch_message(thread.id)
                if starter:
                    # Get image
                    if starter.attachments:
                        for attachment in starter.attachments:
                            if attachment.content_type and attachment.content_type.startswith("image/"):
                                image_url = attachment.url
                                break
                    # Get excerpt from content (first 150 chars)
                    if starter.content:
                        content = starter.content.strip()
                        # Try to extract source from content
                        if "Source:" in content or "المصدر:" in content:
                            for line in content.split("\n"):
                                if "Source:" in line:
                                    source = line.replace("Source:", "").strip()[:50]
                                    break
                                elif "المصدر:" in line:
                                    source = line.replace("المصدر:", "").strip()[:50]
                                    break
                        # Get excerpt (first meaningful paragraph)
                        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("Source:") and not l.startswith("المصدر:")]
                        if lines:
                            excerpt = lines[0][:150]
                            if len(lines[0]) > 150:
                                excerpt += "..."
            except Exception:
                pass

            results.append({
                "title": thread.name,
                "thread_id": thread.id,
                "message_count": thread.message_count or 0,
                "image": image_url,
                "excerpt": excerpt,
                "source": source,
                "created_at": thread.created_at.isoformat() if thread.created_at else None,
            })

        return results
    except Exception as e:
        logger.debug("Failed to get recent threads", [("Channel", str(channel_id)), ("Error", str(e))])
        return []


async def get_trending_debates(bot: "OthmanBot", limit: int = 3) -> list[dict]:
    """Get most active debate threads."""
    if not bot or not bot.is_ready():
        return []

    try:
        debates_forum = bot.get_channel(DEBATES_FORUM_ID)
        if not debates_forum:
            return []

        # Collect threads with message counts
        threads_data = []
        for thread in debates_forum.threads:
            if thread.message_count and thread.message_count > 0:
                threads_data.append({
                    "thread": thread,
                    "message_count": thread.message_count,
                })

        # Sort by message count and take top N
        threads_data.sort(key=lambda x: x["message_count"], reverse=True)
        top_threads = threads_data[:limit]

        results = []
        for item in top_threads:
            thread = item["thread"]
            # Get image from first message
            image_url = None
            try:
                starter = await thread.fetch_message(thread.id)
                if starter and starter.attachments:
                    for attachment in starter.attachments:
                        if attachment.content_type and attachment.content_type.startswith("image/"):
                            image_url = attachment.url
                            break
            except Exception:
                pass

            results.append({
                "title": thread.name,
                "thread_id": thread.id,
                "message_count": thread.message_count or 0,
                "image": image_url,
                "created_at": thread.created_at.isoformat() if thread.created_at else None,
            })

        return results
    except Exception as e:
        logger.debug("Failed to get trending debates", [("Error", str(e))])
        return []


def get_activity_sparkline(db) -> list[int]:
    """Get vote counts for the last 7 days for sparkline chart."""
    if not db:
        return [0] * 7

    try:
        conn = db._get_connection()
        cursor = conn.cursor()
        try:
            # Get votes per day for the last 7 days
            cursor.execute("""
                SELECT DATE(created_at) as vote_date, COUNT(*) as vote_count
                FROM votes
                WHERE created_at >= DATE('now', '-7 days')
                GROUP BY DATE(created_at)
                ORDER BY vote_date ASC
            """)
            rows = cursor.fetchall()

            # Create a dict of date -> count
            date_counts = {row[0]: row[1] for row in rows}

            # Build array for last 7 days
            result = []
            for i in range(6, -1, -1):
                target_date = (datetime.now(NY_TZ) - timedelta(days=i)).strftime("%Y-%m-%d")
                result.append(date_counts.get(target_date, 0))

            return result
        finally:
            cursor.close()
    except Exception as e:
        logger.debug("Failed to get activity sparkline", [("Error", str(e))])
        return [0] * 7


__all__ = [
    "check_cache_refresh",
    "fetch_user_data",
    "enrich_users_with_avatars",
    "get_changelog",
    "get_hot_debate",
    "count_forum_threads",
    "get_recent_threads",
    "get_trending_debates",
    "get_activity_sparkline",
    "get_tier",
]
