# Ceres784 Live-Data Cutover Runbook

**Status (2026-06-02):** prod is on Ceres5298 (Sim account). New `Ceres784` account exists in 1Password under "Interactive Brokers" with real-time market data subscriptions. Attempt to wire IBeam against Ceres784 at 14:51 UTC failed — selenium login dropped at the 2FA step. Rolled back; IBeam re-authed against Ceres5298 cleanly.

This runbook is the path to actually flipping IBeam to Ceres784 once the interactive prereqs are done.

## Why it didn't work the first try

IBeam runs a headless Chromium that drives the IBKR Client Portal login flow. For Ceres5298 the session has been live for 3 weeks — IBKR's "trusted device" cache covers it. For Ceres784, fresh IP + fresh username triggered IBKR's 2FA challenge (IB Key push, per the IBeam config: `TWO_FA_SELECT_TARGET: 'IB Key'`). Selenium can't approve a phone push, so login dropped after the credential submit.

## Prereqs (interactive, you do these)

### 1. Seed Ceres784 as a trusted device

- Open Client Portal in a normal browser: https://www.interactivebrokers.com/sso/Login
- Log in as **Ceres784**
- Complete whatever 2FA IBKR throws (IB Key push → approve on phone, or SMS code if that's the method)
- Look for "Remember this device" / "Trust this browser" — check it
- This adds the device fingerprint to IBKR's allowlist for ~30 days

This step alone won't help the headless droplet — IBKR fingerprints by browser, not account. But it tells IBKR the account is active and not in some "first-login-must-be-interactive" hold.

### 2. Choose a 2FA mode the droplet can use

IBKR offers three 2FA options on retail accounts:

| Mode | Works headless? | How |
|---|---|---|
| **IB Key (mobile push)** | No — requires phone tap each time | Push to phone, you approve manually |
| **IB Key (challenge code)** | Yes, with effort | IBKR sends a numeric code; you generate response via the IB Key mobile app's "Generate Code" feature. IBeam can prompt for this via `CUSTOM_TWO_FA_HANDLER` |
| **SMS / Security Card** | Yes, with handler | Phone receives code; pipe to IBeam via Telegram bot, env var, or similar handler |

The IBeam container is *already configured* for `CUSTOM_TWO_FA_HANDLER: 'custom_two_fa_handler.CustomTwoFaHandler'`. Source is mounted at `/opt/lumisignals/cpapi/custom_two_fa_handler.py` (verify) — it must work for Ceres784 too if Ceres5298 was using the same handler, but worth re-confirming.

### 3. Confirm the paper sub-account ID

The `paper_account_id` field in the "Interactive Brokers" 1P item should hold Ceres784's paper sub-account ID (DU* prefix). The bot auto-discovers it via `/iserver/accounts[0]` once IBeam authenticates, so no env-var change needed.

But: if you actually want LIVE trading (not just live data), you need to:
- Flip `IBEAM_TRADING_MODE=live` in `ibeam.env.tpl`
- Flip `IBEAM_USE_PAPER_ACCOUNT=False`
- Confirm `live_account_id` in 1P is correct
- This is the irreversible step. Don't do it until paper-with-real-data is verified end-to-end.

## Cutover steps (after prereqs)

1. Verify on the droplet that op is signed in (`source ~/.op-cache && op vault list`)
2. Render the env file (the .tpl already exists at `ops/cpapi/ibeam.env.tpl`):
   ```bash
   op inject -i ops/cpapi/ibeam.env.tpl -o /tmp/ibeam.env.new --force
   ```
3. Scp to lumi-prod and install (root:root, 0600):
   ```bash
   scp /tmp/ibeam.env.new lumi-prod:/tmp/ibeam.env.new
   ssh lumi-prod 'sudo cp /opt/lumisignals/cpapi/ibeam.env /opt/lumisignals/cpapi/ibeam.env.bak-$(date +%Y%m%d-%H%M%S)
                   sudo install -m 600 -o root -g root /tmp/ibeam.env.new /opt/lumisignals/cpapi/ibeam.env'
   shred -u /tmp/ibeam.env.new
   ```
4. Restart IBeam container:
   ```bash
   ssh lumi-prod 'cd /opt/lumisignals/cpapi && sudo docker compose down && sudo docker compose up -d'
   ```
5. Watch the auth flow (you'll need to be near your phone for IB Key approval):
   ```bash
   ssh lumi-prod 'sudo docker logs -f ibeam' &
   ```
6. After "Logging in succeeded" → "AUTHENTICATED", verify:
   ```bash
   curl -fsk "https://localhost:5000/v1/api/iserver/auth/status" | jq .
   ```
   Should show `"authenticated": true`.
7. Check the bot's snapshot updates (within 10s):
   ```bash
   ssh lumi-prod 'redis-cli GET "ibkr:data:1"' | jq '.last_synced, (.positions | length)'
   ```

## Rollback (already proven)

If anything fails:
```bash
ssh lumi-prod 'BACKUP=$(ls -t /opt/lumisignals/cpapi/ibeam.env.bak-* | head -1)
                sudo cp "$BACKUP" /opt/lumisignals/cpapi/ibeam.env
                sudo chmod 600 /opt/lumisignals/cpapi/ibeam.env
                cd /opt/lumisignals/cpapi && sudo docker compose down && sudo docker compose up -d'
```

After 60s IBeam's maintenance loop re-authenticates against the old credentials. Verified working on 2026-06-02.

## Open questions for the live-money phase

- Do we want bot.lumitrade.ai to ever trade real money, or is Ceres784-paper-with-real-data the goal?
- What's the dollar threshold below which live trading is acceptable (e.g. micro-futures at 1 contract = $5/pt MES)?
- Are there any IBKR-side rate limits / position caps to set as a safety net before going live?

## When to revisit OAuth

If Ceres784 (or any other account) ever gets upgraded to an IB Pro / Institutional account, OAuth becomes the right answer:
- No selenium / Chrome dependency
- Long-lived tokens, deterministic auth
- IBKR Client Portal → Settings → API → Settings → Register Consumer (only visible on Institutional accounts)
- Workflow: generate RSA 2048 keypair, upload public key, get consumer key, sign requests
- Reference: https://www.interactivebrokers.com/campus/ibkr-api-page/oauth/
