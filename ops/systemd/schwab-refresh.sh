#!/usr/bin/env bash
# Schwab access-token refresh (30-min lifetime). Run every 20 min
# via schwab-refresh.timer so the bot's quote path never trips a 401.
set -euo pipefail

ENV_FILE=/etc/lumisignals/web-app.env
TOKEN_FILE=/opt/lumisignals/schwab_tokens.json
APP_DIR=/opt/lumisignals/app
PY=/opt/lumisignals/venv/bin/python3

# Pull SCHWAB_CLIENT_ID / SCHWAB_CLIENT_SECRET into env
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$APP_DIR"
"$PY" - <<'PY'
import os, sys, json
from lumisignals.schwab_client import SchwabAuth, token_status

tf = "/opt/lumisignals/schwab_tokens.json"
auth = SchwabAuth(
    client_id=os.environ["SCHWAB_CLIENT_ID"],
    client_secret=os.environ["SCHWAB_CLIENT_SECRET"],
    token_file=tf,
)
ok = auth.refresh_access_token()
status = token_status(tf)
print(json.dumps({"refresh_ok": bool(ok), "status": status}, default=str))
sys.exit(0 if ok else 1)
PY
