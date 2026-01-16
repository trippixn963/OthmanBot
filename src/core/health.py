"""
OthmanBot - Health Check Server
=========================================

Simple HTTP health check endpoint for monitoring bot status.

Runs on port 8080 and provides:
- /health - JSON status with uptime, latency, run_id
- / - Simple "OK" response for basic health checks

Usage:
    curl http://your-vps-ip:8080/health

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from aiohttp import web

from src.core.logger import logger
from src.core.config import NY_TZ

if TYPE_CHECKING:
    from src.bot import OthmanBot


# =============================================================================
# Health Check Server
# =============================================================================

class HealthCheckServer:
    """Simple HTTP server for health checks."""

    def __init__(self, bot: "OthmanBot", port: int = 8080) -> None:
        """
        Initialize health check server.

        Args:
            bot: The OthmanBot instance
            port: Port to run the server on (default: 8080)
        """
        self.bot = bot
        self.port = port
        self.start_time = datetime.now(NY_TZ)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def start(self) -> None:
        """Start the health check HTTP server."""
        app = web.Application()
        app.router.add_get("/", self._handle_root)
        app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await self._site.start()

        logger.tree("Health Check Server Started", [
            ("Port", str(self.port)),
            ("Endpoints", "/, /health"),
        ], emoji="🏥")

    async def stop(self) -> None:
        """Stop the health check HTTP server."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("Health Check Server Stopped", [
                ("Status", "Server shutdown complete"),
            ])

    async def _handle_root(self, request: web.Request) -> web.Response:
        """Handle root endpoint - simple OK response."""
        return web.Response(text="OK", content_type="text/plain")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle /health endpoint - detailed JSON status."""
        now = datetime.now(NY_TZ)
        uptime_seconds = (now - self.start_time).total_seconds()

        # Format uptime as human-readable
        hours, remainder = divmod(int(uptime_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        # Get bot status
        is_ready = self.bot.is_ready()
        latency_ms = round(self.bot.latency * 1000) if is_ready else None

        # Check database connectivity
        db_healthy = False
        db_error: Optional[str] = None
        try:
            if self.bot.debates_service and self.bot.debates_service.db:
                # Simple query to verify database is accessible
                db_healthy = self.bot.debates_service.db.health_check()
        except Exception as e:
            db_error = str(e)

        # Overall health: Discord connected AND database accessible
        overall_healthy = is_ready and db_healthy

        status = {
            "status": "healthy" if overall_healthy else ("degraded" if is_ready else "starting"),
            "run_id": logger.run_id,
            "uptime": uptime_str,
            "uptime_seconds": int(uptime_seconds),
            "started_at": self.start_time.isoformat(),
            "timestamp": now.isoformat(),
            "discord": {
                "connected": is_ready,
                "latency_ms": latency_ms,
                "guilds": len(self.bot.guilds) if is_ready else 0,
            },
            "database": {
                "connected": db_healthy,
                "error": db_error,
            },
        }

        # Return 503 if unhealthy for proper monitoring integration
        status_code = 200 if overall_healthy else 503
        return web.json_response(status, status=status_code)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["HealthCheckServer"]
