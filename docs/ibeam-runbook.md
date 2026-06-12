# IBeam / IBKR Connection Runbook

**Authoritative state as of 2026-06-03.** Supersedes parts of `ceres784-cutover.md` (kept for historical context but the cutover concluded with a different outcome than that runbook anticipated).

---

## Quick reference

| Thing | Value |
|---|---|
| IBeam image | `voyz/ibeam:latest` (pinned at Apr 21 2026 build until further notice) |
| Container | `ibeam` on `lumi-prod` (174.138.46.187), runs the CPAPI gateway inside |
| Gateway URL | `https://localhost:5000/v1/api/...` (HTTPS, self-signed cert) |
| Compose path | `/opt/lumisignals/cpapi/docker-compose.yml` |
| Env file | `/opt/lumisignals/cpapi/ibeam.env` (root:root, 0600, gitignored) |
| Env tpl | `ops/cpapi/ibeam.env.tpl` (committed; references 1Password items only) |
| 1P "Interactive Brokers" | Ceres784 — **LIVE** account, real-time data subscription holder |
| 1P "Interactive Brokers Sim" | **Ceres5299** — current paper login (post-merger, inherits 784's data subs) |
| Currently logged in as | **Ceres5299** (paper) |
| Paper sub-account ID | `DUP888072` (auto-discovered by IBeam from `/iserver/accounts[0]`) |
| Mobile reauth button | `/api/ib/reauth` — only refreshes existing sessions; useless if IBeam has shut down |
| Manual login proxy | `https://bot.lumitrade.ai/ib-auth/proxy/sso/Login` (renders the gateway's login form through Flask + Nginx) |

## Why we're on Ceres5299, not Ceres784

The original plan (see `ceres784-cutover.md`) was to log IBeam in as **Ceres784** (the live, funded account) with `IBEAM_USE_PAPER_ACCOUNT=True` to use the live account's paper sub-account — getting real-time market data while trading paper.

What actually killed that path: when IBeam tries to "switch to paper mode" inside the live account, **IBKR shows a "Welcome to Paper Trading — I Understand and Accept" disclaimer on every session.** IBeam's selenium has no handler for that button — it sees the URL change post-login, matches its "logged in" page indicator, and reports `Logging in succeeded`. But the actual session never establishes because the disclaimer is gating it. Log signature:

```
Logging in succeeded
NO SESSION Status(running=True, session=False, ...)
Repeatedly reauthenticating failed 3 times. Killing the Gateway and restarting.
```

The "I Understand and Accept" acknowledgment is **per-IBKR-session, not per-account** — clicking it interactively in your phone browser doesn't help because IBeam's fresh selenium Chrome has no cookies from your session.

Workaround that's in place now: log in directly as Ceres5299 (the paper username IBKR created when Ceres784 was approved post-merger). It's already paper, no switch step, no disclaimer.

Real long-term fix would be a custom IBeam patch that clicks the disclaimer (~half-day of work, extends `voyz/ibeam:latest`). Tracked as a deferred improvement; not blocking anything today.

---

## Routine ops

### Restart IBeam (after a code change to the env or compose)
```bash
ssh lumi-prod 'cd /opt/lumisignals/cpapi && sudo docker compose down && sudo docker compose up -d'
```
Watch the logs while it logs in:
```bash
ssh lumi-prod 'sudo docker logs -f ibeam'
```
Expected on success (within ~30-90s):
- `Login attempt number 1`
- `Switching to paper mode`
- `Logging in succeeded`
- `AUTHENTICATED Status(running=True, session=True, connected=True, authenticated=True, ...)`

After that: `Maintenance` ticks every 60s and that's it.

### Verify the session is alive
```bash
ssh lumi-prod 'curl -fsk https://localhost:5000/v1/api/iserver/auth/status'
```
Look for `"authenticated": true, "connected": true, "competing": false`.

Or check the bot's freshness signal:
```bash
ssh lumi-prod 'redis-cli TTL "ibkr:data:1"'
```
Should be 50-60 (the bot pushes to this key every ~10s with a 60s TTL). `-2` means the key doesn't exist → bot not pushing → IBeam likely down or session lost.

### Check real-time vs delayed data
Pre-flight a snapshot then read it:
```bash
ssh lumi-prod 'curl -fsk "https://localhost:5000/v1/api/iserver/marketdata/snapshot?conids=265598&fields=31,84,86,6509" >/dev/null; sleep 2; curl -fsk "https://localhost:5000/v1/api/iserver/marketdata/snapshot?conids=265598&fields=31,84,86,6509"'
```
Field `6509`:
- Starts with **`R`** → real-time (e.g. `RPB`)
- Starts with **`D`** → delayed (e.g. `DPB`)
- Starts with **`Z`** → frozen (closed market, last known)

Schwab as an independent real-time benchmark (free, requires `config.yaml` + `schwab_tokens.json` valid):
```python
from lumisignals.schwab_client import SchwabMarketData, SchwabAuth
import yaml
sc = yaml.safe_load(open("config.yaml"))["schwab"]
auth = SchwabAuth(client_id=sc["client_id"], client_secret=sc["client_secret"],
                  token_file="schwab_tokens.json")
md = SchwabMarketData(auth)
q = md.get_quote("AAPL")
print(q["realtime"], q["quote"]["lastPrice"], q["quote"]["tradeTime"])
```

## Failure modes seen so far

### "Invalid username password combination"
IBKR is rejecting the credentials. Two flavors:
- **The password is genuinely wrong** — typically because a funding/merger event forced a password reset and 1P wasn't updated.
- **The account is locked / mid-verification** — common during funding/merger. Browser-log-in to https://www.interactivebrokers.com/sso/Login and complete whatever IBKR shows (SMS verification, identity confirmation, TOS update).

Don't restart IBeam more than once before the account is unblocked — every failed login sends an SMS to your phone and edges closer to a real account lockout.

### `Logging in succeeded` → `Repeatedly reauthenticating failed`
This was today's blocker. Means selenium matched a "logged in" page indicator but the gateway never got a session cookie. Almost always a post-credentials interstitial (TOS, "Welcome to Paper Trading", market-data agreement, account picker). Selenium can't navigate these.

Fix path:
1. Stop IBeam immediately (`docker stop ibeam`) so you don't burn auth attempts.
2. Identify which interstitial is appearing by doing a manual login at https://www.interactivebrokers.com/sso/Login.
3. If it's a one-time TOS-style ack: click through, then restart IBeam — it should sail through next time.
4. If it's per-session (like "Welcome to Paper Trading"): you can't fix it from the IBKR side. Switch to a login flow that avoids the page (e.g. direct paper login instead of live + switch-to-paper).

### Push 2FA every login
Means IBKR doesn't recognize the droplet as a trusted device. Two paths:
- **Stand by your phone** when restarting IBeam — tap Approve on the push within ~30s of the restart. `IBEAM_TWO_FA_HANDLING=true` waits for the tap.
- **Build trust over time** — each successful login extends IBKR's trusted-device window. After ~3 weeks of uninterrupted weekly auth cycles, the prompt usually stops.

### SMS / Challenge-code 2FA
**IBeam cannot handle SMS or challenge-code 2FA in the current setup.** No `custom_two_fa_handler.py` is mounted. If you ever see Ceres5299 (or any future account) ask for SMS or challenge code on every login, you have two options:
- Switch the account's 2FA mode in IBKR Account Management to IB Key (Push) — the only mode the current handler supports.
- Build the deferred Telegram-based 2FA pipe (separate work item — ~half-day).

### Bot's mobile app shows stale data but IBeam logs look healthy
Check whether the gateway's session is still valid:
```bash
ssh lumi-prod 'curl -fsk https://localhost:5000/v1/api/iserver/auth/status'
```
If `authenticated: false`, IBeam needs to re-login. The mobile reauth button calls `/iserver/reauthenticate` which only works if IBeam still has cookies. If it returns "not logged in", do a full container restart.

### Competing session
Log shows `competing=True, collision=True`. Means someone else (you on your phone, the IBKR web app, TWS) is logged in with the same username. **One session per username across all IBKR platforms.** Log out everywhere else, then restart IBeam.

---

## Switching IBeam back to Ceres784 (live trading)

**Read this section in full before doing anything. Going live = real money.**

### The credentials you'll need

Two separate IBKR logins are tied to the same trading household:

| Username | Account type | Where it logs you in |
|---|---|---|
| **Ceres784** | Live (funded) | Real account, real orders, real money |
| **Ceres5299** | Paper | Simulated trading sub-account |

Different usernames, different passwords. The paper sub-account inherits the live account's market data subscriptions (eventually, once IBKR propagates the toggle).

Ceres784's credentials are already in 1Password under "Interactive Brokers". They've been there since 2026-06-02 14:29 UTC and were last confirmed valid 2026-06-03.

### Pre-flight checks

Do these in order before flipping anything:

1. **Funding has fully cleared and merger approval is complete.** Verify on https://www.interactivebrokers.com/sso/Login as Ceres784 that you reach the Account Management dashboard without pending verification banners.
2. **Real-time market data subscriptions are active on Ceres784** — check `Settings → User Settings → Market Data Subscriptions`. You should see entries like "US Securities Snapshot and Futures Value Bundle" or "NASDAQ TotalView" with status "Active".
3. **`Share Market Data with Paper Trading Account`** toggle should already be on (we'll keep paper as a fallback option). Confirm it's set.
4. **Test the live login interactively first.** Browser-login as Ceres784, accept any "Welcome to Live Trading" disclaimer it shows, get to the dashboard, log out. This proves the credentials work and clears any one-time acks.
5. **Decide on safety gates before flipping IBeam:**
   - Confirm `equity:orders_enabled` Redis flag state: `ssh lumi-prod 'redis-cli GET equity:orders_enabled'`. Keep it `0` for the first session.
   - Confirm `ibkr:reconciler:disabled` Redis flag: `0` is normal.
   - Confirm kill switch state: `ssh lumi-prod 'redis-cli GET risk:kill_switch:state'`.
   - Have an idea of position size limits and per-strategy caps you're comfortable with.

### The flip

1. **Update the tpl** to point at the live account item:
   ```diff
   - IBEAM_ACCOUNT={{ op://Lumi/Interactive Brokers Sim/username }}
   - IBEAM_PASSWORD={{ op://Lumi/Interactive Brokers Sim/password }}
   + IBEAM_ACCOUNT={{ op://Lumi/Interactive Brokers/username }}
   + IBEAM_PASSWORD={{ op://Lumi/Interactive Brokers/password }}
   ```
   And flip the trading-mode lines:
   ```diff
   - IBEAM_TRADING_MODE=paper
   + IBEAM_TRADING_MODE=live
   ```
   ```diff
   - IBEAM_USE_PAPER_ACCOUNT=True
   + IBEAM_USE_PAPER_ACCOUNT=False
   ```

   Critical: set `USE_PAPER_ACCOUNT=False`. Setting it to True with the live login is what triggered the "Welcome to Paper Trading" disclaimer wall today. Live + USE_PAPER_ACCOUNT=False bypasses the disclaimer entirely (you're staying on the live sub-account; no switch needed).

2. **Backup the current ibeam.env** before overwriting, in case rollback is needed:
   ```bash
   ssh lumi-prod 'sudo cp /opt/lumisignals/cpapi/ibeam.env /opt/lumisignals/cpapi/ibeam.env.bak-pre-live-$(date +%Y%m%d-%H%M%S)'
   ```

3. **Render and ship** (mirrors the cutover steps used for the Ceres5299 switch):
   ```bash
   op inject -i ops/cpapi/ibeam.env.tpl -o /tmp/ibeam.env.new --force
   scp /tmp/ibeam.env.new lumi-prod:/tmp/ibeam.env.new
   ssh lumi-prod 'sudo install -m 600 -o root -g root /tmp/ibeam.env.new /opt/lumisignals/cpapi/ibeam.env && rm /tmp/ibeam.env.new'
   shred -u /tmp/ibeam.env.new
   ```

4. **Restart and watch** with your phone in hand:
   ```bash
   ssh lumi-prod 'cd /opt/lumisignals/cpapi && sudo docker compose down && sudo docker compose up -d && sleep 5 && sudo docker logs -f ibeam'
   ```
   Approve the IB Key push if it appears.

5. **Verify live session is established:**
   ```bash
   ssh lumi-prod 'curl -fsk https://localhost:5000/v1/api/iserver/auth/status'
   ssh lumi-prod 'curl -fsk https://localhost:5000/v1/api/iserver/accounts'
   ```
   The account ID returned should be the live account ID (Ceres784's actual account number, **not** `DUP*` — DU prefix is paper-only).

6. **Confirm real-time data** is now flowing (the 6509 prefix should be `R*`, not `D*`):
   ```bash
   ssh lumi-prod 'curl -fsk "https://localhost:5000/v1/api/iserver/marketdata/snapshot?conids=265598&fields=31,6509" >/dev/null; sleep 2; curl -fsk "https://localhost:5000/v1/api/iserver/marketdata/snapshot?conids=265598&fields=31,6509"'
   ```

### Cutting in real orders (separate from the login flip)

Just having IBeam authenticated against the live account does NOT mean the bot will place real orders. The bot reads `equity:orders_enabled` and `ibkr:reconciler:disabled` flags before submitting.

Order-enable path, once live login is confirmed working for at least one full session (~24h is reasonable):

1. Start with one strategy and one symbol. Pick a low-risk one — e.g., futures_2n20 on MES, or a swing/MTF setup with small `max_risk_usd`.
2. Set `equity:orders_enabled=1` in Redis to permit submission.
3. Watch the next entry signal closely. Confirm:
   - The order appears in TWS / mobile / `gh api`-equivalent (whatever you use to see IB-side orders).
   - The fill appears in IBeam's `/iserver/trades` endpoint.
   - The mobile app's Open Positions shows it.
   - The strat_pos in Redis has correct strategy + model tags.
4. After 1-2 successful cycles, gradually enable more strategies.

### Rollback to paper (if something goes wrong)

```bash
ssh lumi-prod 'BACKUP=$(ls -t /opt/lumisignals/cpapi/ibeam.env.bak-pre-live-* | head -1) && \
                sudo cp "$BACKUP" /opt/lumisignals/cpapi/ibeam.env && \
                sudo chmod 600 /opt/lumisignals/cpapi/ibeam.env && \
                cd /opt/lumisignals/cpapi && sudo docker compose down && sudo docker compose up -d'
```

Within ~60s IBeam will be back on Ceres5299 paper. Verified-working rollback path from 2026-06-02.

Also flip `equity:orders_enabled=0` so the bot stops trying to place orders against the now-paper account:
```bash
ssh lumi-prod 'redis-cli SET equity:orders_enabled 0'
```

---

## Things explicitly NOT supported today

These are deferred work items, not bugs. They cause confusion if you assume they work:

- **SMS-based 2FA** for IBeam. The `custom_two_fa_handler.py` mentioned in `ceres784-cutover.md` does not exist on lumi-prod; building it requires implementing a Telegram (or similar) interactive code pipe. Estimated ~half-day.
- **Push 2FA without manual approval**. IB Key Push works, but you have to tap Approve on your phone within ~30s of an IBeam restart. There's no zero-touch path.
- **Headless OAuth**. IBKR's OAuth 2.0 is Organizations/Institutional-only. OAuth 1.0a is gated behind Third-Party Vendor approval (3-6 week Compliance review). Long-term aspiration only.
- **TWS API** as an alternative to IBeam. Documented in `docs/ceres784-cutover.md` discussion — also requires GUI login and would just shift the same 2FA problem to a different selenium wrapper.
- **FIX**. Account minimums ($10K equity + $1500/mo commissions) make this out of reach until/unless trading volume scales.

See `memory/ib-api-choice-rationale.md` for the rationale on why we stay with CP API / IBeam.

---

## Useful one-liners

```bash
# Restart everything cleanly (gateway + bot)
ssh lumi-prod 'cd /opt/lumisignals/cpapi && sudo docker compose down && sudo docker compose up -d && sudo systemctl restart lumisignals lumisignals-bot'

# Tail IBeam logs filtered to the meaningful lines only
ssh lumi-prod 'sudo docker logs -f ibeam 2>&1' | grep -E "Login attempt|Logging in (succeeded|failed)|AUTHENTICATED|NO SESSION|Invalid username|Repeatedly reauthenticating|TimeoutException"

# Force IBeam to give up after one failed attempt (paranoid mode — useful if you suspect IBKR is rate-limiting)
ssh lumi-prod 'sudo sed -i "s/^IBEAM_MAX_FAILED_AUTH=.*/IBEAM_MAX_FAILED_AUTH=1/" /opt/lumisignals/cpapi/ibeam.env'

# Watch the bot's IB data freshness in real time
ssh lumi-prod 'watch -n 5 "redis-cli TTL ibkr:data:1; redis-cli GET ibkr:data:1 | jq .last_synced"'

# See exactly which account IBeam is currently authenticated against (no creds revealed)
ssh lumi-prod 'curl -fsk https://localhost:5000/v1/api/iserver/accounts | python3 -m json.tool | head -20'
```
