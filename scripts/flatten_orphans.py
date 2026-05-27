"""Flatten any IB position the bot doesn't recognize.

An "orphan" here is an IB holding that:
  - has no matching `ibkr:strat_pos:{ticker}:*` row in Redis, AND
  - has no live diary row (state in INTENT_OPEN / OPEN / INTENT_CLOSE)
        in Supabase `trade_state_current`.

These orphans cause the bot to refuse legitimate signals — e.g. 7 separate
SELL signals were skipped on 2026-05-22 morning with the message
"IB has opposing orphan (qty=+2). Fresh entry would close the orphan
rather than open a new position; manual-flat the orphan first."

Usage (run on lumi-prod):
    python3 -m scripts.flatten_orphans           # dry run — list only
    python3 -m scripts.flatten_orphans --execute # actually market-close

Each closed position is logged to /var/log/lumisignals_flatten.log and a
Telegram summary is sent if env is configured. Closes are MKT orders;
all stop / take-profit children attached to the same contract are
cancelled first so IB doesn't reject the close as overselling.

Safe to re-run. If nothing is orphan, it exits cleanly.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Optional

# Allow running from /opt/lumisignals/app on prod or repo root in dev.
sys.path.insert(0, os.environ.get("LUMISIGNALS_PATH", "/opt/lumisignals/app"))
sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("flatten_orphans")


def _connect_redis():
    try:
        import redis
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        return redis.Redis(host=host, port=port, decode_responses=True)
    except Exception as e:
        logger.error("Redis unavailable: %s", e)
        return None


def _has_strat_pos(rdb, ticker: str) -> bool:
    """True iff Redis has at least one ibkr:strat_pos:{ticker}:* key."""
    if rdb is None:
        return False
    try:
        return any(True for _ in rdb.scan_iter(f"ibkr:strat_pos:{ticker}:*"))
    except Exception as e:
        logger.warning("strat_pos scan failed for %s: %s", ticker, e)
        return False


def _diary_has_live_open(ticker: str) -> bool:
    """True iff Supabase trade_state_current has a live OPEN/INTENT for this ticker."""
    try:
        from lumisignals import diary
    except Exception as e:
        logger.warning("diary import failed: %s", e)
        return False
    if not diary._service_key():
        return False
    uid = diary._supabase_user_id()
    params = {
        "ticker": f"eq.{ticker}",
        "state": (
            f"in.({diary.State.INTENT_OPEN},"
            f"{diary.State.OPEN},"
            f"{diary.State.INTENT_CLOSE})"
        ),
        "select": "broker_trade_id,state",
        "limit": 1,
    }
    if uid:
        params["user_id"] = f"eq.{uid}"
    rows = diary._rest_request("GET", "trade_state_current", params=params)
    return bool(rows)


def _telegram(title: str, body: str) -> None:
    try:
        from lumisignals.supabase_client import send_telegram_message
        send_telegram_message(f"*{title}*\n{body}")
    except Exception as e:
        logger.debug("telegram suppressed: %s", e)


def _cancel_children(client, ticker: str) -> int:
    """Cancel any open SL/TP children for this ticker so the market-close
    is not rejected as overselling."""
    cancelled = 0
    try:
        open_orders = client.get_open_orders() or []
        for o in open_orders:
            if o.get("ticker") != ticker:
                continue
            if o.get("status") in ("Filled", "Cancelled"):
                continue
            ot = (o.get("orderType") or "").upper()
            if ot not in ("STP", "STOP", "STOP_LIMIT", "LMT", "LIMIT"):
                continue
            try:
                client.cancel_order(str(o.get("orderId")))
                cancelled += 1
                logger.info("Cancelled %s order %s on %s before close",
                            ot, o.get("orderId"), ticker)
            except Exception as e:
                logger.warning("Cancel %s failed: %s", o.get("orderId"), e)
    except Exception as e:
        logger.warning("Children cancel scan failed: %s", e)
    return cancelled


def find_orphans(client) -> list:
    """Return list of (ticker, qty, avg_cost, sec_type, conid) for each
    IB position with no Redis strat_pos and no live diary row."""
    rdb = _connect_redis()
    positions = client.get_positions() or []
    orphans = []
    for p in positions:
        try:
            qty = int(p.get("quantity") or p.get("position") or 0)
        except (TypeError, ValueError):
            continue
        if qty == 0:
            continue
        ticker = p.get("symbol") or p.get("ticker")
        if not ticker:
            continue
        if _has_strat_pos(rdb, ticker):
            continue
        if _diary_has_live_open(ticker):
            continue
        orphans.append({
            "ticker": ticker,
            "qty": qty,
            "avg_cost": p.get("avg_cost"),
            "sec_type": p.get("sec_type"),
            "conid": p.get("conid"),
            "raw": p,
        })
    return orphans


def flatten(client, orphans: list, dry_run: bool = True) -> int:
    """Close each orphan via market order. Returns count actually closed."""
    closed = 0
    for o in orphans:
        ticker = o["ticker"]
        qty = o["qty"]
        sec_type = o.get("sec_type", "")
        conid = o.get("conid")
        side = "SELL" if qty > 0 else "BUY"
        absqty = abs(qty)

        logger.info("ORPHAN %s %s %+d (sec=%s conid=%s avg_cost=%s)",
                    "DRY-RUN" if dry_run else "CLOSING",
                    ticker, qty, sec_type, conid, o.get("avg_cost"))

        if dry_run:
            continue

        # Cancel any leftover SL/TP children first.
        _cancel_children(client, ticker)
        time.sleep(1)

        # Build MKT close order.
        try:
            if sec_type == "FUT":
                payload = client.build_futures_order(
                    conid, side, absqty, "MKT", tif="GTC",
                )
            else:
                # Stocks / options — simpler single-leg payload.
                payload = {
                    "orders": [{
                        "conid": int(conid),
                        "orderType": "MKT",
                        "side": side,
                        "quantity": absqty,
                        "tif": "DAY",
                    }]
                }
            result = client.place_order(payload)
            order_id = ""
            if isinstance(result, list) and result:
                first = result[0] if isinstance(result[0], dict) else {}
                order_id = str(first.get("order_id", "") or "")
            elif isinstance(result, dict):
                order_id = str(result.get("order_id", "") or "")
            logger.info("Flatten %s: placed %s %dx — order_id=%s",
                        ticker, side, absqty, order_id or "(no id returned)")
            closed += 1
        except Exception as e:
            logger.error("Flatten %s failed: %s", ticker, e)
    return closed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually place the close orders. Without this, dry-run only.",
    )
    parser.add_argument(
        "--only", action="append", default=[],
        help="Limit to these tickers (repeatable). Default: all orphans.",
    )
    parser.add_argument(
        "--cpapi-url", default=os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api"),
    )
    args = parser.parse_args()

    from lumisignals.ibkr_cpapi import CPAPIClient
    client = CPAPIClient(base_url=args.cpapi_url)
    try:
        client.ensure_session()
    except Exception as e:
        logger.error("CPAPI not reachable (%s) — is IBeam up?", e)
        return 2

    orphans = find_orphans(client)
    if args.only:
        wanted = {t.upper() for t in args.only}
        orphans = [o for o in orphans if o["ticker"].upper() in wanted]
        logger.info("Filtered to --only %s: %d orphan(s) match",
                    sorted(wanted), len(orphans))
    if not orphans:
        logger.info("No orphans found. IB positions all tracked by bot.")
        return 0

    summary_lines = [f"Found {len(orphans)} orphan(s):"]
    for o in orphans:
        summary_lines.append(
            f"  • {o['ticker']} qty={o['qty']:+d} avg_cost={o.get('avg_cost')}"
        )
    summary = "\n".join(summary_lines)
    logger.info(summary)

    if not args.execute:
        logger.info("Dry run — pass --execute to actually flatten.")
        return 0

    closed = flatten(client, orphans, dry_run=False)
    msg = f"Flattened {closed} of {len(orphans)} orphan position(s)."
    logger.info(msg)
    _telegram("🧹 Orphan flatten complete", f"{summary}\n\n{msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
