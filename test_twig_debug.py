#!/usr/bin/env python3
"""Debug script to test TWIG RSS parsing."""

import asyncio
import feedparser
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import aiohttp

async def debug_twig():
    print("=== TWIG RSS FEED DEBUG ===\n")

    # Fetch and parse RSS feed
    feed = feedparser.parse("https://thisweekinvideogames.com/feed/")

    print(f"Feed title: {feed.feed.get('title', 'N/A')}")
    print(f"Total entries: {len(feed.entries)}\n")

    if not feed.entries:
        print("❌ NO ENTRIES IN FEED!")
        return

    cutoff = datetime.now() - timedelta(hours=168)  # 7 days

    # Check first 3 entries in detail
    for i, entry in enumerate(feed.entries[:3]):
        print(f"--- Entry {i+1} ---")
        print(f"Title: {entry.get('title', 'N/A')[:60]}")
        print(f"Link: {entry.get('link', 'N/A')[:80]}")

        # Date parsing
        date_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
        if date_tuple:
            pub_date = datetime(*date_tuple[:6])
            print(f"Date: {pub_date} ({'✅ Recent' if pub_date > cutoff else '❌ Too old'})")
        else:
            print("Date: ⚠️ No parsable date (will use now)")
            pub_date = datetime.now()

        # Check for images in RSS
        has_image = False
        image_sources = []

        if "media_content" in entry:
            image_sources.append(f"media_content: {len(entry.media_content)} items")
            has_image = True

        if "media_thumbnail" in entry and entry.media_thumbnail:
            image_sources.append(f"media_thumbnail: {entry.media_thumbnail[0].get('url', 'N/A')[:50]}")
            has_image = True

        if "enclosures" in entry and entry.enclosures:
            for enc in entry.enclosures:
                if enc.get("type", "").startswith("image/"):
                    image_sources.append(f"enclosure: {enc.get('href', 'N/A')[:50]}")
                    has_image = True

        # Check content for embedded images
        content = entry.get("summary", "") or entry.get("description", "")
        if content:
            soup = BeautifulSoup(content, "html.parser")
            img_tag = soup.find("img")
            if img_tag and img_tag.get("src"):
                image_sources.append(f"content img: {img_tag['src'][:50]}")
                has_image = True

        print(f"Image sources: {image_sources if image_sources else '❌ NONE FOUND'}")

        # Fetch article page to check for og:image
        url = entry.get("link", "")
        if url:
            async with aiohttp.ClientSession() as session:
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                    async with session.get(url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, "html.parser")

                            # Check og:image
                            og_image = soup.find("meta", property="og:image")
                            if og_image and og_image.get("content"):
                                print(f"og:image: ✅ {og_image['content'][:60]}")
                                has_image = True
                            else:
                                print("og:image: ❌ Not found")

                            # Check for article content
                            # Try common selectors for WordPress
                            selectors = [
                                ("entry-content", "div", {"class": "entry-content"}),
                                ("post-content", "div", {"class": "post-content"}),
                                ("article-content", "div", {"class": "article-content"}),
                                ("article", "article", {}),
                            ]

                            content_found = False
                            for name, tag, attrs in selectors:
                                elem = soup.find(tag, attrs) if attrs else soup.find(tag)
                                if elem:
                                    paragraphs = elem.find_all("p")
                                    if paragraphs:
                                        text = "\n".join([p.get_text().strip() for p in paragraphs[:3]])
                                        print(f"Content ({name}): ✅ {len(text)} chars")
                                        content_found = True
                                        break

                            if not content_found:
                                print("Content: ❌ No article body found")
                        else:
                            print(f"Page fetch: ❌ HTTP {response.status}")
                except Exception as e:
                    print(f"Page fetch error: {str(e)[:50]}")

        print(f"Would be scraped: {'✅ YES' if has_image else '❌ NO (missing image)'}\n")

if __name__ == "__main__":
    asyncio.run(debug_twig())
