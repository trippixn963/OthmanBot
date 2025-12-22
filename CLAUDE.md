# OthmanBot - Claude Code Instructions

## Project Overview
Discord debate management bot with karma system, analytics, and leaderboards.

## VPS Deployment Rules (CRITICAL)

**NEVER do these:**
- `nohup python main.py &` - creates orphaned processes
- `rm -f /tmp/othman_bot.lock` - defeats single-instance lock
- `pkill` followed by manual start - use systemctl instead

**ALWAYS do these:**
- Use `systemctl restart othmanbot.service` to restart
- Use `systemctl stop othmanbot.service` to stop
- Use `systemctl status othmanbot.service` to check status

## VPS Connection
- Host: `root@188.245.32.205`
- SSH Key: `~/.ssh/hetzner_vps`
- Bot path: `/root/OthmanBot`

## Health Check
- Port: 8080
- Stats API: 8085
- Test: `curl http://188.245.32.205:8080/health`

## Other Bots on Same VPS
- AzabBot: port 8081, `systemctl azabbot.service`
- JawdatBot: port 8082, `systemctl jawdatbot.service`
- TahaBot: port 8083, `systemctl tahabot.service`
- TrippixnBot: port 8086, `systemctl trippixnbot.service`

## Lock Mechanism
- Lock file: `/tmp/othman_bot.lock`
- Contains PID of running process
- Prevents multiple instances
- NEVER delete this file manually

## Key Files
- Constants: `src/core/constants.py`
- Config: `src/core/config.py`
- Main entry: `main.py`

## Uploading Code Changes
1. Edit files locally
2. `scp -i ~/.ssh/hetzner_vps <file> root@188.245.32.205:/root/OthmanBot/<path>`
3. `ssh -i ~/.ssh/hetzner_vps root@188.245.32.205 "systemctl restart othmanbot.service"`

## After Deployment
- Verify: `systemctl status othmanbot.service`
- Health: `curl http://188.245.32.205:8080/health`
