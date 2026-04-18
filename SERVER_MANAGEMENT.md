# LumiSignals — Server Management

## Server Info

- **Provider:** Digital Ocean
- **IP:** 174.138.46.187
- **Domain:** bot.lumitrade.ai (HTTPS via Let's Encrypt)
- **SSH:** `ssh root@174.138.46.187`

## Services

Two systemd services run on the droplet:

| Service | What it does | Port |
|---------|-------------|------|
| `lumisignals` | Web app (gunicorn) — serves the dashboard, API | 8000 (behind Nginx) |
| `lumisignals-bot` | Bot runner — scans markets, places trades | N/A (background process) |

Both auto-start on server reboot and auto-restart on crash.

## Common Commands

```bash
# Check status
systemctl status lumisignals
systemctl status lumisignals-bot

# Restart
systemctl restart lumisignals
systemctl restart lumisignals-bot

# Stop
systemctl stop lumisignals-bot

# View logs
journalctl -u lumisignals -f          # web app logs (live)
journalctl -u lumisignals-bot -f      # bot runner logs (live)
tail -100 /var/log/lumisignals_bot.log # bot runner log file

# Check Nginx
systemctl status nginx
nginx -t                              # test config
```

## Deploying Code

From your local Mac:

```bash
cd /Users/sonia/Documents/LumiTrade/LumiSignals
bash saas/deploy.sh
```

This uploads code via rsync and restarts the web app. To also restart the bot runner after deploy:

```bash
ssh root@174.138.46.187 "systemctl restart lumisignals-bot"
```

## Database

```bash
# Connect to PostgreSQL
ssh root@174.138.46.187 "sudo -u postgres psql -d lumisignals_db"

# Run a migration
ssh root@174.138.46.187 "sudo -u postgres psql -d lumisignals_db -c 'ALTER TABLE ...'"
```

## SSL Certificate

Managed by Let's Encrypt / Certbot. Auto-renews. If needed:

```bash
ssh root@174.138.46.187 "certbot --nginx -d bot.lumitrade.ai"
```

The deploy script preserves the SSL config (won't overwrite Nginx).
