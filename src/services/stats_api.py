"""
Othman Discord Bot - API Service
=================================

HTTP API server for OthmanBot Dashboard.

Exposes debate stats, karma leaderboard, and health metrics.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
import psutil
from collections import defaultdict
from datetime import datetime
from aiohttp import web
from typing import TYPE_CHECKING, Optional

import os

from src.core.logger import logger
from src.core.config import NY_TZ, DEBATES_FORUM_ID, SYRIA_GUILD_ID, load_news_channel_id, load_soccer_channel_id, BASE_COMMAND_COUNT
from src.services.debates.tags import DEBATE_TAGS

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Constants
# =============================================================================

# API port (OthmanBot health check is 8080, so use 8085 for stats API)
STATS_API_PORT = 8085
STATS_API_HOST = "0.0.0.0"

# Cache duration in seconds
CACHE_TTL = 30

# Bot home directory (for git log)
BOT_HOME = os.environ.get("BOT_HOME", "/root/OthmanBot")


# =============================================================================
# Response Cache
# =============================================================================

class ResponseCache:
    """Simple in-memory cache for API responses."""

    def __init__(self, ttl: int = CACHE_TTL):
        self.ttl = ttl
        self._cache: dict[str, tuple[dict, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[dict]:
        """Get cached response if still valid."""
        async with self._lock:
            if key in self._cache:
                data, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    return data
                del self._cache[key]
            return None

    async def set(self, key: str, data: dict) -> None:
        """Cache a response."""
        async with self._lock:
            self._cache[key] = (data, time.time())

    async def invalidate(self, key: str) -> None:
        """Invalidate a cached response."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]


# =============================================================================
# Rate Limiting
# =============================================================================

class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self, requests_per_minute: int = 60, burst_limit: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_ip: str) -> tuple[bool, Optional[int]]:
        """Check if request is allowed for this IP."""
        async with self._lock:
            now = time.time()
            window_start = now - 60

            # Clean old requests
            self._requests[client_ip] = [
                ts for ts in self._requests[client_ip]
                if ts > window_start
            ]

            requests = self._requests[client_ip]

            # Check per-minute limit
            if len(requests) >= self.requests_per_minute:
                oldest = min(requests) if requests else now
                retry_after = int(oldest + 60 - now) + 1
                return False, retry_after

            # Check burst limit (last 1 second)
            recent = [ts for ts in requests if ts > now - 1]
            if len(recent) >= self.burst_limit:
                return False, 1

            # Allow request
            self._requests[client_ip].append(now)
            return True, None

    async def cleanup(self) -> None:
        """Remove stale entries older than 2 minutes."""
        async with self._lock:
            cutoff = time.time() - 120
            stale_ips = [
                ip for ip, timestamps in self._requests.items()
                if not timestamps or max(timestamps) < cutoff
            ]
            for ip in stale_ips:
                del self._requests[ip]


# Global rate limiter
rate_limiter = RateLimiter(requests_per_minute=60, burst_limit=10)


# =============================================================================
# Security Middleware
# =============================================================================

