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

- **100% Automated** - Zero commands needed, runs 24/7 autonomously
- **Bilingual Summaries** - AI-generated Arabic and English summaries
- **Multi-Content** - News, Soccer, Gaming on hourly rotation
- **Forum Threads** - Auto-creates discussion threads with category tags
- **Karma System** - Upvote/downvote with persistent tracking
- **Auto-Tagging** - AI detects relevant topic tags for new debates
- **Hot Tag Manager** - Dynamic "Hot" tag based on activity
- **Leaderboard** - Monthly/all-time rankings updated hourly
- **Case Logging** - Moderation actions tracked in forum threads
- **Webhook Alerts** - Discord notifications for status and errors
- **Health Monitoring** - HTTP endpoint for external monitoring

---

## Debates System

The debates forum includes:
- **Karma Voting** - Reaction-based upvote/downvote system
- **Analytics** - Thread engagement metrics and participant tracking
- **Moderation** - /disallow and /allow commands for debate bans
- **Reconciliation** - Nightly sync to catch any missed votes
- **Case Logs** - All ban/unban actions tracked per-user in dedicated threads

---

## Tech Stack

- **Python 3.12+** with asyncio
- **Discord.py 2.3.2+** for Discord API
- **OpenAI GPT-4o-mini** for AI summaries
- **SQLite** for karma and state persistence
- **aiohttp** for async HTTP requests
- **feedparser** for RSS scraping

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/karma [user]` | View karma stats for yourself or another user |
| `/disallow <user>` | Ban user from debates (moderator only) |
| `/allow <user>` | Unban user from debates (moderator only) |

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<div align="center">

**حَـــــنَّـــــا**

*Built for discord.gg/syria*

</div>
