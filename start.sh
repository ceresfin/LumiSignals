#!/usr/bin/env bash
# Launch LumiSignals bot with 1Password secrets + venv activated.
# Prerequisite: run `eval $(op signin)` in this shell first (lasts ~30 days).
set -e

cd "$(dirname "$0")"

# Sanity check: op session must be active (otherwise run.py will fail at op inject)
if ! op vault list >/dev/null 2>&1; then
  echo "ERROR: 1Password session is not active in this shell."
  echo "Run:  eval \$(op signin)"
  echo "Then re-run this script."
  exit 1
fi

# Export Supabase env vars from 1Password so the bot can write the
# trade diary (and other Supabase tables) at runtime. Read-once at
# launch — the values are stable per-tenant. If any read fails the
# bot still starts; diary writes will no-op until vars are restored.
export SUPABASE_URL="$(op read 'op://Lumi/LumiSignals - Supabase/url' 2>/dev/null || true)"
export SUPABASE_SERVICE_KEY="$(op read 'op://Lumi/LumiSignals - Supabase/service_role_key' 2>/dev/null || true)"
export SUPABASE_USER_ID="$(op read 'op://Lumi/LumiSignals - Supabase/user_id' 2>/dev/null || true)"
if [[ -z "$SUPABASE_SERVICE_KEY" || -z "$SUPABASE_USER_ID" ]]; then
  echo "WARN: SUPABASE_SERVICE_KEY or SUPABASE_USER_ID is empty — diary writes will no-op."
fi

# Activate venv and launch
source .venv/bin/activate
exec python run.py "$@"
