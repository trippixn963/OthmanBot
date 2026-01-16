"""
OthmanBot - Playwright Pool Manager
===================================

Manages a shared Playwright browser instance and page pool for efficient
HTML-to-image rendering. Optimized for low memory usage and stability.

Features:
- Singleton browser/context pattern
- Page pooling to avoid creation overhead
- Idle timeout (closes browser after inactivity)
- Periodic restart to clear memory leaks
- Semaphore to limit concurrent renders
- Graceful cleanup on shutdown

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import atexit
import time
from typing import Optional
from playwright.async_api import async_playwright, Page, BrowserContext

from src.core.logger import logger


# =============================================================================
# Browser State (Singleton)
# =============================================================================

_browser = None
_context = None
_playwright = None

# Page pool for reuse (avoid creating/destroying pages)
_page_pool: list = []
_page_pool_lock = asyncio.Lock()
_MAX_POOL_SIZE = 2  # Reduced to save memory

# Track last activity for idle timeout
_last_activity: float = 0
_IDLE_TIMEOUT = 120  # Close browser after 2 minutes of inactivity

# Track renders for periodic browser restart (clears memory leaks)
_render_count: int = 0
_RESTART_AFTER_RENDERS = 50  # Restart browser every 50 renders

# Semaphore to limit concurrent card generations
_render_semaphore: Optional[asyncio.Semaphore] = None


# =============================================================================
# Semaphore Management
# =============================================================================

def get_render_semaphore() -> asyncio.Semaphore:
    """Get or create the shared render semaphore."""
    global _render_semaphore
    if _render_semaphore is None:
        _render_semaphore = asyncio.Semaphore(1)  # Only 1 concurrent render
    return _render_semaphore


# =============================================================================
# Cleanup Handlers
# =============================================================================

def _sync_cleanup():
    """Synchronous cleanup for atexit/signal handlers."""
    import subprocess
    try:
        # Kill any orphaned chrome-headless-shell processes
        subprocess.run(
            ['pkill', '-f', 'chrome-headless-shell'],
            capture_output=True,
            timeout=5
        )
    except Exception:
        pass


# Register cleanup handlers
atexit.register(_sync_cleanup)


# =============================================================================
# Idle & Memory Management
# =============================================================================

async def _check_idle_timeout():
    """Check if browser should be closed due to inactivity."""
    global _last_activity
    if _browser is not None and _last_activity > 0:
        idle_time = time.time() - _last_activity
        if idle_time > _IDLE_TIMEOUT:
            logger.tree("Playwright Idle Timeout", [
                ("Idle Time", f"{int(idle_time)}s"),
                ("Action", "Closing browser"),
            ], emoji="💤")
            await cleanup()


async def _check_render_restart():
    """Check if browser should be restarted due to render count (memory cleanup)."""
    global _render_count
    if _browser is not None and _render_count >= _RESTART_AFTER_RENDERS:
        logger.tree("Playwright Restart", [
            ("Render Count", str(_render_count)),
            ("Action", "Restarting for memory cleanup"),
        ], emoji="🔄")
        await cleanup()
        _render_count = 0


# =============================================================================
# Context Management
# =============================================================================

async def _force_reset_state():
    """Force reset all state variables without cleanup (for crash recovery)."""
    global _browser, _context, _playwright, _page_pool, _render_count, _last_activity

    _browser = None
    _context = None
    _playwright = None
    _page_pool.clear()
    _render_count = 0
    _last_activity = 0

    # Kill any orphaned chrome processes
    _sync_cleanup()


async def _launch_browser(width: int, height: int) -> BrowserContext:
    """Launch browser and create context."""
    global _browser, _context, _playwright

    logger.tree("Playwright Starting", [
        ("Action", "Launching Chromium"),
        ("Viewport", f"{width}x{height}"),
    ], emoji="🚀")

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-extensions',
            '--disable-background-networking',
            '--disable-sync',
            '--disable-translate',
            '--hide-scrollbars',
            '--metrics-recording-only',
            '--mute-audio',
            '--no-first-run',
            # Additional memory optimization flags
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-component-update',
            '--disable-default-apps',
            '--disable-hang-monitor',
            '--disable-popup-blocking',
            '--disable-prompt-on-repost',
            '--js-flags=--max-old-space-size=128',
        ]
    )
    _context = await _browser.new_context(
        viewport={'width': width, 'height': height},
        device_scale_factor=1,
    )
    logger.tree("Playwright Ready", [
        ("Viewport", f"{width}x{height}"),
    ], emoji="✅")

    return _context


async def get_context(width: int = 940, height: int = 300) -> BrowserContext:
    """Get or create browser context (reusable) with crash recovery."""
    global _browser, _context, _playwright, _last_activity

    # Check if we should close idle browser first
    await _check_idle_timeout()

    # Check if we should restart browser for memory cleanup
    await _check_render_restart()

    if _context is None:
        try:
            await _launch_browser(width, height)
        except Exception as e:
            logger.tree("Playwright Launch Failed", [
                ("Error", str(e)[:100]),
                ("Action", "Resetting state and retrying"),
            ], emoji="❌")
            # Reset all state and try again
            await _force_reset_state()
            try:
                await _launch_browser(width, height)
            except Exception as retry_error:
                logger.tree("Playwright Retry Failed", [
                    ("Error", str(retry_error)[:100]),
                ], emoji="💀")
                raise
    else:
        # Verify existing context is still valid
        try:
            # Simple health check - try to get pages
            _ = _context.pages
        except Exception as e:
            logger.tree("Playwright Context Invalid", [
                ("Error", str(e)[:50]),
                ("Action", "Recovering"),
            ], emoji="⚠️")
            await _force_reset_state()
            await _launch_browser(width, height)

    _last_activity = time.time()
    return _context


# =============================================================================
# Page Pool Management
# =============================================================================

async def get_page() -> Page:
    """Get a page from pool or create new one."""
    global _render_count, _last_activity

    async with _page_pool_lock:
        if _page_pool:
            _last_activity = time.time()
            return _page_pool.pop()

    context = await get_context()
    page = await context.new_page()
    _last_activity = time.time()
    return page


async def return_page(page: Page) -> None:
    """Return page to pool for reuse."""
    global _render_count, _last_activity

    _render_count += 1
    _last_activity = time.time()

    async with _page_pool_lock:
        if len(_page_pool) < _MAX_POOL_SIZE:
            _page_pool.append(page)
        else:
            try:
                await page.close()
            except Exception as e:
                logger.tree("Playwright Page Close Failed", [
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")


# =============================================================================
# Cleanup
# =============================================================================

async def cleanup() -> None:
    """Clean up browser resources. Call on bot shutdown."""
    global _browser, _context, _playwright, _page_pool, _render_count, _last_activity

    _last_activity = 0

    # Close all pooled pages
    async with _page_pool_lock:
        for page in _page_pool:
            try:
                await page.close()
            except Exception:
                pass
        _page_pool.clear()

    # Close context
    if _context:
        try:
            await _context.close()
        except Exception:
            pass
        _context = None

    # Close browser
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None

    # Stop playwright
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None

    # Force kill any remaining chrome processes
    _sync_cleanup()

    _render_count = 0
    logger.tree("Playwright Cleanup", [
        ("Status", "Complete"),
    ], emoji="🧹")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "get_context",
    "get_page",
    "return_page",
    "cleanup",
    "get_render_semaphore",
]
