#!/bin/bash
# =============================================================================
# Multi-Bot Log Sync Daemon (OthmanBot + TahaBot)
# =============================================================================
# Continuously syncs logs from the VPS to local machine for both bots.
# Each bot's logs are synced to their respective project folders.
#
# Usage:
#   ./log-sync-daemon.sh start   - Start the daemon
#   ./log-sync-daemon.sh stop    - Stop the daemon
#   ./log-sync-daemon.sh status  - Check if daemon is running
#   ./log-sync-daemon.sh logs    - Tail the daemon's own log
#
# Author: حَـــــنَّـــــا
# =============================================================================

# =============================================================================
# Configuration
# =============================================================================

SSH_KEY="$HOME/.ssh/hetzner_vps"
REMOTE_HOST="root@188.245.32.205"
SYNC_INTERVAL=30  # seconds between syncs
PID_FILE="$HOME/.botlogs-sync.pid"
DAEMON_LOG="$HOME/Developer/OthmanBot/logs/.sync-daemon.log"

# -----------------------------------------------------------------------------
# OthmanBot Configuration
# -----------------------------------------------------------------------------
OTHMAN_REMOTE_LOG="/root/OthmanBot/logs"
OTHMAN_REMOTE_DATA="/root/OthmanBot/data"
OTHMAN_LOCAL_LOG="$HOME/Developer/OthmanBot/logs"
OTHMAN_LOCAL_DATA="$HOME/Developer/OthmanBot/data"

# -----------------------------------------------------------------------------
# TahaBot Configuration
# -----------------------------------------------------------------------------
TAHA_REMOTE_LOG="/root/TahaBot/logs"
TAHA_REMOTE_DATA="/root/TahaBot/data"
TAHA_LOCAL_LOG="$HOME/Developer/TahaBot/logs"
TAHA_LOCAL_DATA="$HOME/Developer/TahaBot/data"

# =============================================================================
# Colors
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# =============================================================================
# Ensure directories exist
# =============================================================================

mkdir -p "$OTHMAN_LOCAL_LOG"
mkdir -p "$OTHMAN_LOCAL_DATA"
mkdir -p "$TAHA_LOCAL_LOG"
mkdir -p "$TAHA_LOCAL_DATA"

# =============================================================================
# Logging function
# =============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$DAEMON_LOG"
}

# =============================================================================
# Sync functions
# =============================================================================

# Sync logs for a specific bot (only recent logs - today and yesterday)
sync_bot_logs() {
    local remote_dir="$1"
    local local_dir="$2"

    # Get today and yesterday's date folders
    local today=$(date +%Y-%m-%d)
    local yesterday=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d 2>/dev/null)

    # Sync only today's logs
    rsync -avz \
        -e "ssh -i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no" \
        "$REMOTE_HOST:$remote_dir/$today/" \
        "$local_dir/$today/" \
        --exclude='.sync-daemon.log' \
        2>/dev/null

    # Sync yesterday's logs (if exists)
    if [ -n "$yesterday" ]; then
        rsync -avz \
            -e "ssh -i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no" \
            "$REMOTE_HOST:$remote_dir/$yesterday/" \
            "$local_dir/$yesterday/" \
            --exclude='.sync-daemon.log' \
            2>/dev/null
    fi

    return $?
}

# Sync data for a specific bot
sync_bot_data() {
    local remote_dir="$1"
    local local_dir="$2"

    # Check if remote directory exists first
    ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=no \
        "$REMOTE_HOST" "test -d $remote_dir" 2>/dev/null

    if [ $? -ne 0 ]; then
        # Remote directory doesn't exist, skip
        return 2
    fi

    rsync -avz \
        -e "ssh -i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no" \
        "$REMOTE_HOST:$remote_dir/" \
        "$local_dir/" \
        --exclude='temp_media' \
        --exclude='__pycache__' \
        2>/dev/null

    return $?
}

