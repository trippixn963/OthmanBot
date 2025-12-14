#!/usr/bin/env python3
"""
One-time script to create the rules thread in the case log forum.
Run with: python3 scripts/create_rules_thread.py
"""

import asyncio
import sys
import os

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables BEFORE importing config
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

import discord
from src.core.config import CASE_LOG_FORUM_ID

# Get token directly from env (like main.py does)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    print("DISCORD_TOKEN not set in environment")
    sys.exit(1)


# Compact single message (under 2000 chars)
RULES_CONTENT = """# 📋 Case Log Guidelines

This forum tracks all debate bans/unbans. Each user gets a case thread for their moderation history.

══════════════════════════════════════

# Bannable Offenses

**Severe (Permanent)** — Slurs/hate speech, doxxing, threats, ban evasion
**Moderate (1 Week - 1 Month)** — Personal attacks, derailing, trolling, ignoring warnings
**Minor (1 Day - 1 Week)** — Off-topic spam, minor hostility, low-effort responses

══════════════════════════════════════

# Moderator Guidelines

• Warn first for minor offenses
• Check prior cases with `/cases`
• Always provide a reason
• Use "all debates" for severe violations
• Escalate duration for repeat offenders

```
1st minor    →  1 Day
1st moderate →  1 Week
Repeat       →  2 Weeks - 1 Month
Severe       →  Permanent
```

══════════════════════════════════════

# Case Thread Usage

• Discuss specific users in their case thread
• Document warnings, appeals, and decisions
• Threads auto-archive after 7 days"""


# IMPORTANT: Rules thread already created - DO NOT DELETE
# Thread ID: 1449731972384555068
RULES_THREAD_ID = 1449731972384555068


if __name__ == "__main__":
    print("Rules thread already exists: 1449731972384555068")
    print("This script is kept for reference only - do not run again.")
