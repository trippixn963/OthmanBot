"""
OthmanBot - Karma Card Generator
================================

HTML/CSS based karma card rendered with Playwright for professional quality.
Optimized with page pooling and caching for fast generation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional

from src.core.logger import logger
from src.services.playwright_pool import get_page, return_page, get_render_semaphore


# =============================================================================
# Constants
# =============================================================================

# Brand colors (matching SyriaBot)
COLOR_GREEN = "#1F5E2E"
COLOR_GOLD = "#E6B84A"

# Status colors for Discord presence
STATUS_COLORS = {
    "online": "#3ba55c",
    "idle": "#faa61a",
    "dnd": "#ed4245",
    "offline": "#747f8d",
    "streaming": "#9146ff",
}

# Card cache: {cache_key: (bytes, timestamp)}
_card_cache: dict = {}
_CACHE_TTL = 30  # Cache cards for 30 seconds


# =============================================================================
# Tier System
# =============================================================================

def get_tier(karma: int) -> tuple[str, str, str]:
    """
    Get tier info based on karma.

    Returns:
        Tuple of (tier_name, tier_color, tier_gradient)
    """
    if karma >= 500:
        return ("Diamond", "#b9f2ff", "linear-gradient(145deg, #b9f2ff, #7dd3fc, #38bdf8)")
    elif karma >= 250:
        return ("Gold", COLOR_GOLD, f"linear-gradient(145deg, #f5d55a, {COLOR_GOLD}, #cc9900)")
    elif karma >= 100:
        return ("Silver", "#c0c0c0", "linear-gradient(145deg, #e8e8e8, #c0c0c0, #a8a8a8)")
    elif karma >= 50:
        return ("Bronze", "#cd7f32", "linear-gradient(145deg, #daa06d, #cd7f32, #a0522d)")
    else:
        return ("", "", "")  # No tier badge for unranked


# =============================================================================
# HTML Template
# =============================================================================

def _generate_html(
    display_name: str,
    username: str,
    avatar_url: str,
    karma: int,
    rank: int,
    upvotes: int,
    downvotes: int,
    status: str,
    banner_url: Optional[str] = None,
) -> str:
    """Generate HTML for karma card."""

    status_color = STATUS_COLORS.get(status, STATUS_COLORS["online"])
    tier_name, tier_color, tier_gradient = get_tier(karma)

    # Calculate approval rate
    total_votes = upvotes + downvotes
    approval_rate = round((upvotes / total_votes * 100), 1) if total_votes > 0 else 0.0

    # Background style
    bg_style = f'url({banner_url})' if banner_url else 'linear-gradient(135deg, #0f0f17 0%, #1a1a28 100%)'

    # Tier badge HTML (only show if user has a tier)
    tier_badge = ""
    if tier_name:
        tier_badge = f'''
            <div class="badge tier-badge" style="background: {tier_gradient};">
                <span class="badge-label">Tier</span>
                <span class="badge-value">{tier_name}</span>
            </div>
        '''

    html = f'''
<!DOCTYPE html>
<html>
<head>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: transparent;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }}

        .card-wrapper {{
            padding: 3px;
            background: linear-gradient(135deg, {COLOR_GREEN}, {COLOR_GOLD}, {COLOR_GREEN});
            border-radius: 20px;
            position: relative;
            box-shadow:
                0 8px 32px rgba(0,0,0,0.5),
                0 0 40px rgba(31, 94, 46, 0.3),
                0 0 40px rgba(230, 184, 74, 0.2);
        }}

        .card-wrapper::before {{
            content: '';
            position: absolute;
            inset: -6px;
            border-radius: 26px;
            background: linear-gradient(135deg, {COLOR_GREEN}44, {COLOR_GOLD}33, {COLOR_GREEN}44);
            filter: blur(16px);
            opacity: 0.8;
            z-index: -1;
        }}

        .card {{
            width: 934px;
            height: 280px;
            background: {bg_style};
            background-size: cover;
            background-position: center;
            border-radius: 21px;
            position: relative;
            overflow: hidden;
        }}

        .card::before {{
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(12, 12, 18, 0.92) 0%, rgba(18, 18, 28, 0.88) 100%);
            backdrop-filter: blur(12px);
        }}

        .card-content {{
            position: relative;
            z-index: 1;
            display: flex;
            height: 100%;
            padding: 32px 40px;
            gap: 36px;
        }}

        /* Avatar Section */
        .avatar-section {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}

        .avatar-wrapper {{
            position: relative;
            width: 180px;
            height: 180px;
        }}

        .avatar-ring {{
            position: absolute;
            inset: -6px;
            border-radius: 50%;
            border: 6px solid {status_color};
            background: transparent;
        }}

        .avatar-ring::before {{
            content: '';
            position: absolute;
            inset: -12px;
            border-radius: 50%;
            background: {status_color};
            filter: blur(20px);
            opacity: 0.4;
            z-index: -1;
        }}

        .avatar {{
            width: 180px;
            height: 180px;
            border-radius: 50%;
            object-fit: cover;
            position: relative;
            z-index: 1;
        }}

        .status-dot {{
            position: absolute;
            bottom: 5px;
            right: 5px;
            width: 44px;
            height: 44px;
            background: {status_color};
            border: 8px solid #14141f;
            border-radius: 50%;
            z-index: 3;
            box-shadow: 0 0 12px {status_color}66;
        }}

        /* Info Section */
        .info-section {{
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 16px;
        }}

        /* Top Row - Name and Badges */
        .top-row {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}

        .names {{
            display: flex;
            flex-direction: column;
            gap: 2px;
        }}

        .display-name {{
            font-size: 40px;
            font-weight: 800;
            color: #fff;
            text-shadow: 0 2px 8px rgba(0,0,0,0.5);
            line-height: 1.1;
            letter-spacing: -0.5px;
        }}

        .username {{
            font-size: 16px;
            font-weight: 500;
            color: #6b7280;
        }}

        .badges {{
            display: flex;
            gap: 8px;
            align-items: flex-start;
        }}

        .badge {{
            display: flex;
            flex-direction: column;
            align-items: center;
            border-radius: 12px;
            padding: 8px 16px;
            min-width: 72px;
            position: relative;
            overflow: hidden;
        }}

        .badge.rank-badge {{
            background: linear-gradient(145deg, #3a3a4a, #2a2a3a);
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }}

        .badge.karma-badge {{
            background: linear-gradient(145deg, {COLOR_GREEN}, #165c26, #0f4d1c);
            border: 1px solid rgba(255,255,255,0.2);
            box-shadow: 0 4px 16px rgba(31, 94, 46, 0.5);
        }}

        .badge.tier-badge {{
            border: 1px solid rgba(255,255,255,0.25);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
        }}

        .badge::after {{
            content: '';
            position: absolute;
            top: 0;
            left: 15%;
            width: 35%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent);
            transform: skewX(-20deg);
        }}

        .badge-label {{
            font-size: 9px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            margin-bottom: 2px;
            opacity: 0.7;
        }}

        .badge.rank-badge .badge-label {{
            color: #9ca3af;
        }}

        .badge.karma-badge .badge-label,
        .badge.tier-badge .badge-label {{
            color: rgba(255,255,255,0.8);
        }}

        .badge-value {{
            font-size: 22px;
            font-weight: 900;
            color: #fff;
            text-shadow: 0 1px 3px rgba(0,0,0,0.3);
        }}

        /* Stats Section - Connected like JawdatBot */
        .stats-section {{
            display: flex;
            gap: 24px;
            padding: 16px 24px;
            background: rgba(255,255,255,0.05);
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.08);
        }}

        .stat {{
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
        }}

        .stat-value {{
            font-size: 26px;
            font-weight: 800;
            color: #fff;
        }}

        .stat-value.upvotes {{
            color: #57f287;
        }}

        .stat-value.downvotes {{
            color: #ed4245;
        }}

        .stat-value.approval {{
            color: #e6b84a;
        }}

        .stat-label {{
            font-size: 12px;
            font-weight: 600;
            color: #8a8a9a;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 4px;
        }}

        .stat-divider {{
            width: 1px;
            background: rgba(255,255,255,0.1);
        }}
    </style>
</head>
<body>
    <div class="card-wrapper">
    <div class="card">
        <div class="card-content">
            <div class="avatar-section">
                <div class="avatar-wrapper">
                    <div class="avatar-ring"></div>
                    <img class="avatar" src="{avatar_url}" alt="avatar">
                    <div class="status-dot"></div>
                </div>
            </div>

            <div class="info-section">
                <div class="top-row">
                    <div class="names">
                        <div class="display-name">{display_name}</div>
                        <div class="username">@{username}</div>
                    </div>
                    <div class="badges">
                        <div class="badge rank-badge">
                            <span class="badge-label">Rank</span>
                            <span class="badge-value">#{rank}</span>
                        </div>
                        <div class="badge karma-badge">
                            <span class="badge-label">Karma</span>
                            <span class="badge-value">{karma:,}</span>
                        </div>
                        {tier_badge}
                    </div>
                </div>

                <div class="stats-section">
                    <div class="stat">
                        <span class="stat-value upvotes">+{upvotes:,}</span>
                        <span class="stat-label">Upvotes</span>
                    </div>
                    <div class="stat-divider"></div>
                    <div class="stat">
                        <span class="stat-value downvotes">-{downvotes:,}</span>
                        <span class="stat-label">Downvotes</span>
                    </div>
                    <div class="stat-divider"></div>
                    <div class="stat">
                        <span class="stat-value approval">{approval_rate}%</span>
                        <span class="stat-label">Approval</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    </div>
</body>
</html>
'''
    return html


# =============================================================================
# Card Generation
# =============================================================================

async def generate_karma_card(
    username: str,
    display_name: str,
    avatar_url: str,
    karma: int,
    rank: int,
    upvotes: int,
    downvotes: int,
    status: str = "online",
    banner_url: Optional[str] = None,
) -> bytes:
    """
    Generate karma card using Playwright with caching and page pooling.

    Args:
        username: Discord username
        display_name: Display name
        avatar_url: Avatar URL
        karma: Total karma points
        rank: Leaderboard rank
        upvotes: Total upvotes received
        downvotes: Total downvotes received
        status: Discord presence status
        banner_url: Optional banner URL for background

    Returns:
        PNG image bytes
    """
    global _card_cache

    # Create cache key from data that affects appearance
    cache_key = (
        username, display_name, karma, rank, upvotes, downvotes,
        status, avatar_url[:50] if avatar_url else ""
    )

    # Check cache
    now = time.time()
    if cache_key in _card_cache:
        cached_bytes, cached_time = _card_cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            logger.tree("Karma Card Cache Hit", [
                ("User", display_name),
            ], emoji="⚡")
            return cached_bytes

    # Clean old cache entries periodically
    if len(_card_cache) > 100:
        _card_cache.clear()

    # Use semaphore to limit concurrent renders
    async with get_render_semaphore():
        page = None
        try:
            page = await get_page()

            # Clear page before each render
            await page.goto('about:blank')

            # Set viewport size for karma card (matching SyriaBot/JawdatBot)
            await page.set_viewport_size({'width': 960, 'height': 300})

            # Generate HTML
            html = _generate_html(
                display_name=display_name[:16] + "..." if len(display_name) > 16 else display_name,
                username=username,
                avatar_url=avatar_url,
                karma=karma,
                rank=rank,
                upvotes=upvotes,
                downvotes=downvotes,
                status=status,
                banner_url=banner_url,
            )

            await page.set_content(html, wait_until='networkidle')

            # Wait for avatar with short timeout
            try:
                await page.wait_for_function(
                    '''() => {
                        const img = document.querySelector('img.avatar');
                        return img && img.complete && img.naturalWidth > 0;
                    }''',
                    timeout=2000
                )
            except Exception:
                # Fallback - hide avatar and show initial
                await page.evaluate('''(initial) => {
                    const img = document.querySelector('img.avatar');
                    if (img) {
                        img.style.display = 'none';
                        const wrapper = document.querySelector('.avatar-wrapper');
                        if (wrapper) {
                            const fallback = document.createElement('div');
                            fallback.style.cssText = 'width:180px;height:180px;border-radius:50%;background:linear-gradient(135deg,#3a3a4a,#2a2a3a);display:flex;align-items:center;justify-content:center;font-size:64px;color:#fff;font-weight:700;';
                            fallback.textContent = initial;
                            wrapper.insertBefore(fallback, img);
                        }
                    }
                }''', display_name[0].upper() if display_name else "?")

            # Screenshot
            screenshot = await page.screenshot(type='png', omit_background=True)

            # Return page to pool
            await return_page(page)
            page = None

            # Cache the result
            _card_cache[cache_key] = (screenshot, now)

            logger.tree("Karma Card Generated", [
                ("User", display_name),
                ("Karma", str(karma)),
                ("Rank", f"#{rank}"),
            ], emoji="🎨")

            return screenshot

        except Exception as e:
            logger.error("Karma Card Failed", [
                ("User", display_name),
                ("Error", str(e)[:100]),
            ])
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            raise


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["generate_karma_card", "get_tier"]
