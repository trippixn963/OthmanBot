#!/bin/bash
# OthmanBot Crash Alert Script
# Called by systemd when OthmanBot service fails

# Load webhook URL from .env file
WEBHOOK_URL=$(grep "^CRASH_WEBHOOK_URL=" /root/OthmanBot/.env | cut -d'=' -f2-)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Get exit code from systemd
EXIT_CODE=$(systemctl show othmanbot.service -p ExecMainStatus --value 2>/dev/null || echo "?")

# Get when service started (to show uptime before crash)
ACTIVE_SINCE=$(systemctl show othmanbot.service -p ActiveEnterTimestamp --value 2>/dev/null | cut -d" " -f2-3 || echo "Unknown")

# Get recent error (sanitized for JSON safety)
LOG_DATE=$(date +%Y-%m-%d)
ERROR_LOG="/root/OthmanBot/logs/${LOG_DATE}/Othman-Errors-${LOG_DATE}.log"
if [ -f "$ERROR_LOG" ]; then
    LAST_ERROR=$(tail -1 "$ERROR_LOG" 2>/dev/null | head -c 100 | tr -d '"\n\r\\' || echo "None")
else
    LAST_ERROR="No log file"
fi

# Send webhook
curl -s -H "Content-Type: application/json" -X POST "$WEBHOOK_URL" -d "{
  \"embeds\": [{
    \"title\": \"OthmanBot - CRASHED\",
    \"description\": \"**Status:** Process Died\\n**Exit Code:** $EXIT_CODE\\n**Started:** $ACTIVE_SINCE\\n**Last Error:** $LAST_ERROR\\n\\n**Action:** Auto-restarting in 10s\",
    \"color\": 16711680,
    \"timestamp\": \"$TIMESTAMP\"
  }]
}"
