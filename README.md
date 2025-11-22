# 📰 OthmanBot - Automated News Discord Bot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![Discord.py](https://img.shields.io/badge/Discord.py-2.3.2+-green.svg)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--3.5-orange.svg)

**Fully automated multilingual news posting with AI-generated summaries**

*Built for discord.gg/syria*

[![Join Discord Server](https://img.shields.io/badge/Join%20Server-discord.gg/syria-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)

</div>

---

## 🎯 What is OthmanBot?

A fully automated Discord bot that posts hourly news updates from multiple sources with AI-generated bilingual summaries (Arabic/English). Covers Syrian news, soccer/football, and gaming across three separate channels.

**⚠️ Custom-built for discord.gg/syria • No support provided**

---

## ✨ Features

- 🤖 **100% Automated** - Zero commands, runs 24/7 autonomously
- 🌍 **Bilingual Summaries** - AI-generated Arabic and English summaries
- 📰 **Multi-Content** - News, Soccer, Gaming on separate schedules
- 🖼️ **Rich Media** - Images and videos embedded in forum posts
- 💬 **Forum Threads** - Auto-creates discussion threads with category tags
- 🔔 **Announcements** - Sends notification embeds to general channel
- 🧠 **Smart Caching** - AI response caching to reduce API costs
- 🔄 **Self-Healing** - Exponential backoff retry on failures

---

## 🚀 Quick Start

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

## ⚙️ Configuration

Essential environment variables in `.env`:

```env
# Discord
DISCORD_TOKEN=your_bot_token
DEVELOPER_ID=your_user_id

# OpenAI
OPENAI_API_KEY=your_api_key

# Channels (Forum channels)
NEWS_CHANNEL_ID=news_forum_channel
SOCCER_CHANNEL_ID=soccer_forum_channel
GAMING_CHANNEL_ID=gaming_forum_channel
GENERAL_CHANNEL_ID=announcements_channel
```

**Discord Bot Setup:**
- Enable "Message Content Intent"
- Invite bot with permissions: Send Messages, Manage Messages, Create Public Threads, Embed Links

---

## 📅 Posting Schedule

| Content | Time | Frequency |
|---------|------|-----------|
| 📰 News | :00 | Hourly |
| ⚽ Soccer | :20 | Hourly |
| 🎮 Gaming | :40 | Hourly |

Each post includes:
- AI-generated 3-5 word English title
- Bilingual summary (Arabic + English)
- Source image/video
- Category tags
- Announcement embed in general channel

---

## 🗞️ News Sources

**Syrian News:**
- 🍇 Enab Baladi - Syria-focused independent journalism

**Soccer:**
- ⚽ Kooora - Arabic football/soccer news

**Gaming:**
- 🎮 This Week in Videogames - Gaming industry news

---

## 🏗️ Structure

```
OthmanBot/
├── src/
│   ├── bot.py                    # Main bot (posting logic)
│   ├── core/
│   │   └── logger.py             # Custom EST logging
│   ├── services/
│   │   ├── news_scraper.py       # News RSS scraping + AI
│   │   ├── news_scheduler.py     # Hourly news scheduler
│   │   ├── soccer_scraper.py     # Soccer RSS scraping + AI
│   │   ├── soccer_scheduler.py   # Hourly soccer scheduler
│   │   ├── gaming_scraper.py     # Gaming RSS scraping + AI
│   │   └── gaming_scheduler.py   # Hourly gaming scheduler
│   ├── utils/
│   │   ├── ai_cache.py           # AI response caching
│   │   └── retry.py              # Exponential backoff
│   └── data/
│       └── team_tags.py          # Soccer team tag mappings
├── data/                         # Runtime data & caches
├── logs/                         # Log files
├── main.py                       # Entry point
└── requirements.txt              # Dependencies
```

**Tech Stack:** discord.py, OpenAI GPT-3.5, feedparser, BeautifulSoup, aiohttp

---

## 🔧 How It Works

1. **Startup** - Loads caches, initializes scrapers and schedulers
2. **Scheduling** - Three independent schedulers for :00, :20, :40
3. **Fetching** - Scrapes RSS feeds for latest articles
4. **AI Processing** - Generates titles and bilingual summaries
5. **Posting** - Creates forum thread with media and tags
6. **Announcing** - Sends embed to general channel
7. **Caching** - Marks article as posted, saves AI responses
8. **Repeat** - Waits for next scheduled time

---

## 📊 Features Detail

### AI-Generated Content
- **Titles**: Concise 3-5 word English titles
- **Summaries**: 200-350 character bilingual summaries
- **Caching**: Responses cached to reduce API costs

### Forum Posts
- Beautiful formatted content with key quote
- Arabic (🇸🇾) and English (🇬🇧) sections
- Source attribution and publish date
- Auto-applied category tags

### Announcements
- Teaser embed sent to general channel
- "Read Full Article" button linking to forum thread
- Color-coded: Blue (news), Green (soccer), Purple (gaming)

### Smart Deduplication
- Article ID extraction from URLs
- Persistent cache across restarts
- Prevents duplicate posts

---

## ⚠️ Disclaimer

Educational purposes only. No support provided. Use at own risk.

---

## 👨‍💻 Author

<div align="center">

**حَـــــنَّـــــا**

*Built with ❤️ for discord.gg/syria*

[![Discord](https://img.shields.io/badge/Discord-discord.gg/syria-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/syria)

</div>
