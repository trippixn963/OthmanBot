# OthmanBot

<div align="center">

![OthmanBot Banner](images/PFP.gif)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.7.0+-5865F2?style=flat-square&logo=discord&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991?style=flat-square&logo=openai&logoColor=white)
![License](https://img.shields.io/badge/License-Source%20Available-red?style=flat-square)

**Automated News & Debates Bot for Discord**

*Built for [discord.gg/syria](https://discord.gg/syria)*

[![Join Server](https://img.shields.io/badge/Join%20Server-discord.gg/syria-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)
[![Dashboard](https://img.shields.io/badge/Dashboard-trippixn.com/othman-1F5E2E?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBhdGggZD0iTTMgOWwzLTMgMyAzIi8+PHBhdGggZD0iTTYgNnYxMiIvPjxwYXRoIGQ9Ik0xNSAyMWwzLTMgMy0zIi8+PHBhdGggZD0iTTE4IDE4VjYiLz48L3N2Zz4=&logoColor=white)](https://trippixn.com/othman)

</div>

---

## Overview

OthmanBot automates content posting and community engagement for Discord servers. It posts hourly news updates with AI-generated bilingual summaries and manages a debate forum with karma voting.

**Live Stats Dashboard**: [trippixn.com/othman](https://trippixn.com/othman)

> **Note**: This bot was custom-built for **discord.gg/syria** and is provided as-is for educational purposes. **No support will be provided.**

---

## Features

| Feature | Description |
|---------|-------------|
| **Content Automation** | 100% automated, runs 24/7 autonomously |
| **Bilingual Summaries** | AI-generated Arabic and English summaries |
| **Multi-Content** | News and Soccer on hourly rotation |
| **Forum Threads** | Auto-creates discussion threads with category tags |
| **Karma Voting** | Reaction-based upvote/downvote with persistent tracking |
| **Auto-Tagging** | AI detects relevant topic tags for new debates |
| **Hot Tag Manager** | Dynamic "Hot" tag based on activity |
| **Open Discussion** | Pinned casual chat thread (no karma tracking) |
| **Leaderboard** | Monthly/all-time rankings updated hourly |
| **Case Logging** | All ban/unban actions tracked per-user |
| **Appeal System** | Users can appeal disallows and closures via DM |
| **Stats Dashboard** | Real-time activity stats at [trippixn.com/othman](https://trippixn.com/othman) |

---

## Screenshots

<div align="center">
<table>
<tr>
<td align="center" width="50%">
<img src="images/News-Example.png" alt="News Post" width="350" height="245"><br>
<b>News Post</b><br>
<sub>AI-generated bilingual news summary with discussion thread</sub>
</td>
</tr>
</table>
</div>

---

## News Sources

<div align="center">
<table>
<tr>
<td align="center"><img src="images/Enab-Baladi-Logo.jpg" width="100" height="100"><br><b>Enab Baladi</b><br><sub>Syrian News</sub></td>
<td align="center"><img src="images/koora-logo.jpeg" width="100" height="100"><br><b>Koora</b><br><sub>Soccer News</sub></td>
</tr>
</table>
</div>

---

## Commands

| Command | Description |
|---------|-------------|
| `/karma [user]` | View karma stats for yourself or another user |
| `/disallow <user>` | Ban user from debates (moderator only) |
| `/allow <user>` | Unban user from debates (moderator only) |
| `/close [reason]` | Close the current debate thread (moderator only) |
| `/open` | Reopen a closed debate thread (moderator only) |
| `/rename <new_name>` | Rename a debate thread (moderator only) |
| `/cases [search]` | Search moderation cases by user or case ID (moderator only) |
| `/toggle` | Enable/disable bot posting (developer only) |

---

## Tech Stack

- **Python 3.12+** - Async runtime
- **Discord.py 2.7+** - Discord API wrapper
- **OpenAI GPT-4o-mini** - AI summaries
- **SQLite** - State persistence with WAL mode
- **aiohttp** - Async HTTP client
- **feedparser** - RSS scraping

---

## Architecture

```
OthmanBot/
├── src/
│   ├── core/           # Bot initialization, config, logging
│   ├── services/       # Scrapers, schedulers, debates system
│   ├── handlers/       # Event handlers (debates, reactions, ready)
│   ├── commands/       # Slash commands (/karma, /disallow, /allow, etc.)
│   ├── posting/        # Content posting logic
│   ├── views/          # Discord UI components
│   └── utils/          # Helpers, rate limiting, caching
├── data/               # SQLite database, backups
├── scripts/            # Deployment and maintenance scripts
└── images/             # Bot assets and examples
```

---

## Database Schema

| Table | Description |
|-------|-------------|
| `votes` | Individual vote records with karma tracking |
| `debate_participation` | User activity per thread |
| `debate_bans` | Ban records with expiry |
| `ban_history` | Historical record of all bans |
| `closure_history` | Thread closure records with reopen tracking |
| `case_logs` | Moderation case tracking per user |
| `appeals` | User appeals for disallows and closures |
| `open_discussion` | Open Discussion thread state |
| `audit_log` | All database changes for accountability |

---

## License

**Source Available** - See [LICENSE](LICENSE) for details.

This code is provided for **educational and viewing purposes only**. You may not run, redistribute, or create derivative works from this code.

---

<div align="center">

<img src="images/PFP.gif" alt="OthmanBot" width="100">

**OthmanBot**

*Built with care for [discord.gg/syria](https://discord.gg/syria)*

</div>
