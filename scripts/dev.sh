#!/usr/bin/env bash
# LumiSignals dev orchestrator — starts cloudflared + Expo detached, then exits.
# Processes survive this shell ending (uses setsid+nohup), so it works fine when
# triggered from a Claude Code session that goes away.
#
# Re-run safely: if the stack is already up, just re-prints the URL.
#
# Usage:  ./scripts/dev.sh
# Stop:   ./scripts/stop.sh
# Logs:   tail -F ~/.lumisignals-dev/expo.log ~/.lumisignals-dev/cloudflared.log

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$HOME/.lumisignals-dev"
mkdir -p "$RUN_DIR"

CF_PID_FILE="$RUN_DIR/cloudflared.pid"
EXPO_PID_FILE="$RUN_DIR/expo.pid"
URL_FILE="$RUN_DIR/tunnel.url"
CF_LOG="$RUN_DIR/cloudflared.log"
EXPO_LOG="$RUN_DIR/expo.log"
METRO_PORT="${METRO_PORT:-8082}"

G='\033[0;32m'; Y='\033[0;33m'; B='\033[0;34m'; R='\033[0;31m'; X='\033[0m'

is_running() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }

print_url() {
  [[ -f "$URL_FILE" ]] || return 0
  local url host
  url=$(cat "$URL_FILE")
  host="${url#https://}"
  echo
  echo -e "${G}LumiSignals dev stack is running.${X}"
  echo -e "  Tunnel:   $url"
  echo -e "  Expo Go → 'Enter URL manually':"
  echo -e "    ${G}exp://$host${X}"
  echo
  echo -e "  Logs:     tail -F $EXPO_LOG $CF_LOG"
  echo -e "  Stop:     $ROOT/scripts/stop.sh"
  echo
}

if is_running "$CF_PID_FILE" && is_running "$EXPO_PID_FILE"; then
  echo -e "${Y}Already running.${X}"
  print_url
  exit 0
fi

# Half-running state: kill survivors, start clean
is_running "$CF_PID_FILE"   && kill "$(cat "$CF_PID_FILE")"   2>/dev/null || true
is_running "$EXPO_PID_FILE" && kill "$(cat "$EXPO_PID_FILE")" 2>/dev/null || true
rm -f "$CF_PID_FILE" "$EXPO_PID_FILE" "$URL_FILE"

echo -e "${B}→ Starting cloudflared (target: localhost:$METRO_PORT)${X}"
: > "$CF_LOG"
setsid nohup cloudflared tunnel --url "http://localhost:$METRO_PORT" --no-autoupdate \
  >>"$CF_LOG" 2>&1 </dev/null &
echo $! > "$CF_PID_FILE"

TUNNEL_URL=""
for _ in $(seq 1 60); do
  TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1 || true)
  [[ -n "$TUNNEL_URL" ]] && break
  sleep 1
done
if [[ -z "$TUNNEL_URL" ]]; then
  echo -e "${R}✗ Tunnel failed${X}"; tail -20 "$CF_LOG"
  kill "$(cat "$CF_PID_FILE")" 2>/dev/null || true
  rm -f "$CF_PID_FILE"
  exit 1
fi
echo "$TUNNEL_URL" > "$URL_FILE"
echo -e "${G}✓ Tunnel: $TUNNEL_URL${X}"

echo -e "${B}→ Starting Expo on :$METRO_PORT${X}"
: > "$EXPO_LOG"
cd "$ROOT/mobile"
setsid nohup env \
  EXPO_PACKAGER_PROXY_URL="$TUNNEL_URL" \
  EXPO_MANIFEST_PROXY_URL="$TUNNEL_URL" \
  npx expo start --port "$METRO_PORT" \
  >>"$EXPO_LOG" 2>&1 </dev/null &
echo $! > "$EXPO_PID_FILE"

# Wait for Metro to be ready or fail
for _ in $(seq 1 30); do
  grep -qE "Logs for your project|Waiting on http" "$EXPO_LOG" 2>/dev/null && break
  grep -qE "CommandError|Error:" "$EXPO_LOG" 2>/dev/null && {
    echo -e "${R}✗ Expo failed:${X}"; tail -20 "$EXPO_LOG"
    exit 1
  }
  sleep 1
done
echo -e "${G}✓ Expo started${X}"

print_url
