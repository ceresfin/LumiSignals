#!/usr/bin/env bash
# Stops the LumiSignals dev stack started by dev.sh.

set -euo pipefail

RUN_DIR="$HOME/.lumisignals-dev"
G='\033[0;32m'; Y='\033[0;33m'; X='\033[0m'

stop_group() {
  local pidfile="$1" name="$2"
  [[ -f "$pidfile" ]] || return 0
  local pid
  pid=$(cat "$pidfile")
  if kill -0 "$pid" 2>/dev/null; then
    echo -e "${Y}→ Stopping $name (pid $pid)${X}"
    # setsid put the process in its own group; killing the group catches children too
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$pidfile"
}

stop_group "$RUN_DIR/expo.pid"        "expo"
stop_group "$RUN_DIR/cloudflared.pid" "cloudflared"
rm -f "$RUN_DIR/tunnel.url"

echo -e "${G}✓ LumiSignals dev stack stopped.${X}"