def get_client_ip(request: web.Request) -> str:
    """Extract client IP from request, handling proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    peername = request.transport.get_extra_info("peername")
    if peername:
        return peername[0]

    return "unknown"


@web.middleware
async def rate_limit_middleware(request: web.Request, handler) -> web.Response:
    """Middleware to enforce rate limiting on all requests."""
    if request.path == "/health":
        return await handler(request)

    client_ip = get_client_ip(request)
    allowed, retry_after = await rate_limiter.is_allowed(client_ip)

    if not allowed:
        logger.warning("Rate Limit Exceeded", [
            ("IP", client_ip),
            ("Path", request.path),
            ("Retry-After", f"{retry_after}s"),
        ])
        return web.json_response(
            {"error": "Rate limit exceeded", "retry_after": retry_after},
            status=429,
            headers={
                "Retry-After": str(retry_after),
                "Access-Control-Allow-Origin": "*",
            }
        )

    return await handler(request)


@web.middleware
async def security_headers_middleware(request: web.Request, handler) -> web.Response:
    """Middleware to add security headers to all responses."""
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# =============================================================================
# Stats API
# =============================================================================

# Avatar cache: {user_id: (avatar_url, display_name)}
# Refreshed daily at 00:00 EST
_avatar_cache: dict[int, tuple[Optional[str], str]] = {}
_avatar_cache_date: Optional[str] = None


class OthmanAPI:
    """API server for OthmanBot."""

    def __init__(self, bot: "OthmanBot") -> None:
        self._bot = bot
        self._start_time: Optional[datetime] = None
        self._cache = ResponseCache(ttl=CACHE_TTL)
        self.app = web.Application(middlewares=[
            rate_limit_middleware,
            security_headers_middleware,
        ])
        self.runner: Optional[web.AppRunner] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Configure API routes."""
        self.app.router.add_get("/api/othman/stats", self.handle_stats)
        self.app.router.add_get("/api/othman/user/{user_id}", self.handle_user_profile)
        self.app.router.add_get("/health", self.handle_health)

    def _check_cache_refresh(self) -> None:
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

    async def _fetch_user_data(self, uid: int, fallback_name: str) -> tuple[Optional[str], str]:
        """Fetch avatar and display name for a single user with timeout and daily caching."""
        global _avatar_cache

        self._check_cache_refresh()

        if uid in _avatar_cache:
            return _avatar_cache[uid]

        if not self._bot or not self._bot.is_ready():
            return None, fallback_name

        try:
            user = self._bot.get_user(uid)
            if not user:
                user = await asyncio.wait_for(
                    self._bot.fetch_user(uid),
                    timeout=2.0
                )

            if user:
                display_name = user.global_name or user.display_name or user.name
                avatar_url = user.avatar.url if user.avatar else user.default_avatar.url
                _avatar_cache[uid] = (avatar_url, display_name)
                return avatar_url, display_name
        except (asyncio.TimeoutError, Exception):
            pass

        return None, fallback_name

    async def _enrich_users_with_avatars(
        self, users: list[tuple]
    ) -> list[dict]:
        """Add avatar URLs and clean usernames to user data (concurrent with caching)."""
        if not users:
            return []

        # Fetch all user data concurrently with overall 5s timeout
        try:
            tasks = [self._fetch_user_data(uid, name) for uid, name, karma in users]
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            results = [(None, name) for _, name, _ in users]

        # Build enriched list
        enriched = []
        for i, (uid, fallback_name, karma) in enumerate(users):
            result = results[i]
            if isinstance(result, Exception):
                avatar_url, display_name = None, fallback_name
            else:
                avatar_url, display_name = result

            enriched.append({
                "user_id": str(uid),  # String to avoid JS precision loss
                "name": display_name,
                "karma": karma,
                "avatar": avatar_url,
            })

        return enriched

    def _get_tier(self, karma: int) -> str | None:
        """Get tier based on karma thresholds."""
        if karma >= 500:
            return "diamond"
        elif karma >= 250:
            return "gold"
        elif karma >= 100:
            return "silver"
        elif karma >= 50:
            return "bronze"
        return None

    def _get_guild_banner_url(self) -> str | None:
        """Get the current guild banner URL."""
        try:
            guild = self._bot.get_guild(SYRIA_GUILD_ID)
            if guild and guild.banner:
                # Return high quality banner (size=1024)
                return guild.banner.with_size(1024).url
        except Exception as e:
            logger.debug("Failed to get guild banner", [("Error", str(e))])
        return None

    def _get_uptime(self) -> str:
        """Get formatted uptime string."""
        if not self._start_time:
            return "0m"

        now = datetime.now(NY_TZ)
        delta = now - self._start_time
        total_seconds = int(delta.total_seconds())

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _get_system_resources(self) -> dict:
        """Get system CPU, memory, and disk usage."""
        try:
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = psutil.cpu_percent(interval=None)
            sys_mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                "bot_mem_mb": round(mem_mb, 1),
                "cpu_percent": round(cpu_percent, 1),
                "mem_percent": round(sys_mem.percent, 1),
                "mem_used_gb": round(sys_mem.used / (1024 ** 3), 1),
                "mem_total_gb": round(sys_mem.total / (1024 ** 3), 1),
                "disk_percent": round(disk.percent, 1),
                "disk_used_gb": round(disk.used / (1024 ** 3), 1),
                "disk_total_gb": round(disk.total / (1024 ** 3), 1),
            }
        except Exception as e:
            logger.debug("Failed to get system resources", [("Error", str(e))])
            return {}

    def _get_bot_status(self) -> dict:
        """Get current bot status."""
        status = {
            "online": False,
            "latency_ms": None,
            "guilds": 0,
        }

        if not self._bot:
            return status

        status["online"] = self._bot.is_ready()

        if self._bot.is_ready():
            status["latency_ms"] = round(self._bot.latency * 1000)
            status["guilds"] = len(self._bot.guilds)

        return status

    async def _get_changelog(self) -> list[dict]:
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

    async def _get_hot_debate(self) -> Optional[dict]:
        """Get the current hot debate thread info."""
        try:
            if not self._bot or not self._bot.is_ready():
                return None

            debates_forum = self._bot.get_channel(DEBATES_FORUM_ID)
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
                        pass  # Non-critical: image fetch for hot debate

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
                pass  # Non-critical: archived threads may not be accessible

            return None
        except Exception as e:
            logger.debug("Failed to get hot debate", [("Error", str(e))])
            return None

    async def _count_forum_threads(self, channel_id: Optional[int]) -> int:
        """Count all threads (active + archived) in a forum channel."""
        if not channel_id or not self._bot or not self._bot.is_ready():
            return 0

        try:
            channel = self._bot.get_channel(channel_id)
            if not channel:
                return 0

            count = len(channel.threads)
            try:
                async for _ in channel.archived_threads(limit=None):
                    count += 1
            except Exception:
                pass  # Non-critical: archived threads may not be accessible
            return count
        except Exception as e:
            logger.debug("Failed to count forum threads", [("Channel", str(channel_id)), ("Error", str(e))])
            return 0

    async def _get_recent_threads(self, channel_id: Optional[int], limit: int = 5) -> list[dict]:
        """Get the most recent threads from a forum channel."""
        if not channel_id or not self._bot or not self._bot.is_ready():
            return []

        try:
            channel = self._bot.get_channel(channel_id)
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
                pass  # Non-critical: archived threads may not be accessible

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
                            # Try to extract source from content (often in format "Source: ...")
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
                    pass  # Non-critical: message content enrichment

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

    async def _get_trending_debates(self, limit: int = 3) -> list[dict]:
        """Get most active debate threads."""
        if not self._bot or not self._bot.is_ready():
            return []

        try:
            debates_forum = self._bot.get_channel(DEBATES_FORUM_ID)
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
                    pass  # Non-critical: image fetch for trending debate

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

    def _get_activity_sparkline(self, db) -> list[int]:
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
                    from datetime import timedelta
                    target_date = (datetime.now(NY_TZ) - timedelta(days=i)).strftime("%Y-%m-%d")
                    result.append(date_counts.get(target_date, 0))

                return result
            finally:
                cursor.close()
        except Exception as e:
            logger.debug("Failed to get activity sparkline", [("Error", str(e))])
            return [0] * 7

    async def _get_all_time_stats(self, db) -> dict:
        """Get all-time statistics."""
        total_commands = BASE_COMMAND_COUNT
        total_votes = 0
        total_news = 0

        if db:
            try:
                total_votes = db.get_total_votes()
            except Exception as e:
                logger.debug("Failed to get total votes", [("Error", str(e))])

        # Count news from both news and soccer channels
        if self._bot and self._bot.is_ready():
            news_channel_id = load_news_channel_id()
            soccer_channel_id = load_soccer_channel_id()

            news_count = await self._count_forum_threads(news_channel_id)
            soccer_count = await self._count_forum_threads(soccer_channel_id)
            total_news = news_count + soccer_count

        return {
            "total_commands": total_commands,
            "total_votes": total_votes,
            "total_news": total_news,
        }

    async def handle_stats(self, request: web.Request) -> web.Response:
        """GET /api/othman/stats - Return Othman debate stats."""
        client_ip = get_client_ip(request)
        start_time = time.time()

        logger.info("Stats API Request", [
            ("IP", client_ip),
            ("Path", request.path),
        ])

        # Check cache first
        cached = await self._cache.get("stats")
        if cached:
            # Update response time for cached response
            cached["response_time_ms"] = round((time.time() - start_time) * 1000, 1)
            cached["cached"] = True
            logger.info("Stats API Cache Hit", [
                ("Response Time", f"{cached['response_time_ms']}ms"),
            ])
            return web.json_response(cached)

        try:
            db = self._bot.debates_service.db if hasattr(self._bot, 'debates_service') else None

            # Get debate stats
            total_debates = 0
            votes_today = 0
            leaderboard_raw = []
            monthly_stats = {}

            monthly_leaderboard_raw = []
            now = datetime.now(NY_TZ)

            # Category leaderboards (streaks, active, creators)
            category_leaderboards = {}

            if db:
                total_debates = db.get_active_debate_count()
                votes_today = db.get_votes_today()
                leaderboard_raw = db.get_leaderboard(limit=15)

                # Get current month stats
                monthly_stats = db.get_monthly_stats(now.year, now.month)

                # Get monthly leaderboard
                try:
                    monthly_leaderboard_raw = db.get_monthly_leaderboard(now.year, now.month, limit=15)
                except Exception as e:
                    logger.debug("Failed to get monthly leaderboard", [("Error", str(e))])

                # Get category leaderboards
                try:
                    category_leaderboards = db.get_category_leaderboards(limit=15)
                except Exception as e:
                    logger.debug("Failed to get category leaderboards", [("Error", str(e))])

            # Enrich all-time leaderboard with avatars
            leaderboard_tuples = [
                (user.user_id, f"User {user.user_id}", user.total_karma)
                for user in leaderboard_raw
            ]
            leaderboard = await self._enrich_users_with_avatars(leaderboard_tuples)

            # Get karma changes for leaderboard users
            karma_changes = {}
            if db and leaderboard:
                try:
                    user_ids = [u["user_id"] for u in leaderboard]
                    karma_changes = db.get_karma_changes_today(user_ids)
                except Exception as e:
                    logger.debug("Failed to get karma changes", [("Error", str(e))])

            # Calculate max karma for progress bars
            max_karma = max((u["karma"] for u in leaderboard), default=1)

            # Add progress percentage, karma change, and tier to each user
            for user in leaderboard:
                user["progress"] = round((user["karma"] / max_karma) * 100, 1) if max_karma > 0 else 0
                user["karma_change"] = karma_changes.get(user["user_id"], 0)
                user["tier"] = self._get_tier(user["karma"])

            # Enrich monthly leaderboard with avatars
            monthly_tuples = [
                (user.user_id, f"User {user.user_id}", user.total_karma)
                for user in monthly_leaderboard_raw
            ]
            monthly_leaderboard = await self._enrich_users_with_avatars(monthly_tuples)

            # Get karma changes for monthly leaderboard users
            monthly_karma_changes = {}
            if db and monthly_leaderboard:
                try:
                    monthly_user_ids = [u["user_id"] for u in monthly_leaderboard]
                    monthly_karma_changes = db.get_karma_changes_today(monthly_user_ids)
                except Exception as e:
                    logger.debug("Failed to get monthly karma changes", [("Error", str(e))])

            # Calculate max karma for monthly progress bars
            monthly_max_karma = max((u["karma"] for u in monthly_leaderboard), default=1)

            # Add progress percentage, karma change, and tier to monthly users
            for user in monthly_leaderboard:
                user["progress"] = round((user["karma"] / monthly_max_karma) * 100, 1) if monthly_max_karma > 0 else 0
                user["karma_change"] = monthly_karma_changes.get(user["user_id"], 0)
                user["tier"] = self._get_tier(user["karma"])

            # Enrich category leaderboards with avatars
            enriched_categories = {}
            for category, users in category_leaderboards.items():
                if users:
                    # Different value keys for different categories
                    value_key = "current_streak" if category == "streaks" else "message_count" if category == "active" else "debate_count"
                    category_tuples = [
                        (u["user_id"], f"User {u['user_id']}", u.get(value_key, 0))
                        for u in users
                    ]
                    enriched_list = await self._enrich_users_with_avatars(category_tuples)
                    # Add back the original value with proper key name
                    for i, enriched_user in enumerate(enriched_list):
                        enriched_user["value"] = users[i].get(value_key, 0)
                        enriched_user["tier"] = self._get_tier(enriched_user.get("karma", 0))
                    enriched_categories[category] = enriched_list
                else:
                    enriched_categories[category] = []

            # Get hot debate info
            hot_debate = await self._get_hot_debate()

            # Get recent news threads (last 5 each)
            news_channel_id = load_news_channel_id()
            soccer_channel_id = load_soccer_channel_id()
            recent_news = await self._get_recent_threads(news_channel_id, limit=5)
            recent_soccer = await self._get_recent_threads(soccer_channel_id, limit=5)

            # Get trending debates (most active)
            trending_debates = await self._get_trending_debates(limit=3)

            # Get activity sparkline (votes per day for last 7 days)
            activity_sparkline = self._get_activity_sparkline(db)

            # Build response
            response_data = {
                "bot": self._get_bot_status(),
                "uptime": self._get_uptime(),
                "debates": {
                    "total": total_debates,
                    "votes_today": votes_today,
                    "monthly": monthly_stats,
                },
                "all_time": await self._get_all_time_stats(db),
                "hot_debate": hot_debate,
                "recent_news": recent_news,
                "recent_soccer": recent_soccer,
                "trending_debates": trending_debates,
                "activity_sparkline": activity_sparkline,
                "leaderboard": leaderboard,
                "monthly_leaderboard": monthly_leaderboard,
                "category_leaderboards": enriched_categories,
                "current_month": now.strftime("%B"),
                "changelog": await self._get_changelog(),
                "system": self._get_system_resources(),
                "guild_banner": self._get_guild_banner_url(),
                "generated_at": datetime.now(NY_TZ).isoformat(),
                "response_time_ms": round((time.time() - start_time) * 1000, 1),
                "cached": False,
            }

            # Cache the response for 30 seconds
            await self._cache.set("stats", response_data)

            logger.info("Stats API Response Built", [
                ("Response Time", f"{response_data['response_time_ms']}ms"),
            ])

            return web.json_response(
                response_data,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        except Exception as e:
            logger.error_tree("Stats API Error", e)
            return web.json_response(
                {"error": "Internal server error"},
                status=500,
                headers={"Access-Control-Allow-Origin": "*"}
            )

    async def handle_user_profile(self, request: web.Request) -> web.Response:
        """GET /api/othman/user/{user_id} - Return user profile data."""
        client_ip = get_client_ip(request)
        start_time = time.time()

        # Validate user_id
        try:
            user_id = int(request.match_info["user_id"])
        except ValueError:
            return web.json_response(
                {"error": "Invalid user ID"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        logger.info("User Profile API Request", [
            ("IP", client_ip),
            ("User ID", str(user_id)),
        ])

        # Check cache first
        cache_key = f"user_profile_{user_id}"
        cached = await self._cache.get(cache_key)
        if cached:
            cached["response_time_ms"] = round((time.time() - start_time) * 1000, 1)
            cached["cached"] = True
            return web.json_response(cached, headers={"Access-Control-Allow-Origin": "*"})

        try:
            db = self._bot.debates_service.db if hasattr(self._bot, 'debates_service') else None

            if not db:
                return web.json_response(
                    {"error": "Database unavailable"},
                    status=503,
                    headers={"Access-Control-Allow-Origin": "*"}
                )

            # Gather all user data
            karma = db.get_user_karma(user_id)
            rank = db.get_user_rank(user_id)
            analytics = db.get_user_analytics(user_id)
            streak = db.get_user_streak(user_id)

            # Check if user has any activity (exists in our system)
            has_activity = (
                karma.total_karma != 0 or
                karma.upvotes_received != 0 or
                karma.downvotes_received != 0 or
                analytics.get("debates_participated", 0) > 0 or
                analytics.get("total_messages", 0) > 0
            )

            # Try to fetch Discord user data
            avatar_url, display_name = await self._fetch_user_data(user_id, f"User {user_id}")

            # If user has no activity AND we couldn't get their Discord info, return 404
            if not has_activity and display_name == f"User {user_id}":
                return web.json_response(
                    {"error": "User not found"},
                    status=404,
                    headers={"Access-Control-Allow-Origin": "*"}
                )

            # New enhanced data
            rank_change = db.get_rank_change(user_id)
            karma_history = db.get_karma_history(user_id, days=7)
            recent_debates_raw = db.get_user_recent_debates(user_id, limit=5)

            # Enrich recent debates with thread names from Discord
            recent_debates = []
            if recent_debates_raw and self._bot and self._bot.is_ready():
                debates_forum = self._bot.get_channel(DEBATES_FORUM_ID)
                if debates_forum:
                    for debate in recent_debates_raw:
                        thread_id = debate["thread_id"]
                        thread_name = "Unknown Debate"

                        # Try to get thread from cache first
                        thread = debates_forum.get_thread(thread_id)
                        if thread:
                            thread_name = thread.name
                        else:
                            # Try archived threads
                            try:
                                thread = await asyncio.wait_for(
                                    self._bot.fetch_channel(thread_id),
                                    timeout=2.0
                                )
                                if thread:
                                    thread_name = thread.name
                            except Exception:
                                pass  # Non-critical: thread name enrichment

                        # Only include debates where we found the thread name
                        if thread_name != "Unknown Debate":
                            recent_debates.append({
                                "thread_id": thread_id,
                                "thread_name": thread_name,
                                "message_count": debate["message_count"],
                                "created_at": debate["created_at"]
                            })
            else:
                recent_debates = recent_debates_raw

            # Calculate approval rate
            total_votes = karma.upvotes_received + karma.downvotes_received
            approval_rate = round((karma.upvotes_received / total_votes * 100), 1) if total_votes > 0 else 0.0

            # Get tier based on karma
            tier = self._get_tier(karma.total_karma)

            response_data = {
                "user_id": str(user_id),  # String to avoid JS precision loss
                "name": display_name,
                "avatar": avatar_url,
                "karma": karma.total_karma,
                "rank": rank,
                "tier": tier,
                "rank_change": rank_change,
                "approval_rate": approval_rate,
                "upvotes_received": karma.upvotes_received,
                "downvotes_received": karma.downvotes_received,
                "debates_participated": analytics.get("debates_participated", 0),
                "debates_created": analytics.get("debates_created", 0),
                "total_messages": analytics.get("total_messages", 0),
                "current_streak": streak.get("current_streak", 0),
                "longest_streak": streak.get("longest_streak", 0),
                "karma_history": karma_history,
                "recent_debates": recent_debates,
                "generated_at": datetime.now(NY_TZ).isoformat(),
                "response_time_ms": round((time.time() - start_time) * 1000, 1),
                "cached": False,
            }

            # Cache for 30 seconds
            await self._cache.set(cache_key, response_data)

            logger.info("User Profile API Response Built", [
                ("User ID", str(user_id)),
                ("Response Time", f"{response_data['response_time_ms']}ms"),
            ])

            return web.json_response(
                response_data,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        except Exception as e:
            logger.error_tree("User Profile API Error", e)
            return web.json_response(
                {"error": "Internal server error"},
                status=500,
                headers={"Access-Control-Allow-Origin": "*"}
            )

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /health - Simple health check."""
        return web.json_response(
            {"status": "healthy", "bot": "OthmanBot"},
            headers={"Access-Control-Allow-Origin": "*"}
        )

    async def start(self) -> None:
        """Start the API server."""
        self._start_time = datetime.now(NY_TZ)
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(self.runner, STATS_API_HOST, STATS_API_PORT)
        await site.start()

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.success("Stats API Started", [
            ("Host", STATS_API_HOST),
            ("Port", str(STATS_API_PORT)),
            ("Endpoints", "/api/othman/stats, /api/othman/user/{id}, /health"),
        ])

    async def stop(self) -> None:
        """Stop the API server."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self.runner:
            await self.runner.cleanup()
            logger.info("Stats API Stopped")

    async def _cleanup_loop(self) -> None:
        """Periodically clean up rate limiter entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await rate_limiter.cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Rate limiter cleanup error", [("Error", str(e))])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["OthmanAPI", "STATS_API_PORT"]
