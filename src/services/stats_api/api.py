"""
OthmanBot - Stats API Server
============================

Main API server class for OthmanBot Dashboard.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import psutil
import time
from datetime import datetime
from aiohttp import web
from typing import TYPE_CHECKING, Optional

from src.core.logger import logger
from src.core.config import (
    NY_TZ, DEBATES_FORUM_ID, SYRIA_GUILD_ID,
    load_news_channel_id, load_soccer_channel_id, BASE_COMMAND_COUNT
)
from src.core.constants import (
    SLEEP_ERROR_RETRY,
    LEADERBOARD_DISPLAY_LIMIT,
    TRENDING_LIMIT,
    RECENT_ITEMS_LIMIT,
    HISTORY_LIMIT_MAX,
)
from src.utils.api_cache import ResponseCache
from src.services.stats_api.constants import (
    STATS_API_PORT, STATS_API_HOST, CACHE_TTL, get_tier
)
from src.services.stats_api.middleware import (
    rate_limit_middleware, security_headers_middleware,
    rate_limiter, get_client_ip
)
from src.services.stats_api.data_fetchers import (
    fetch_user_data, enrich_users_with_avatars,
    get_changelog, get_hot_debate, count_forum_threads,
    get_recent_threads, get_trending_debates, get_activity_sparkline
)

if TYPE_CHECKING:
    from src.bot import OthmanBot


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
        self.app.router.add_get("/api/othman/leaderboard", self.handle_leaderboard)
        self.app.router.add_get("/api/othman/user/{user_id}", self.handle_user_profile)
        self.app.router.add_get("/health", self.handle_health)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_guild_banner_url(self) -> str | None:
        """Get the current guild banner URL."""
        try:
            guild = self._bot.get_guild(SYRIA_GUILD_ID)
            if guild and guild.banner:
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

            news_count = await count_forum_threads(self._bot, news_channel_id)
            soccer_count = await count_forum_threads(self._bot, soccer_channel_id)
            total_news = news_count + soccer_count

        return {
            "total_commands": total_commands,
            "total_votes": total_votes,
            "total_news": total_news,
        }

    # =========================================================================
    # Route Handlers
    # =========================================================================

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
            category_leaderboards = {}

            if db:
                total_debates = db.get_active_debate_count()
                votes_today = db.get_votes_today()
                leaderboard_raw = db.get_leaderboard(limit=LEADERBOARD_DISPLAY_LIMIT)
                monthly_stats = db.get_monthly_stats(now.year, now.month)

                try:
                    monthly_leaderboard_raw = db.get_monthly_leaderboard(now.year, now.month, limit=LEADERBOARD_DISPLAY_LIMIT)
                except Exception as e:
                    logger.debug("Failed to get monthly leaderboard", [("Error", str(e))])

                try:
                    category_leaderboards = db.get_category_leaderboards(limit=LEADERBOARD_DISPLAY_LIMIT)
                except Exception as e:
                    logger.debug("Failed to get category leaderboards", [("Error", str(e))])

            # Enrich all-time leaderboard with avatars
            leaderboard_tuples = [
                (user.user_id, f"User {user.user_id}", user.total_karma)
                for user in leaderboard_raw
            ]
            leaderboard = await enrich_users_with_avatars(self._bot, leaderboard_tuples)

            # Get karma changes for leaderboard users
            karma_changes = {}
            if db and leaderboard:
                try:
                    user_ids = [u["user_id"] for u in leaderboard]
                    karma_changes = db.get_karma_changes_today(user_ids)
                except Exception as e:
                    logger.debug("Failed to get karma changes", [("Error", str(e))])

            # Calculate max karma and add progress, karma change, tier
            max_karma = max((u["karma"] for u in leaderboard), default=1)
            for user in leaderboard:
                user["progress"] = round((user["karma"] / max_karma) * 100, 1) if max_karma > 0 else 0
                user["karma_change"] = karma_changes.get(user["user_id"], 0)
                user["tier"] = get_tier(user["karma"])

            # Enrich monthly leaderboard
            monthly_tuples = [
                (user["user_id"], f"User {user['user_id']}", user["monthly_karma"])
                for user in monthly_leaderboard_raw
            ]
            monthly_leaderboard = await enrich_users_with_avatars(self._bot, monthly_tuples)

            monthly_karma_changes = {}
            if db and monthly_leaderboard:
                try:
                    monthly_user_ids = [u["user_id"] for u in monthly_leaderboard]
                    monthly_karma_changes = db.get_karma_changes_today(monthly_user_ids)
                except Exception as e:
                    logger.debug("Failed to get monthly karma changes", [("Error", str(e))])

            monthly_max_karma = max((u["karma"] for u in monthly_leaderboard), default=1)
            for user in monthly_leaderboard:
                user["progress"] = round((user["karma"] / monthly_max_karma) * 100, 1) if monthly_max_karma > 0 else 0
                user["karma_change"] = monthly_karma_changes.get(user["user_id"], 0)
                user["tier"] = get_tier(user["karma"])

            # Enrich category leaderboards
            enriched_categories = {}
            for category, users in category_leaderboards.items():
                if users:
                    value_key = "current_streak" if category == "streaks" else "message_count" if category == "active" else "debate_count"
                    category_tuples = [
                        (u["user_id"], f"User {u['user_id']}", u.get(value_key, 0))
                        for u in users
                    ]
                    enriched_list = await enrich_users_with_avatars(self._bot, category_tuples)
                    for i, enriched_user in enumerate(enriched_list):
                        enriched_user["value"] = users[i].get(value_key, 0)
                        enriched_user["tier"] = get_tier(enriched_user.get("karma", 0))
                    enriched_categories[category] = enriched_list
                else:
                    enriched_categories[category] = []

            # Get additional data
            hot_debate = await get_hot_debate(self._bot)
            news_channel_id = load_news_channel_id()
            soccer_channel_id = load_soccer_channel_id()
            recent_news = await get_recent_threads(self._bot, news_channel_id, limit=RECENT_ITEMS_LIMIT)
            recent_soccer = await get_recent_threads(self._bot, soccer_channel_id, limit=RECENT_ITEMS_LIMIT)
            trending_debates = await get_trending_debates(self._bot, limit=TRENDING_LIMIT)
            activity_sparkline = get_activity_sparkline(db)

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
                "changelog": await get_changelog(),
                "system": self._get_system_resources(),
                "guild_banner": self._get_guild_banner_url(),
                "generated_at": datetime.now(NY_TZ).isoformat(),
                "response_time_ms": round((time.time() - start_time) * 1000, 1),
                "cached": False,
            }

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

    async def handle_leaderboard(self, request: web.Request) -> web.Response:
        """GET /api/othman/leaderboard - Return karma leaderboard."""
        client_ip = get_client_ip(request)
        start_time = time.time()

        logger.info("Leaderboard API Request", [
            ("IP", client_ip),
            ("Path", "/api/othman/leaderboard"),
        ])

        cached = await self._cache.get("leaderboard")
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

            leaderboard_raw = db.get_leaderboard(limit=HISTORY_LIMIT_MAX)
            total_users = db.get_total_users() if hasattr(db, 'get_total_users') else len(leaderboard_raw)
            total_karma = db.get_total_karma() if hasattr(db, 'get_total_karma') else sum(u.total_karma for u in leaderboard_raw)

            leaderboard_tuples = [
                (user.user_id, f"User {user.user_id}", user.total_karma)
                for user in leaderboard_raw
            ]
            leaderboard = await enrich_users_with_avatars(self._bot, leaderboard_tuples)

            max_karma = max((u["karma"] for u in leaderboard), default=1)
            for i, user in enumerate(leaderboard, 1):
                user["rank"] = i
                user["progress"] = round((user["karma"] / max_karma) * 100, 1) if max_karma > 0 else 0
                user["tier"] = get_tier(user["karma"])

            response_data = {
                "leaderboard": leaderboard,
                "total_users": total_users,
                "total_karma": total_karma,
                "generated_at": datetime.now(NY_TZ).isoformat(),
                "response_time_ms": round((time.time() - start_time) * 1000, 1),
                "cached": False,
            }

            await self._cache.set("leaderboard", response_data)

            logger.info("Leaderboard API Response", [
                ("Users", str(len(leaderboard))),
                ("Response Time", f"{response_data['response_time_ms']}ms"),
            ])

            return web.json_response(
                response_data,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        except Exception as e:
            logger.error_tree("Leaderboard API Error", e)
            return web.json_response(
                {"error": "Internal server error"},
                status=500,
                headers={"Access-Control-Allow-Origin": "*"}
            )

    async def handle_user_profile(self, request: web.Request) -> web.Response:
        """GET /api/othman/user/{user_id} - Return user profile data."""
        client_ip = get_client_ip(request)
        start_time = time.time()

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

            karma = db.get_user_karma(user_id)
            rank = db.get_user_rank(user_id)
            analytics = db.get_user_analytics(user_id)
            streak = db.get_user_streak(user_id)

            has_activity = (
                karma.total_karma != 0 or
                karma.upvotes_received != 0 or
                karma.downvotes_received != 0 or
                analytics.get("debates_participated", 0) > 0 or
                analytics.get("total_messages", 0) > 0
            )

            avatar_url, display_name, is_booster = await fetch_user_data(self._bot, user_id, f"User {user_id}")

            if not has_activity and display_name == f"User {user_id}":
                return web.json_response(
                    {"error": "User not found"},
                    status=404,
                    headers={"Access-Control-Allow-Origin": "*"}
                )

            rank_change = db.get_rank_change(user_id)
            karma_history = db.get_karma_history(user_id, days=7)
            recent_debates_raw = db.get_user_recent_debates(user_id, limit=RECENT_ITEMS_LIMIT)

            # Enrich recent debates with thread names
            recent_debates = []
            if recent_debates_raw and self._bot and self._bot.is_ready():
                debates_forum = self._bot.get_channel(DEBATES_FORUM_ID)
                if debates_forum:
                    for debate in recent_debates_raw:
                        thread_id = debate["thread_id"]
                        thread_name = "Unknown Debate"

                        thread = debates_forum.get_thread(thread_id)
                        if thread:
                            thread_name = thread.name
                        else:
                            try:
                                thread = await asyncio.wait_for(
                                    self._bot.fetch_channel(thread_id),
                                    timeout=2.0
                                )
                                if thread:
                                    thread_name = thread.name
                            except Exception:
                                pass

                        if thread_name != "Unknown Debate":
                            recent_debates.append({
                                "thread_id": thread_id,
                                "thread_name": thread_name,
                                "message_count": debate["message_count"],
                                "created_at": debate["created_at"]
                            })
            else:
                recent_debates = recent_debates_raw

            total_votes = karma.upvotes_received + karma.downvotes_received
            approval_rate = round((karma.upvotes_received / total_votes * 100), 1) if total_votes > 0 else 0.0
            tier = get_tier(karma.total_karma)

            response_data = {
                "user_id": str(user_id),
                "name": display_name,
                "avatar": avatar_url,
                "is_booster": is_booster,
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

    # =========================================================================
    # Server Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the API server."""
        self._start_time = datetime.now(NY_TZ)
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(self.runner, STATS_API_HOST, STATS_API_PORT)
        await site.start()

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.success("Stats API Started", [
            ("Host", STATS_API_HOST),
            ("Port", str(STATS_API_PORT)),
            ("Endpoints", "/stats, /leaderboard, /user/{id}, /health"),
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
                await asyncio.sleep(SLEEP_ERROR_RETRY)
                await rate_limiter.cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Rate limiter cleanup error", [("Error", str(e))])


__all__ = ["OthmanAPI"]