# Sync all bots
sync_all_bots() {
    local total_success=0
    local total_partial=0
    local total_failed=0

    # Sync OthmanBot
    local othman_logs=0
    local othman_data=0

    if sync_bot_logs "$OTHMAN_REMOTE_LOG" "$OTHMAN_LOCAL_LOG"; then
        othman_logs=1
    fi

    if sync_bot_data "$OTHMAN_REMOTE_DATA" "$OTHMAN_LOCAL_DATA"; then
        othman_data=1
    fi

    if [ $othman_logs -eq 1 ] && [ $othman_data -eq 1 ]; then
        log "OthmanBot: sync OK (logs + data)"
        total_success=$((total_success + 1))
    elif [ $othman_logs -eq 1 ] || [ $othman_data -eq 1 ]; then
        log "OthmanBot: partial (logs=$othman_logs, data=$othman_data)"
        total_partial=$((total_partial + 1))
    else
        log "OthmanBot: sync FAILED"
        total_failed=$((total_failed + 1))
    fi

    # Sync TahaBot
    local taha_logs=0
    local taha_data=0

    if sync_bot_logs "$TAHA_REMOTE_LOG" "$TAHA_LOCAL_LOG"; then
        taha_logs=1
    fi

    local data_result
    sync_bot_data "$TAHA_REMOTE_DATA" "$TAHA_LOCAL_DATA"
    data_result=$?

    if [ $data_result -eq 0 ]; then
        taha_data=1
    elif [ $data_result -eq 2 ]; then
        # Remote data dir doesn't exist - not a failure
        taha_data=2
    fi

    if [ $taha_logs -eq 1 ] && [ $taha_data -ge 1 ]; then
        if [ $taha_data -eq 2 ]; then
            log "TahaBot: sync OK (logs only, no remote data)"
        else
            log "TahaBot: sync OK (logs + data)"
        fi
        total_success=$((total_success + 1))
    elif [ $taha_logs -eq 1 ] || [ $taha_data -eq 1 ]; then
        log "TahaBot: partial (logs=$taha_logs, data=$taha_data)"
        total_partial=$((total_partial + 1))
    else
        log "TahaBot: sync FAILED"
        total_failed=$((total_failed + 1))
    fi

    # Return overall status
    if [ $total_failed -eq 0 ]; then
        return 0  # All successful
    elif [ $total_success -gt 0 ] || [ $total_partial -gt 0 ]; then
        return 1  # Partial success
    else
        return 2  # All failed
    fi
}

# =============================================================================
# Daemon loop
# =============================================================================

run_daemon() {
    log "=========================================="
    log "Multi-Bot Sync Daemon started (PID: $$)"
    log "Bots: OthmanBot, TahaBot"
    log "=========================================="
    echo "$$" > "$PID_FILE"

    # Trap signals for clean shutdown
    trap 'log "Daemon stopped"; rm -f "$PID_FILE"; exit 0' SIGTERM SIGINT

    local consecutive_failures=0
    local max_failures=10

    while true; do
        sync_all_bots
        local result=$?

        if [ $result -eq 0 ]; then
            consecutive_failures=0
        elif [ $result -eq 1 ]; then
            # Partial success - don't count as failure
            consecutive_failures=0
        else
            consecutive_failures=$((consecutive_failures + 1))
            log "All syncs failed (attempt $consecutive_failures/$max_failures)"

            if [ $consecutive_failures -ge $max_failures ]; then
                log "Too many consecutive failures, waiting 5 minutes before retry"
                sleep 300
                consecutive_failures=0
            fi
        fi

        sleep "$SYNC_INTERVAL"
    done
}

# =============================================================================
# Start daemon
# =============================================================================

start_daemon() {
    if [ -f "$PID_FILE" ]; then
        local old_pid=$(cat "$PID_FILE")
        if ps -p "$old_pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}Daemon already running (PID: $old_pid)${NC}"
            return 1
        else
            rm -f "$PID_FILE"
        fi
    fi

    echo -e "${GREEN}Starting Multi-Bot Sync Daemon...${NC}"
    echo -e "${CYAN}Bots: OthmanBot, TahaBot${NC}"
    echo ""

    # Initial sync for OthmanBot
    echo -e "${BLUE}[OthmanBot]${NC} Syncing logs..."
    if sync_bot_logs "$OTHMAN_REMOTE_LOG" "$OTHMAN_LOCAL_LOG"; then
        echo -e "  ${GREEN}✓ Logs synced${NC}"
    else
        echo -e "  ${YELLOW}⚠ Log sync had issues${NC}"
    fi

    echo -e "${BLUE}[OthmanBot]${NC} Syncing data..."
    if sync_bot_data "$OTHMAN_REMOTE_DATA" "$OTHMAN_LOCAL_DATA"; then
        echo -e "  ${GREEN}✓ Data synced${NC}"
    else
        echo -e "  ${YELLOW}⚠ Data sync had issues${NC}"
    fi

    # Initial sync for TahaBot
    echo -e "${BLUE}[TahaBot]${NC} Syncing logs..."
    if sync_bot_logs "$TAHA_REMOTE_LOG" "$TAHA_LOCAL_LOG"; then
        echo -e "  ${GREEN}✓ Logs synced${NC}"
    else
        echo -e "  ${YELLOW}⚠ Log sync had issues${NC}"
    fi

    echo -e "${BLUE}[TahaBot]${NC} Syncing data..."
    sync_bot_data "$TAHA_REMOTE_DATA" "$TAHA_LOCAL_DATA"
    local taha_data_result=$?
    if [ $taha_data_result -eq 0 ]; then
        echo -e "  ${GREEN}✓ Data synced${NC}"
    elif [ $taha_data_result -eq 2 ]; then
        echo -e "  ${CYAN}ℹ No remote data directory${NC}"
    else
        echo -e "  ${YELLOW}⚠ Data sync had issues${NC}"
    fi

    echo ""

    # Start daemon in background
    nohup "$0" daemon >> "$DAEMON_LOG" 2>&1 &
    local pid=$!

    sleep 1
    if ps -p "$pid" > /dev/null 2>&1; then
        echo -e "${GREEN}Daemon started (PID: $pid)${NC}"
        echo "Syncing every ${SYNC_INTERVAL}s"
        echo ""
        echo "Sync destinations:"
        echo -e "  ${BLUE}OthmanBot${NC} → $OTHMAN_LOCAL_LOG"
        echo -e "  ${BLUE}TahaBot${NC}   → $TAHA_LOCAL_LOG"
        echo ""
        echo "Daemon log: $DAEMON_LOG"
    else
        echo -e "${RED}Failed to start daemon${NC}"
        return 1
    fi
}

