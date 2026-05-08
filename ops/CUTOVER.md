# IB Gateway → IBeam + CPAPI Cutover Plan

## What changes

| Before | After |
|---|---|
| `gnzsnz/ib-gateway` Docker container (Java IB Gateway) | `voyz/ibeam` Docker container (CPAPI Gateway + auto-login) |
| `theasp/novnc` Docker container | (removed — no VNC needed) |
| nginx vhost: `/ib-vnc/` and `/ib-vnc/websockify` | (removed) |
| `python -m lumisignals.ibkr_sync` running ad-hoc as a detached process | `lumisignals-ibkr-sync.service` running `ibkr_sync_cpapi` under systemd |
| Manual VNC login required daily | Push notification on phone (if IBKR Mobile push 2FA) — one tap, ~5s/day |
| TWS API on `127.0.0.1:4002` (binary socket) | CPAPI on `https://localhost:5000` (REST) |

## Pre-flight (do these BEFORE cutover, can be done now)

1. Confirm IB account 2FA mode is **IBKR Mobile push** (or none).
   Log into `https://www.interactivebrokers.com/portal` → User → Security → Two-Factor Authentication.
   If it's SMS or Secure Login Device: stop and reconfigure to Mobile push first, OR plan a manual session via the CPAPI login page.
2. Confirm the IB username and password used for VNC login are known and correct. These go into `ibeam.env`.
3. Verify the IB account has Client Portal API access enabled (it does by default for most account types).

## Stage 1 — Place files (no behavior change)

On prod, as root:

```bash
# 1. Backup current config
mkdir -p /root/cutover-backup-$(date +%Y%m%d)
cp /opt/lumisignals/cpapi/docker-compose.yml /root/cutover-backup-$(date +%Y%m%d)/docker-compose.yml.old
cp /etc/nginx/sites-enabled/lumisignals /root/cutover-backup-$(date +%Y%m%d)/nginx.conf.old
systemctl cat lumisignals-bot > /root/cutover-backup-$(date +%Y%m%d)/lumisignals-bot.service.old

# 2. Copy new files from dev droplet (or paste in place)
# docker compose
scp <dev>:/home/sonia/projects/LumiSignals/ops/cpapi/docker-compose.yml /opt/lumisignals/cpapi/docker-compose.yml.new
scp <dev>:/home/sonia/projects/LumiSignals/ops/cpapi/ibeam.env.example /opt/lumisignals/cpapi/ibeam.env

# Edit credentials
nano /opt/lumisignals/cpapi/ibeam.env   # fill IBEAM_ACCOUNT, IBEAM_PASSWORD
chmod 600 /opt/lumisignals/cpapi/ibeam.env

# systemd service + env
mkdir -p /etc/lumisignals
scp <dev>:/home/sonia/projects/LumiSignals/ops/systemd/lumisignals-ibkr-sync.service /etc/systemd/system/lumisignals-ibkr-sync.service.new
scp <dev>:/home/sonia/projects/LumiSignals/ops/systemd/ibkr-sync.env.example /etc/lumisignals/ibkr-sync.env
nano /etc/lumisignals/ibkr-sync.env    # fill IBKR_SYNC_KEY (use ibkr_sync_2026 to match existing)
chmod 600 /etc/lumisignals/ibkr-sync.env
chown root:root /etc/lumisignals/ibkr-sync.env
```

(Files are staged as `.new`; nothing is active yet. We can review/diff before flipping.)

## Stage 2 — Stop old, start new

```bash
# 1. Stop the manual sync process (PID was 505173, find current)
pkill -f "lumisignals.ibkr_sync$" || true
sleep 2

# 2. Stop and remove old containers
cd /opt/lumisignals/cpapi
docker compose down                          # stops ib-gateway + novnc

# 3. Swap compose file
mv docker-compose.yml docker-compose.yml.old-vnc
mv docker-compose.yml.new docker-compose.yml

# 4. Pull and start IBeam
docker compose pull
docker compose up -d
```

## Stage 3 — Watch IBeam authenticate

```bash
docker logs -f ibeam
```

Expected log timeline:
- `Starting IBeam ...`
- `Gateway started`
- `Logging in...`
- *If IBKR Mobile push 2FA*: a notification arrives on the registered phone. **Approve it within 30 seconds.**
- `Authenticated`
- `Tickle successful`

If login fails or times out:
- `Authentication strategy 'B' did not complete` → 2FA type isn't compatible. Stop here, do `docker compose down`, restart the old VNC stack from the backup, and reconsider.
- Check `IBEAM_ACCOUNT` / `IBEAM_PASSWORD` typos in `ibeam.env`.

## Stage 4 — Verify CPAPI reachable

```bash
curl -k https://localhost:5000/v1/api/one/user
# Expect 200 with a JSON body containing the IB username.

curl -k https://localhost:5000/v1/api/iserver/auth/status
# Expect {"authenticated":true,"connected":true,"competing":false,...}
```

If both return 200 with `authenticated:true`, the gateway is live.

## Stage 5 — Start the new sync service

```bash
mv /etc/systemd/system/lumisignals-ibkr-sync.service.new /etc/systemd/system/lumisignals-ibkr-sync.service
systemctl daemon-reload
systemctl enable lumisignals-ibkr-sync
systemctl start lumisignals-ibkr-sync
systemctl status lumisignals-ibkr-sync --no-pager

# Watch sync logs
tail -F /var/log/lumisignals_ibkr_sync.log
```

Expected: `IB CPAPI Sync starting — connecting to https://localhost:5000/v1/api`, then `Connected to CPAPI — syncing every 10s ...`, then NAV / Positions / Orders lines every 10 seconds.

## Stage 6 — Clean up nginx (optional, do after 24h of stability)

Once the new stack has run a full day without intervention:

```bash
# Remove the now-dead /ib-vnc/ proxy from nginx
sed -i.bak '/location \/ib-vnc\//,/^    }/d' /etc/nginx/sites-enabled/lumisignals
nginx -t && systemctl reload nginx
```

## Rollback (if anything in stages 2–5 fails)

```bash
# 1. Stop new
systemctl stop lumisignals-ibkr-sync 2>/dev/null
systemctl disable lumisignals-ibkr-sync 2>/dev/null
rm -f /etc/systemd/system/lumisignals-ibkr-sync.service
systemctl daemon-reload

cd /opt/lumisignals/cpapi
docker compose down

# 2. Restore old compose
mv docker-compose.yml docker-compose.yml.ibeam-failed
mv docker-compose.yml.old-vnc docker-compose.yml
docker compose up -d

# 3. Restart the old sync the same way it was running
cd /opt/lumisignals/app
nohup /opt/lumisignals/venv/bin/python3 -m lumisignals.ibkr_sync >> /var/log/lumisignals_ibkr_sync.log 2>&1 &
```

(The full backup is in `/root/cutover-backup-YYYYMMDD/` for any deeper restores.)

## Post-cutover hygiene

- Move all secrets currently inlined in `lumisignals-bot.service` and `lumisignals.service` into `/etc/lumisignals/*.env` files (`chmod 600`) and reference via `EnvironmentFile=`. Same pattern as the new sync service. Not part of this cutover, but next on the list — those plaintext keys appear in `systemctl cat` output.
- Add a Cloudwatch/Sentry/email alert on `lumisignals-ibkr-sync.service` failure and on the IBeam `/iserver/auth/status` endpoint returning `authenticated:false`.
- Document the daily push-tap step somewhere visible (or set up a script that nudges via SMS/email if a session goes 30+ min without being live).
