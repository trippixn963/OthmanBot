"""
OthmanBot - Stats API Middleware
================================

Security and rate limiting middleware for the stats API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from aiohttp import web

from src.core.logger import logger
from src.utils.api_cache import RateLimiter

# Global rate limiter instance
rate_limiter = RateLimiter(requests_per_minute=60, burst_limit=10)


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


__all__ = [
    "rate_limiter",
    "get_client_ip",
    "rate_limit_middleware",
    "security_headers_middleware",
]
