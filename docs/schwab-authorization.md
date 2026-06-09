# Schwab Authorization Runbook

How to (re)authorize the Schwab Market Data API. Schwab is the **fallback**
options-chain source (IB is primary — see `ib-options-orders.md`); keep it
healthy so the dashboard always has a working chain feed.

## Why you have to do this ~weekly

Schwab OAuth2 has two tokens:
- **access token** — 30-minute life. Auto-refreshed every 20 min by the
  `schwab-refresh` systemd timer.
- **refresh token** — **~7-day life, not extendable.** When it expires you
  MUST re-run the browser authorization below. There is no way around the
  weekly re-auth — it's a Schwab policy.

If the dashboard's option specs go empty with `"No valid Schwab access token —
authorize first"`, the refresh token lapsed → re-authorize.

## Prerequisites (already true on prod)

- Runs on **`lumi-prod`** (`root@174.138.46.187`), where the bot lives.
- Creds come from env: `SCHWAB_CLIENT_ID` / `SCHWAB_CLIENT_SECRET` in
  `/etc/lumisignals/web-app.env`.
- Tokens are read by the bot from **`/opt/lumisignals/schwab_tokens.json`**
  (root-owned) — the auth helper writes there.
- Use the **venv python**: `/opt/lumisignals/venv/bin/python` (system python3
  lacks numpy and will crash on import).

## Method A — interactive on the server (preferred when you can paste)

In a terminal **on lumi-prod**:

```bash
set -a; source /etc/lumisignals/web-app.env; set +a
cd /opt/lumisignals/app
/opt/lumisignals/venv/bin/python schwab_auth.py
```

`schwab_auth.py` prints an authorization URL and waits at a paste prompt. Then:

1. Open the printed URL in a browser, log in, click **Allow**.
2. You're redirected to `https://127.0.0.1/?code=...` — the browser shows
   **"can't connect." That's expected.**
3. Copy the **full** address-bar URL.
4. Paste it into the waiting terminal, Enter. **Do it within ~30 seconds** —
   the auth code expires fast.

Tip: have the terminal already waiting at the prompt **before** you click
Allow, so the paste→exchange is instant. On success it prints
`✓ Authorization successful!` and runs a verified test quote.

## Method B — chat/URL relay (when you can't paste into SSH)

Useful from a phone / restricted terminal. Two commands run from anywhere
that can SSH to `lumi-prod`:

**1. Generate the URL:**
```bash
ssh lumi-prod 'set -a; source /etc/lumisignals/web-app.env; set +a; cd /opt/lumisignals/app && \
  /opt/lumisignals/venv/bin/python -c "import os; from lumisignals.schwab_client import SchwabAuth; \
  print(SchwabAuth(os.environ[\"SCHWAB_CLIENT_ID\"], os.environ[\"SCHWAB_CLIENT_SECRET\"], \
  token_file=\"/opt/lumisignals/schwab_tokens.json\").get_authorization_url())"'
```

Open the URL → Allow → copy the `https://127.0.0.1/?code=...` redirect URL.

**2. Exchange the code (run FAST — within ~30s of getting the redirect).**
Put the full redirect URL in `REDIR=` and run:
```bash
ssh lumi-prod "set -a; source /etc/lumisignals/web-app.env; set +a; cd /opt/lumisignals/app; \
  export REDIR='https://127.0.0.1/?code=PASTE_FULL_URL_HERE'; /opt/lumisignals/venv/bin/python" <<'PY'
import os
from urllib.parse import urlparse, parse_qs
from lumisignals.schwab_client import SchwabAuth
code = parse_qs(urlparse(os.environ['REDIR']).query).get('code', [''])[0]
a = SchwabAuth(os.environ['SCHWAB_CLIENT_ID'], os.environ['SCHWAB_CLIENT_SECRET'],
               token_file='/opt/lumisignals/schwab_tokens.json')
print('EXCHANGE:', 'OK' if a.exchange_code(code) else 'FAILED')
PY
```

`EXCHANGE: OK` = done. If `FAILED`, the code expired — regenerate the URL and
retry faster (be ready to run step 2 the instant you get the redirect).

## Verify it worked

```bash
ssh lumi-prod "set -a; source /etc/lumisignals/web-app.env; set +a; cd /opt/lumisignals/app; \
  /opt/lumisignals/venv/bin/python -c 'import os; from lumisignals.schwab_client import SchwabAuth, SchwabMarketData; \
  a=SchwabAuth(os.environ[\"SCHWAB_CLIENT_ID\"],os.environ[\"SCHWAB_CLIENT_SECRET\"],token_file=\"/opt/lumisignals/schwab_tokens.json\"); \
  print(\"auth:\", a.is_authenticated, \"quote:\", bool(SchwabMarketData(a).get_quote(\"AAPL\")))'"
```
Expect `auth: True quote: True`.

## The refresh keepalive (so it lasts the full 7 days)

- `schwab-refresh.timer` runs `/usr/local/bin/schwab-refresh.sh` every ~20 min
  to refresh the access token. Check it:
  ```bash
  ssh lumi-prod 'systemctl is-active schwab-refresh.timer; systemctl list-timers schwab-refresh.timer --no-pager | head -3'
  ```
- It reads creds from `web-app.env`, calls `SchwabAuth.refresh_access_token()`,
  and re-saves `schwab_tokens.json`. Run it once manually to confirm it's
  healthy after a re-auth:
  ```bash
  ssh lumi-prod 'bash /usr/local/bin/schwab-refresh.sh; echo exit=$?'
  ```
  Expect `{"refresh_ok": true, ...}` and `exit=0`.

> **History note:** the refresh script silently failed for a while because it
> imported a `token_status()` helper that didn't exist (ImportError every run)
> → the token kept dying early. Fixed by adding `token_status()` to
> `lumisignals/schwab_client.py`. If the cron starts failing, check for a
> similar import/contract drift first.

## Gotchas

- **Code expires in ~30s.** The slow steps (logging in) don't count — the
  clock starts when you click Allow / get the redirect. Be fast after that.
- **Wrong python = numpy crash.** Always `/opt/lumisignals/venv/bin/python`.
- **Wrong token path = no effect.** Must be `/opt/lumisignals/schwab_tokens.json`
  (the env has no `SCHWAB_TOKEN_FILE`, so that's the default the bot reads).
- **Run on lumi-prod, not your Mac** — the creds and token file live there.
