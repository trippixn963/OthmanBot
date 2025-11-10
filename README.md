# 📰 Othman News Bot

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3.2-blue.svg)](https://github.com/Rapptz/discord.py)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Fully automated** Discord bot that posts hourly Syrian news updates with images and creates discussion threads.

Built with ❤️ for **discord.gg/syria**

---

## ✨ Features

- 🤖 **100% Automated** - No commands, no manual intervention needed
- 📡 **Multi-Source News** - Fetches from Enab Baladi, Al Jazeera Arabic, Syrian Observer
- ⏰ **Hourly Posts** - Automatic posting on the hour, every hour
- 🖼️ **Rich Embeds** - Beautiful news embeds with article images
- 💬 **Auto Threads** - Creates discussion threads for each article
- 🚫 **Smart Filtering** - Duplicate detection, never posts same article twice
- 🔄 **Self-Healing** - Continues running even if one post fails

---

## 🚀 Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/OthmanBot.git
cd OthmanBot
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and add your bot token and channel ID
```

Required settings in `.env`:
```env
DISCORD_TOKEN=your_bot_token_here
NEWS_CHANNEL_ID=1234567890123456789
```

### 3. Run

```bash
python main.py
```

**That's it!** The bot starts posting news automatically.

---

## 🤖 How It Works

1. **Bot starts** → Connects to Discord
2. **Scheduler begins** → Calculates next hour (:00 minutes)
3. **Fetches news** → Scrapes latest Syrian news from 3 sources
4. **Filters content** → Removes duplicates and old articles
5. **Posts automatically** → Creates embeds with images and threads
6. **Repeats** → Waits until next hour, repeats steps 3-5

**Zero interaction required** - Bot runs 24/7 with no manual control needed.

---

## 📦 Project Structure

```
OthmanBot/
├── main.py                     # Entry point
├── requirements.txt            # Dependencies
├── .env                        # Configuration (create from .env.example)
├── .env.example               # Configuration template
├── .gitignore                 # Git ignore rules
├── data/                      # Runtime data (scheduler state)
├── logs/                      # Log files
└── src/
    ├── __init__.py
    ├── bot.py                 # Main bot class (fully automated)
    ├── core/
    │   ├── __init__.py
    │   └── logger.py          # Custom logging with EST timezone
    ├── services/
    │   ├── __init__.py
    │   ├── news_scraper.py    # RSS feed scraping
    │   └── news_scheduler.py  # Hourly scheduling
    ├── handlers/
    │   └── __init__.py
    └── utils/
        └── __init__.py
```

---

## 🗞️ News Sources

- **🍇 Enab Baladi** (Primary) - Syria-focused independent journalism
  - RSS: https://www.enabbaladi.net/feed/
  - Language: Arabic/English

- **📡 Al Jazeera Arabic** - Major network coverage
  - RSS: https://www.aljazeera.net/xml/rss/all.xml
  - Language: Arabic

- **📰 Syrian Observer** - English alternative
  - RSS: https://syrianobserver.com/feed/
  - Language: English

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ Yes | Your Discord bot token |
| `NEWS_CHANNEL_ID` | ✅ Yes | Channel ID where news will be posted |

### Getting Channel ID

1. Enable Developer Mode in Discord (User Settings → Advanced → Developer Mode)
2. Right-click the channel → Copy ID

### Bot Permissions

The bot needs these Discord permissions:
- Send Messages
- Embed Links
- Create Public Threads
- Read Message History

---

## 📊 Automation Details

### Posting Schedule

- Posts at **:00 minutes** of every hour (1:00 PM, 2:00 PM, 3:00 PM, etc.)
- Fetches **up to 3 articles** per post
- Looks back **24 hours** for recent news
- **2-second delay** between multiple articles (Discord rate limit compliance)

### Duplicate Prevention

- Caches last **1000 article URLs** in memory
- Articles are filtered by URL before posting
- Prevents same article from appearing twice

### Thread Management

- Auto-creates discussion thread for each article
- Thread name: First 100 characters of article title
- Auto-archives after **24 hours** of inactivity

### State Persistence

- Scheduler state saved to `data/scheduler_state.json`
- Bot resumes automatically after restart
- No configuration loss on reboot

---

## 🛠️ Development

### Code Style

This project uses [Black](https://github.com/psf/black) for code formatting:

```bash
python3 -m black .
```

### Type Hints

All code follows Python 3.12+ type hint standards with comprehensive annotations.

### Design Comments

Architecture decisions are explained with `# DESIGN:` comments throughout the codebase.

---

## 🐛 Troubleshooting

### Bot doesn't post news

- **Check `NEWS_CHANNEL_ID`** is correct in `.env`
- **Verify bot permissions**: Send Messages, Embed Links, Create Threads
- **Check logs**: `logs/othman_YYYY-MM-DD.log` for errors
- **RSS feeds down?** Wait 5-10 minutes and check again

### No threads created

- **Bot needs** "Create Public Threads" permission
- **Check logs** for specific error messages

### Bot crashes on startup

- **Missing `DISCORD_TOKEN`** in `.env`
- **Invalid token** - regenerate from Discord Developer Portal
- **Python version** - Requires Python 3.12+

---

## 📈 Monitoring

### Bot Status

Bot presence shows **next post time**:
- Example: "Watching Next post: 3:00 PM"
- Updates automatically after each post

### Logs

All activity logged to `logs/` directory:
- **Format**: `othman_YYYY-MM-DD.log`
- **Timezone**: Eastern Standard Time (EST/EDT)
- **Rotation**: New file daily

---

## 🤝 Contributing

This bot follows the same structure and quality standards as TahaBot and AzabBot. When contributing:

- Use Black formatting (88 char limit, double quotes)
- Add comprehensive type hints (Python 3.12+ syntax)
- Include `# DESIGN:` comments for architectural decisions
- Follow existing file header format with author attribution

---

## 📄 License

This project is open source and available for use.

---

## 👤 Author

**حَـــــنَّـــــا**
Discord: discord.gg/syria

---

## 🙏 Acknowledgments

- Built with [discord.py](https://github.com/Rapptz/discord.py)
- RSS parsing with [feedparser](https://github.com/kurtmckee/feedparser)
- HTML parsing with [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)
- News sources: Enab Baladi, Al Jazeera Arabic, Syrian Observer
