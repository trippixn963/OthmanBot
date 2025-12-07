#!/bin/bash
# =============================================================================
# OthmanBot Log Sync Daemon
# =============================================================================
# Continuously syncs logs from the VPS to local machine.
#
# Usage:
#   ./log-sync-daemon.sh start   - Start the daemon
#   ./log-sync-daemon.sh stop    - Stop the daemon
#   ./log-sync-daemon.sh status  - Check if daemon is running
#   ./log-sync-daemon.sh logs    - Tail the daemon's own log
#
# Author: حَـــــنَّـــــا
# =============================================================================

# Configuration
SSH_KEY="$HOME/.ssh/hetzner_vps"
REMOTE_HOST="root@188.245.32.205"
REMOTE_LOG_DIR="/root/OthmanBot/logs"
REMOTE_DATA_DIR="/root/OthmanBot/data"
LOCAL_LOG_DIR="$HOME/Developer/OthmanBot/logs"
LOCAL_DATA_DIR="$HOME/Developer/OthmanBot/data"
SYNC_INTERVAL=30  # seconds between syncs
PID_FILE="$HOME/.othmanbot-log-sync.pid"
DAEMON_LOG="$LOCAL_LOG_DIR/.sync-daemon.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Ensure local directories exist
mkdir -p "$LOCAL_LOG_DIR"
mkdir -p "$LOCAL_DATA_DIR"

# -----------------------------------------------------------------------------
# Logging function
# -----------------------------------------------------------------------------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$DAEMON_LOG"
}

# -----------------------------------------------------------------------------
# Sync function - pulls logs from server
# -----------------------------------------------------------------------------
sync_logs() {
    # Sync all log files using rsync (efficient delta sync)
    rsync -avz --delete \
        -e "ssh -i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no" \
        "$REMOTE_HOST:$REMOTE_LOG_DIR/" \
        "$LOCAL_LOG_DIR/" \
        --exclude='.sync-daemon.log' \
        2>/dev/null

    return $?
}

# -----------------------------------------------------------------------------
# Sync function - pulls data folder from server
# -----------------------------------------------------------------------------
sync_data() {
    # Sync data folder (database, JSON state files, backups)
    # Exclude temp_media to save bandwidth
    rsync -avz \
        -e "ssh -i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no" \
        "$REMOTE_HOST:$REMOTE_DATA_DIR/" \
        "$LOCAL_DATA_DIR/" \
        --exclude='temp_media' \
        2>/dev/null

    return $?
}

# -----------------------------------------------------------------------------
# Daemon loop
# -----------------------------------------------------------------------------
run_daemon() {
    log "Daemon started (PID: $$)"
    echo "$$" > "$PID_FILE"

    # Trap signals for clean shutdown
    trap 'log "Daemon stopped"; rm -f "$PID_FILE"; exit 0' SIGTERM SIGINT

    local consecutive_failures=0
    local max_failures=10

    while true; do
        local logs_ok=0
        local data_ok=0

        # Sync logs
        if sync_logs; then
            logs_ok=1
        fi

        # Sync data folder
        if sync_data; then
            data_ok=1
        fi

        if [ $logs_ok -eq 1 ] && [ $data_ok -eq 1 ]; then
            log "Sync successful (logs + data)"
            consecutive_failures=0
        elif [ $logs_ok -eq 1 ] || [ $data_ok -eq 1 ]; then
            log "Partial sync (logs=$logs_ok, data=$data_ok)"
            consecutive_failures=0
        else
            ((consecutive_failures++))
            log "Sync failed (attempt $consecutive_failures/$max_failures)"

            if [ $consecutive_failures -ge $max_failures ]; then
                log "Too many consecutive failures, waiting 5 minutes before retry"
                sleep 300
                consecutive_failures=0
            fi
        fi

        sleep "$SYNC_INTERVAL"
    done
}

# -----------------------------------------------------------------------------
# Start daemon
# -----------------------------------------------------------------------------
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

    echo -e "${GREEN}Starting OthmanBot sync daemon...${NC}"

    # Initial sync
    echo "Performing initial log sync..."
    if sync_logs; then
        echo -e "${GREEN}Log sync complete${NC}"
    else
        echo -e "${YELLOW}Log sync had issues, but continuing...${NC}"
    fi

    echo "Performing initial data sync..."
    if sync_data; then
        echo -e "${GREEN}Data sync complete${NC}"
    else
        echo -e "${YELLOW}Data sync had issues, but continuing...${NC}"
    fi

    # Start daemon in background
    nohup "$0" daemon >> "$DAEMON_LOG" 2>&1 &
    local pid=$!

    sleep 1
    if ps -p "$pid" > /dev/null 2>&1; then
        echo -e "${GREEN}Daemon started (PID: $pid)${NC}"
        echo "Syncing every ${SYNC_INTERVAL}s:"
        echo "  Logs → $LOCAL_LOG_DIR"
        echo "  Data → $LOCAL_DATA_DIR"
        echo "Daemon log: $DAEMON_LOG"
    else
        echo -e "${RED}Failed to start daemon${NC}"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Stop daemon
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Check status
# -----------------------------------------------------------------------------
check_status() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${GREEN}Daemon is running (PID: $pid)${NC}"
            echo "Sync interval: ${SYNC_INTERVAL}s"
            echo ""
            echo "Log dir: $LOCAL_LOG_DIR"
            echo "Recent synced log folders:"
            ls -d "$LOCAL_LOG_DIR"/????-??-?? 2>/dev/null | tail -5 | while read folder; do
                folder_name=$(basename "$folder")
                file_count=$(ls "$folder"/*.log 2>/dev/null | wc -l | tr -d ' ')
                total_size=$(du -sh "$folder" 2>/dev/null | cut -f1)
                echo "  $folder_name/ ($file_count logs, $total_size)"
            done
            echo ""
            echo "Data dir: $LOCAL_DATA_DIR"
            if [ -d "$LOCAL_DATA_DIR" ]; then
                local db_size=$(du -sh "$LOCAL_DATA_DIR/debates.db" 2>/dev/null | cut -f1)
                local json_count=$(ls "$LOCAL_DATA_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
                local backups_count=$(ls "$LOCAL_DATA_DIR/backups"/*.db 2>/dev/null 2>&1 | wc -l | tr -d ' ')
                echo "  debates.db: ${db_size:-not found}"
                echo "  JSON files: $json_count"
                echo "  Backups: $backups_count"
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

# -----------------------------------------------------------------------------
# Tail daemon logs
# -----------------------------------------------------------------------------
tail_logs() {
    if [ -f "$DAEMON_LOG" ]; then
        tail -f "$DAEMON_LOG"
    else
        echo -e "${YELLOW}No daemon log file yet${NC}"
    fi
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
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
        echo "OthmanBot Log Sync Daemon"
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
