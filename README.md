# OthmanBot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![Discord.py](https://img.shields.io/badge/Discord.py-2.3.2+-green.svg)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-orange.svg)
![License](https://img.shields.io/badge/License-MIT-red.svg)

**Automated multilingual news posting with AI-generated summaries + Debates karma system**

*Built for discord.gg/syria*

[![Join Discord Server](https://img.shields.io/badge/Join%20Server-discord.gg/syria-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)

</div>

---

## Overview

OthmanBot automates content posting and community engagement for Discord servers. It posts hourly news updates with AI-generated bilingual summaries and manages a debate forum with karma voting.

### Disclaimer

This bot was custom-built for **discord.gg/syria** and is provided as-is for educational purposes. **No support will be provided.**

---

## Features

### Content Automation
- **100% Automated** - Zero commands needed, runs 24/7 autonomously
- **Bilingual Summaries** - AI-generated Arabic and English summaries
- **Multi-Content** - News, Soccer, Gaming on hourly rotation
- **Forum Threads** - Auto-creates discussion threads with category tags

### Debates System
- **Karma Voting** - Reaction-based upvote/downvote with persistent tracking
- **Auto-Tagging** - AI detects relevant topic tags for new debates
- **Hot Tag Manager** - Dynamic "Hot" tag based on activity
- **Quality Metrics** - Response time and participation diversity scoring
- **Leaderboard** - Monthly/all-time rankings updated hourly
- **Access Control** - Users must react to participate in debates

### Moderation
- **Case Logging** - All ban/unban actions tracked per-user in dedicated forum threads
- **Debate Bans** - Ban users from specific threads or all debates
- **Auto-Unban** - Timed bans with automatic expiry
- **Audit Trail** - All moderation actions logged for accountability
- **Ban Evasion Detection** - Flags new accounts posting in debates

### Monitoring & Reliability
- **Daily/Weekly Stats** - Comprehensive activity reports via webhook
- **Health Tracking** - Uptime monitoring with disconnect/reconnect logging
- **Webhook Alerts** - Discord notifications for status and errors
- **HTTP Health Endpoint** - External monitoring support
- **Graceful Shutdown** - Proper cleanup of all services and connections

### Robustness
- **Rate Limit Handling** - Automatic retry with exponential backoff
- **Database Migrations** - Automatic schema updates on startup
- **WAL Mode** - SQLite Write-Ahead Logging for data integrity
- **Connection Recovery** - Auto-reconnect on database/Discord disconnects

---

## Tech Stack

- **Python 3.12+** with asyncio
- **Discord.py 2.3.2+** for Discord API
- **OpenAI GPT-4o-mini** for AI summaries
- **SQLite** with WAL mode for persistence
- **aiohttp** for async HTTP requests
- **feedparser** for RSS scraping

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/karma [user]` | View karma stats for yourself or another user |
| `/disallow <user>` | Ban user from debates (moderator only) |
| `/allow <user>` | Unban user from debates (moderator only) |
| `/rename <thread_id> <new_name>` | Rename a debate thread (moderator only) |
| `/toggle` | Enable/disable bot posting (developer only) |

---

## Architecture

```
src/
├── bot.py              # Main bot class
├── core/               # Config, logging, presence
├── commands/           # Slash commands
├── handlers/           # Event handlers (debates, ready, shutdown)
├── services/           # Business logic
│   ├── debates/        # Karma, analytics, reconciliation
│   ├── scrapers/       # News, soccer, gaming
│   └── daily_stats.py  # Activity tracking
├── posting/            # Content posting logic
└── utils/              # Helpers, retry logic, caching
```

---

## Database Schema

- **votes** - Individual vote records with karma tracking
- **debate_participation** - User activity per thread
- **debate_bans** - Ban records with expiry
- **case_logs** - Moderation case tracking
- **audit_log** - All database changes for accountability
- **user_streaks** - Daily participation streaks

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<div align="center">

**حَـــــنَّـــــا**

*Built for discord.gg/syria*

</div>