# =============================================================================
# Stop daemon
# =============================================================================

stop_daemon() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}Stopping daemon (PID: $pid)...${NC}"
            kill "$pid"
            sleep 2
            if ps -p "$pid" > /dev/null 2>&1; then
                kill -9 "$pid"
            fi
            rm -f "$PID_FILE"
            echo -e "${GREEN}Daemon stopped${NC}"
        else
            echo -e "${YELLOW}Daemon not running (stale PID file)${NC}"
            rm -f "$PID_FILE"
        fi
    else
        echo -e "${YELLOW}Daemon not running${NC}"
    fi
}

# =============================================================================
# Check status
# =============================================================================

check_status() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${GREEN}Daemon is running (PID: $pid)${NC}"
            echo "Sync interval: ${SYNC_INTERVAL}s"
            echo ""

            # OthmanBot status
            echo -e "${BLUE}═══ OthmanBot ═══${NC}"
            echo "Log dir: $OTHMAN_LOCAL_LOG"
            if [ -d "$OTHMAN_LOCAL_LOG" ]; then
                ls -d "$OTHMAN_LOCAL_LOG"/????-??-?? 2>/dev/null | tail -3 | while read folder; do
                    folder_name=$(basename "$folder")
                    file_count=$(ls "$folder"/*.log 2>/dev/null | wc -l | tr -d ' ')
                    total_size=$(du -sh "$folder" 2>/dev/null | cut -f1)
                    echo "  $folder_name/ ($file_count logs, $total_size)"
                done
            fi
            echo "Data dir: $OTHMAN_LOCAL_DATA"
            if [ -d "$OTHMAN_LOCAL_DATA" ]; then
                local db_size=$(du -sh "$OTHMAN_LOCAL_DATA/debates.db" 2>/dev/null | cut -f1)
                echo "  debates.db: ${db_size:-not found}"
            fi
            echo ""

            # TahaBot status
            echo -e "${BLUE}═══ TahaBot ═══${NC}"
            echo "Log dir: $TAHA_LOCAL_LOG"
            if [ -d "$TAHA_LOCAL_LOG" ]; then
                local has_folders=$(ls -d "$TAHA_LOCAL_LOG"/????-??-?? 2>/dev/null | head -1)
                if [ -n "$has_folders" ]; then
                    ls -d "$TAHA_LOCAL_LOG"/????-??-?? 2>/dev/null | tail -3 | while read folder; do
                        folder_name=$(basename "$folder")
                        file_count=$(ls "$folder"/*.log 2>/dev/null | wc -l | tr -d ' ')
                        total_size=$(du -sh "$folder" 2>/dev/null | cut -f1)
                        echo "  $folder_name/ ($file_count logs, $total_size)"
                    done
                else
                    echo "  (no log folders yet)"
                fi
            else
                echo "  (not synced yet)"
            fi
            echo "Data dir: $TAHA_LOCAL_DATA"
            if [ -d "$TAHA_LOCAL_DATA" ]; then
                local state_db=$(du -sh "$TAHA_LOCAL_DATA/bot_state.db" 2>/dev/null | cut -f1)
                echo "  bot_state.db: ${state_db:-not found}"
            else
                echo "  (not synced yet)"
            fi

            return 0
        else
            echo -e "${RED}Daemon not running (stale PID file)${NC}"
            rm -f "$PID_FILE"
            return 1
        fi
    else
        echo -e "${RED}Daemon not running${NC}"
        return 1
    fi
}

# =============================================================================
# Tail daemon logs
# =============================================================================

tail_logs() {
    if [ -f "$DAEMON_LOG" ]; then
        tail -f "$DAEMON_LOG"
    else
        echo -e "${YELLOW}No daemon log file yet${NC}"
    fi
}

# =============================================================================
# Main
# =============================================================================

case "$1" in
    start)
        start_daemon
        ;;
    stop)
        stop_daemon
        ;;
    restart)
        stop_daemon
        sleep 1
        start_daemon
        ;;
    status)
        check_status
        ;;
    logs)
        tail_logs
        ;;
    daemon)
        # Internal: called when starting the background daemon
        run_daemon
        ;;
    *)
        echo -e "${CYAN}Multi-Bot Log Sync Daemon${NC}"
        echo -e "${CYAN}═════════════════════════${NC}"
        echo "Syncs logs for: OthmanBot, TahaBot"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the log sync daemon"
        echo "  stop    - Stop the daemon"
        echo "  restart - Restart the daemon"
        echo "  status  - Check daemon status and show synced files"
        echo "  logs    - Tail the daemon's own log file"
        exit 1
        ;;
esac
