"""One-shot backfill for FX closes that landed in Oanda but never made it
into Supabase because oanda_trade_sync filtered them out (no signal_log
match, no recognized clientExtensions tag).

Attribution strategy: parse /var/log/lumisignals_bot.log for OPEN events
(H1ZONE, fx_4h, levels_strategy TRADE:) and match each Oanda close by
(instrument, side, openTime ±90s, initialUnits). Anything that can't be
matched against the log is reported but not written — manual reclassify.

Usage:
    python3 scripts/backfill_orphan_closes.py --dry-run --since 2026-05-14
    python3 scripts/backfill_orphan_closes.py --since 2026-05-14    # writes

Env needed (already in /etc/lumisignals/bot-runner.env on prod):
    OANDA token + account come from the users table.
    SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_USER_ID.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional


def _http_get(url: str, headers: dict, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _parse_oanda_time(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").split(".")[0] + "+00:00")
    except Exception:
        return None


# ---------- Bot log parsing ----------------------------------------------

# 2026-05-14 17:31:46 [INFO] lumisignals.fx_h1_zone_scalp:
#   [H1ZONE] OPEN USD_CAD/alpha BUY @ 1.37156  stop=1.37109 ...  units/leg=29390
H1ZONE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[H1ZONE\] OPEN "
    r"(?P<pair>[A-Z]{3}_[A-Z]{3})/(?P<variant>\w+) (?P<side>BUY|SELL) "
    r"@ (?P<entry>[\d.]+).*units/leg=(?P<units>\d+)"
)

# 2026-05-14 19:17:19 [INFO] lumisignals.fx_trend_4h:
#   fx_4h OPEN USD_JPY SHORT 100000 units @ 158.36400 ...
FX4H_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*fx_4h OPEN "
    r"(?P<pair>[A-Z]{3}_[A-Z]{3}) (?P<side>LONG|SHORT|BUY|SELL) "
    r"(?P<units>\d+) units @ (?P<entry>[\d.]+)"
)

# 2026-05-14 22:47:42 [INFO] lumisignals.levels_strategy:
#   TRADE: SELL USD_CAD @ 1.37160 | Stop: 1.37228 | Target: 1.36752 | R:R: 6.0
LEVELS_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*levels_strategy: "
    r"TRADE: (?P<side>BUY|SELL) (?P<pair>[A-Z]{3}_[A-Z]{3}) "
    r"@ (?P<entry>[\d.]+) \| Stop: (?P<stop>[\d.]+) \| Target: (?P<target>[\d.]+)"
)

# 2026-05-14 10:08:00 [INFO] lumisignals.fx_scalp_2n20:
#   2n20 FX SELL EUR_USD @ 1.17066 (fill: 1.17075) — SL 1.17125, units 50000
N2N20_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*2n20 FX "
    r"(?P<side>BUY|SELL) (?P<pair>[A-Z]{3}_[A-Z]{3}) "
    r"@ (?P<entry>[\d.]+).*SL (?P<stop>[\d.]+), units (?P<units>\d+)"
)


def parse_bot_log(path: str, since: str) -> list:
    """Return list of OPEN records: {ts, pair, side, entry, units, strategy, model, stop, target}.

    `since` is a date prefix like '2026-05-14' — lines before that are skipped fast.
    """
    out = []
    if not os.path.exists(path):
        return out
    with open(path, "r", errors="replace") as f:
        for line in f:
            if not line.startswith("20"):
                continue
            if line[:10] < since:
                continue
            m = H1ZONE_RE.search(line)
            if m:
                out.append({
                    "ts": m.group("ts"), "pair": m.group("pair"),
                    "side": m.group("side"),
                    "entry": float(m.group("entry")),
                    "units": int(m.group("units")),
                    "strategy": "scalp_h1zone", "model": m.group("variant"),
                    "stop": None, "target": None,
                    "level_timeframe": "1h", "level_type": "zone",
                })
                continue
            m = FX4H_RE.search(line)
            if m:
                side = m.group("side").upper()
                side = "BUY" if side in ("LONG", "BUY") else "SELL"
                out.append({
                    "ts": m.group("ts"), "pair": m.group("pair"),
                    "side": side,
                    "entry": float(m.group("entry")),
                    "units": int(m.group("units")),
                    "strategy": "fx_4h_trend", "model": "trend",
                    "stop": None, "target": None,
                    "level_timeframe": "4h", "level_type": "trend",
                })
                continue
            m = LEVELS_RE.search(line)
            if m:
                out.append({
                    "ts": m.group("ts"), "pair": m.group("pair"),
                    "side": m.group("side"),
                    "entry": float(m.group("entry")),
                    "units": None,  # levels uses risk-based sizing
                    "strategy": "htf_levels", "model": "",
                    "stop": float(m.group("stop")),
                    "target": float(m.group("target")),
                    "level_timeframe": "1h", "level_type": "zone",
                })
                continue
            m = N2N20_RE.search(line)
            if m:
                out.append({
                    "ts": m.group("ts"), "pair": m.group("pair"),
                    "side": m.group("side"),
                    "entry": float(m.group("entry")),
                    "units": int(m.group("units")),
                    "strategy": "vwap_2n20", "model": "scalp_2n20",
                    "stop": float(m.group("stop")),
                    "target": None,
                    "level_timeframe": "2m", "level_type": "vwap_overwhelm",
                })
    return out


def match_open(close_trade: dict, log_events: list) -> Optional[dict]:
    """Find best matching OPEN log entry for an Oanda CLOSED trade."""
    pair = close_trade.get("instrument", "")
    units = int(float(close_trade.get("initialUnits", 0)))
    side = "BUY" if units > 0 else "SELL"
    open_dt = _parse_oanda_time(close_trade.get("openTime", ""))
    entry = float(close_trade.get("price", 0))
    if not open_dt:
        return None
    abs_units = abs(units)
    best = None
    best_dt = 10**9
    for ev in log_events:
        if ev["pair"] != pair or ev["side"] != side:
            continue
        if ev["units"] is not None and ev["units"] != abs_units:
            continue
        # Entry price must match within 1 pip-ish (4 decimals for non-JPY,
        # 2 decimals for JPY pairs).
        if abs(ev["entry"] - entry) > (0.05 if "JPY" in pair else 0.0005):
            continue
        try:
            ev_dt = datetime.strptime(ev["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=open_dt.tzinfo)
        except Exception:
            continue
        delta = abs((ev_dt - open_dt).total_seconds())
        # Levels and H1Zone log at SIGNAL time but the limit can fill hours
        # later. Same pair + same side + same entry price (within 1 pip) +
        # same units is already a near-unique key — only require the log
        # event to be BEFORE the open (no fill before signal) and within
        # 8 hours. Closest in time wins on collision.
        if delta > 8 * 3600:
            continue
        if (ev_dt - open_dt).total_seconds() > 60:  # log can't be much after open
            continue
        if delta < best_dt:
            best_dt = delta
            best = ev
    return best


# ---------- Main ----------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-05-14", help="YYYY-MM-DD lower bound on closeTime")
    ap.add_argument("--log", default="/var/log/lumisignals_bot.log")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sb_url = os.environ["SUPABASE_URL"]
    sb_key = os.environ["SUPABASE_SERVICE_KEY"]
    user_id = os.environ["SUPABASE_USER_ID"]
    oanda_token = os.environ.get("OANDA_API_KEY") or os.environ["OANDA_TOKEN"]
    oanda_account = os.environ["OANDA_ACCOUNT_ID"]

    sb_headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    o_headers = {"Authorization": f"Bearer {oanda_token}"}

    # Already-recorded trade IDs (idempotency)
    q = (f"{sb_url}/rest/v1/trades?select=broker_trade_id&broker=eq.oanda"
         f"&closed_at=gte.{args.since}T00:00:00&limit=2000")
    existing = {r["broker_trade_id"] for r in _http_get(q, sb_headers)}
    print(f"Already in DB since {args.since}: {len(existing)}")

    # Oanda closed history (last 500)
    q = f"https://api-fxpractice.oanda.com/v3/accounts/{oanda_account}/trades?state=CLOSED&count=500"
    closed = _http_get(q, o_headers).get("trades", [])
    closed = [t for t in closed if t.get("closeTime", "") >= f"{args.since}T00:00:00"]
    print(f"Oanda closes since {args.since}: {len(closed)}")

    orphans = [t for t in closed if t["id"] not in existing]
    print(f"Orphans to attribute: {len(orphans)}")

    events = parse_bot_log(args.log, args.since)
    print(f"Bot-log OPEN events parsed: {len(events)}")

    matched = []
    unmatched = []
    for t in orphans:
        m = match_open(t, events)
        if m:
            matched.append((t, m))
        else:
            unmatched.append(t)

    print(f"\nMatched: {len(matched)}   Unmatched: {len(unmatched)}\n")
    for t, m in matched:
        units = int(float(t.get("initialUnits", 0)))
        print(f"  [MATCH] {t['id']:>8s} {t['instrument']:10s} "
              f"{'+' if units>0 else '-'}{abs(units):>6} "
              f"pl={float(t.get('realizedPL',0)):>+8.2f}  "
              f"strategy={m['strategy']}/{m['model']}  "
              f"opened={t['openTime'][:19]}")
    for t in unmatched:
        units = int(float(t.get("initialUnits", 0)))
        print(f"  [SKIP ] {t['id']:>8s} {t['instrument']:10s} "
              f"{'+' if units>0 else '-'}{abs(units):>6} "
              f"pl={float(t.get('realizedPL',0)):>+8.2f}  "
              f"opened={t['openTime'][:19]} — no log match")

    if args.dry_run:
        print(f"\nDry-run complete. {len(matched)} would be upserted.")
        return

    # Write each match. Hit the existing /api/ibkr/closed-trade endpoint
    # is overkill — go straight to Supabase for simplicity.
    written = 0
    for t, m in matched:
        units = int(float(t.get("initialUnits", 0)))
        direction = "LONG" if units > 0 else "SHORT"
        entry = float(t.get("price", 0))
        exit_p = float(t.get("averageClosePrice", 0))
        realized = float(t.get("realizedPL", 0))
        stop = m.get("stop") or (
            float(t.get("stopLossOrder", {}).get("price", 0)) or None)
        target = m.get("target") or (
            float(t.get("takeProfitOrder", {}).get("price", 0)) or None)
        open_dt = _parse_oanda_time(t.get("openTime", ""))
        close_dt = _parse_oanda_time(t.get("closeTime", ""))
        duration = int(round((close_dt - open_dt).total_seconds() / 60)) if open_dt and close_dt else None
        pip = 0.01 if "JPY" in t["instrument"] else 0.0001
        pips = round((exit_p - entry) / pip * (1 if direction == "LONG" else -1), 1)
        # Derive RR if stop is known
        planned_rr = None
        achieved_rr = None
        if stop and entry:
            risk = abs(entry - stop)
            if risk:
                if target:
                    planned_rr = round(abs(target - entry) / risk, 2)
                achieved_rr = round((exit_p - entry) / risk *
                                    (1 if direction == "LONG" else -1), 2)
        # Map close reason from Oanda's order links
        close_reason = "Manual"
        if t.get("stopLossOrder") and t["stopLossOrder"].get("state") == "FILLED":
            close_reason = "Stop Loss"
        elif t.get("takeProfitOrder") and t["takeProfitOrder"].get("state") == "FILLED":
            close_reason = "Take Profit"

        row = {
            "user_id": user_id,
            "broker": "oanda",
            "broker_trade_id": t["id"],
            "instrument": t["instrument"],
            "asset_type": "forex",
            "direction": direction,
            "units": abs(units),
            "contracts": 1,
            "entry_price": entry,
            "exit_price": exit_p,
            "stop_loss": stop,
            "take_profit": target,
            "realized_pl": realized,
            "pips": pips,
            "planned_rr": planned_rr,
            "achieved_rr": achieved_rr,
            "strategy": m["strategy"],
            "model": m["model"],
            "close_reason": close_reason,
            "won": realized > 0,
            "duration_mins": duration,
            "opened_at": t["openTime"],
            "closed_at": t["closeTime"],
        }
        row = {k: v for k, v in row.items() if v is not None}
        # Plain INSERT — orphans were already filtered out of `existing` so
        # duplicates aren't possible. Avoids needing a unique constraint
        # that the trades table doesn't have.
        req = urllib.request.Request(
            f"{sb_url}/rest/v1/trades",
            data=json.dumps(row).encode(),
            headers={**sb_headers, "Prefer": "return=minimal"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status < 300:
                    written += 1
                    print(f"  ✓ wrote {t['id']} {t['instrument']} {m['strategy']}/{m['model']}")
                else:
                    print(f"  ✗ {t['id']} status={r.status}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            print(f"  ✗ {t['id']} HTTP {e.code}: {body}")
            if written == 0:  # bail early on first error so we see it
                print(f"    payload: {json.dumps(row)[:400]}")
        except Exception as e:
            print(f"  ✗ {t['id']} error: {e}")

    print(f"\nDone. Wrote {written}/{len(matched)} matched orphans.")


if __name__ == "__main__":
    main()
