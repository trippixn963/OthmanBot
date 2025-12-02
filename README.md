# OthmanBot - Automated Discord Community Bot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![Discord.py](https://img.shields.io/badge/Discord.py-2.3.2+-green.svg)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-orange.svg)

**Fully automated multilingual news posting with AI-generated summaries + Debates karma system**

*Built for discord.gg/syria*

[![Join Discord Server](https://img.shields.io/badge/Join%20Server-discord.gg/syria-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)

</div>

---

## What is OthmanBot?

A fully automated Discord bot that:
- Posts hourly news updates from multiple sources with AI-generated bilingual summaries (Arabic/English)
- Manages a debate forum with karma voting, hostility tracking, and analytics
- Covers Syrian news, soccer/football, and gaming across separate channels

**Custom-built for discord.gg/syria - No support provided**

---

## Features

### Content Automation
- **100% Automated** - Zero commands needed, runs 24/7 autonomously
- **Bilingual Summaries** - AI-generated Arabic and English summaries
- **Multi-Content** - News, Soccer, Gaming on hourly rotation
- **Rich Media** - Images and videos embedded in forum posts
- **Forum Threads** - Auto-creates discussion threads with category tags
- **Announcements** - Sends notification embeds to general channel
- **Smart Caching** - AI response caching to reduce API costs

### Debates System
- **Karma Voting** - Upvote/downvote system with persistent karma tracking
- **Hostility Tracking** - AI-powered detection of hostile messages with warnings
- **Auto-Tagging** - AI detects relevant topic tags for new debates
- **Hot Tag Manager** - Dynamically adds/removes "Hot" tag based on activity
- **Analytics** - Thread engagement metrics and participant tracking
- **Moderation** - /disallow and /allow commands for debate bans
- **Karma Reconciliation** - Nightly sync to catch any missed votes
- **Leaderboard** - Forum post with monthly/all-time rankings, updated hourly:
  - Monthly & All-Time Top 10 with vote breakdown
  - Most Active Debates (top 3 by message count)
  - Most Active Participants (top 3 by messages)
  - Debate Starters (top 3 by debates created)
  - Community Stats (total debates, votes, most active day)

---

## Quick Start

```bash
# Clone and setup
git clone https://github.com/trippixn963/OthmanBot.git
cd OthmanBot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your tokens and IDs

# Run
python main.py
```

---

## Configuration

### Environment Variables

Essential variables in `.env`:

```env
# Discord
DISCORD_TOKEN=your_bot_token

# OpenAI
OPENAI_API_KEY=your_api_key

# Channels (Forum channels)
NEWS_CHANNEL_ID=news_forum_channel
SOCCER_CHANNEL_ID=soccer_forum_channel
GAMING_CHANNEL_ID=gaming_forum_channel
GENERAL_CHANNEL_ID=announcements_channel
```

### Centralized IDs

All Discord IDs (guild, roles, forum tags) are centralized in `src/core/config.py`:

```python
# Guild/Server IDs
SYRIA_GUILD_ID: int = ...

# Role IDs
MODERATOR_ROLE_ID: int = ...
DEVELOPER_ID: int = ...

# Forum IDs
DEBATES_FORUM_ID: int = ...

# Forum Tag IDs
NEWS_FORUM_TAGS: dict[str, int] = {...}
SOCCER_TEAM_TAG_IDS: dict[str, int] = {...}
DEBATE_TAGS: dict[str, int] = {...}
```

### Discord Bot Setup
- Enable "Message Content Intent"
- Invite bot with permissions: Send Messages, Manage Messages, Create Public Threads, Embed Links, Add Reactions

---

## Posting Schedule

| Content | Rotation | Frequency |
|---------|----------|-----------|
| News    | Hour 0   | Every 3 hours |
| Soccer  | Hour 1   | Every 3 hours |
| Gaming  | Hour 2   | Every 3 hours |

Each post includes:
- AI-generated 3-5 word English title
- Bilingual summary (Arabic + English)
- Source image/video
- Category tags
- Announcement embed in general channel

---

## News Sources

**Syrian News:**
- Enab Baladi - Syria-focused independent journalism

**Soccer:**
- Kooora - Arabic football/soccer news

**Gaming:**
- This Week in Videogames - Gaming industry news

---

## Project Structure

```
OthmanBot/
├── src/
│   ├── bot.py                          # Main bot class
│   ├── core/
│   │   ├── config.py                   # Centralized IDs and configuration
│   │   ├── logger.py                   # Custom EST logging
│   │   └── presence.py                 # Bot presence management
│   ├── handlers/
│   │   ├── ready.py                    # Bot startup and service init
│   │   └── debates.py                  # Debate forum event handlers
│   ├── commands/
│   │   └── debates.py                  # /disallow, /allow, /karma commands
│   ├── services/
│   │   ├── news_scraper.py             # News RSS scraping + AI
│   │   ├── soccer_scraper.py           # Soccer RSS scraping + AI
│   │   ├── gaming_scraper.py           # Gaming RSS scraping + AI
│   │   ├── schedulers/
│   │   │   └── rotation.py             # Unified content rotation
│   │   └── debates/
│   │       ├── database.py             # SQLite karma/votes/hostility storage
│   │       ├── analytics.py            # Thread engagement metrics
│   │       ├── hostility.py            # AI hostility detection
│   │       ├── tags.py                 # AI auto-tagging
│   │       ├── hot_tag_manager.py      # Dynamic "Hot" tag management
│   │       ├── scheduler.py            # Hot debates scheduler
│   │       ├── reconciliation.py       # Karma sync logic
│   │       ├── karma_scheduler.py      # Nightly reconciliation
│   │       └── leaderboard.py          # Forum leaderboard manager
│   ├── posting/
│   │   ├── news.py                     # News posting logic
│   │   ├── soccer.py                   # Soccer posting logic
│   │   ├── gaming.py                   # Gaming posting logic
│   │   └── debates.py                  # Hot debates posting
│   └── utils/
│       ├── ai_cache.py                 # AI response caching
│       └── retry.py                    # Exponential backoff
├── data/                               # Runtime data & caches
├── logs/                               # Log files
├── main.py                             # Entry point
└── requirements.txt                    # Dependencies
```

**Tech Stack:** discord.py, OpenAI GPT-4o-mini, feedparser, BeautifulSoup, aiohttp, SQLite

---

## How It Works

### Content Automation
1. **Startup** - Loads caches, initializes scrapers and rotation scheduler
2. **Rotation** - Single scheduler rotates through news → soccer → gaming hourly
3. **Fetching** - Scrapes RSS feeds for latest articles
4. **AI Processing** - Generates titles and bilingual summaries
5. **Posting** - Creates forum thread with media and tags
6. **Announcing** - Sends embed to general channel
7. **Caching** - Marks article as posted, saves AI responses

### Debates System
1. **Thread Creation** - AI auto-tags new debate threads
2. **Voting** - Bot adds reaction buttons, tracks votes in SQLite
3. **Karma** - Accumulated per-user based on votes received
4. **Hostility** - AI monitors for hostile messages, issues warnings
5. **Hot Tags** - Threads with high activity get "Hot" tag
6. **Reconciliation** - Nightly sync catches any missed votes

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/karma [user]` | View karma stats for yourself or another user |
| `/disallow <user>` | Ban user from debates (moderator only) |
| `/allow <user>` | Unban user from debates (moderator only) |

---

## Disclaimer

Educational purposes only. No support provided. Use at own risk.

---

## Author

<div align="center">

**حَـــــنَّـــــا**

*Built for discord.gg/syria*

[![Discord](https://img.shields.io/badge/Discord-discord.gg/syria-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/syria)

</div>
