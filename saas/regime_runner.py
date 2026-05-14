"""Weekly regime recompute job.

Runs at the Sunday 17:00 ET FX day rollover (or on-demand) and writes
per-pair eligibility to Redis under `regime:fx_4h:{PAIR}`.  Compares to
the previous state and fires a single Telegram message summarizing any
flips so the user can see when the active universe changes.

Designed to be cheap and idempotent — re-running mid-week just rewrites
the same numbers (the lookback window only advances on actual time).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis as _redis

from lumisignals.regime import (
    compute_fingerprint, week_anchor, RegimeFingerprint, Bar,
    REGIME_LOOKBACK_DAYS,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# Pairs the FX 4H strategy considers.  Keep in sync with the backtester's
# PAIRS list — single source of truth could live in regime.py later when
# we have more than one regime-gated strategy.
# EUR_USD and GBP_USD excluded — both lost money in the 24mo backtest
# (EUR_USD -$5K, GBP_USD -$31K) even with the regime filter on, so
# they're not in the FX 4H universe.  Kept here as documentation:
# if either pair gets re-added later, the regime runner here AND
# DEFAULT_PAIRS in lumisignals/fx_trend_4h.py must be updated together.
FX_4H_PAIRS = ["USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD"]
STRATEGY_KEY = "fx_4h"
REDIS_KEY_PATTERN = "regime:{strategy}:{pair}"
HISTORY_MAX = 26   # ~half a year of weekly entries kept per pair


def _redis_client():
    return _redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )


def _load_oanda_creds():
    """Same path the backtester uses — env first, then bot user row."""
    api_key = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
    if not api_key:
        try:
            import psycopg2
            db_url = os.environ.get(
                "DATABASE_URL",
                "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db")
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT oanda_api_key, oanda_account_id, oanda_environment "
                        "FROM users WHERE bot_active=true "
                        "AND oanda_api_key IS NOT NULL ORDER BY id LIMIT 1")
                    row = cur.fetchone()
                    if row:
                        api_key, account_id, environment = \
                            row[0], row[1], row[2] or "practice"
        except Exception as e:
            logger.error("DB creds load failed: %s", e)
    return api_key, account_id, environment


def _fetch_window_bars(client, pair: str, days: int) -> list[Bar]:
    """Pull H4 candles for the last `days` days via Oanda.  Returns
    `regime.Bar`-shaped objects so the same fingerprint code works."""
    from saas.backtest_fx_4h import fetch_h4_range
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    raw = fetch_h4_range(client, pair, start, end)
    # backtest_fx_4h.Bar already satisfies our shape — duck typing.
    return raw


def _previous_state(rdb, pair: str) -> dict:
    """Last state we stored for this pair, or empty dict if first run."""
    raw = rdb.get(REDIS_KEY_PATTERN.format(strategy=STRATEGY_KEY, pair=pair))
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _store_state(rdb, pair: str, state: dict):
    rdb.set(REDIS_KEY_PATTERN.format(strategy=STRATEGY_KEY, pair=pair),
            json.dumps(state))


def _send_flip_summary(flips: list[tuple]):
    """One Telegram message per recompute, listing every flip.  Avoids
    notification spam — at most one message per Sunday."""
    if not flips:
        return
    try:
        from lumisignals.supabase_client import send_telegram_message
        lines = ["📊 *FX 4H regime change*", ""]
        for pair, became_eligible, atr_pct, drift_pips, reason in flips:
            arrow = "🟢 ELIGIBLE" if became_eligible else "🔴 PAUSED"
            lines.append(f"`{pair}` → {arrow}")
            lines.append(f"  ATR {atr_pct:.2f}% · drift {drift_pips:+.0f}p")
            if not became_eligible and reason:
                lines.append(f"  Reason: {reason}")
        send_telegram_message("\n".join(lines))
    except Exception as e:
        logger.warning("Telegram flip notify failed: %s", e)


def recompute(strategy: str = STRATEGY_KEY) -> dict:
    """Recompute regime for every pair in the strategy's universe and
    return a summary dict that's also returned to whoever called us."""
    from lumisignals.oanda_client import OandaClient
    api_key, account_id, environment = _load_oanda_creds()
    if not api_key:
        logger.error("No Oanda creds — cannot recompute regime.")
        return {"error": "no_credentials"}
    client = OandaClient(account_id=account_id, api_key=api_key,
                         environment=environment)

    rdb = _redis_client()
    anchor = week_anchor(datetime.now(timezone.utc))
    flips: list[tuple] = []
    summary = {"strategy": strategy, "anchor": anchor.isoformat(), "pairs": {}}

    for pair in FX_4H_PAIRS:
        logger.info("regime[%s] fetching %d days of H4 for %s",
                    strategy, REGIME_LOOKBACK_DAYS, pair)
        try:
            bars = _fetch_window_bars(client, pair, REGIME_LOOKBACK_DAYS + 5)
        except Exception as e:
            logger.error("fetch failed for %s: %s", pair, e)
            continue
        if not bars:
            logger.warning("no bars for %s", pair)
            continue

        # Trim to strictly-before-the-anchor (no look-ahead, even though
        # the bar is already closed)
        window = [b for b in bars if b.ts < anchor]
        fp: RegimeFingerprint = compute_fingerprint(window, pair)
        logger.info("regime[%s] %s: eligible=%s atr=%.2f%% drift=%+.0fp (%s)",
                    strategy, pair, fp.eligible, fp.atr_pct, fp.drift_pips,
                    fp.fail_reason or "ok")

        prev = _previous_state(rdb, pair)
        prev_eligible = bool(prev.get("eligible"))
        history = list(prev.get("history") or [])

        # Was this a flip? (state_change relative to last stored value)
        flipped = (not prev) or (prev_eligible != fp.eligible)
        since = prev.get("since") if not flipped else anchor.isoformat()

        # Append this week to history
        history.append({
            "ts": anchor.isoformat(),
            "eligible": fp.eligible,
            "atr_pct": round(fp.atr_pct, 4),
            "drift_pips": round(fp.drift_pips, 1),
            "fail_reason": fp.fail_reason,
        })
        # Trim history to last N entries
        if len(history) > HISTORY_MAX:
            history = history[-HISTORY_MAX:]

        state = {
            "strategy": strategy,
            "pair": pair,
            "eligible": fp.eligible,
            "atr_pct": round(fp.atr_pct, 4),
            "drift_pips": round(fp.drift_pips, 1),
            "fail_reason": fp.fail_reason,
            "since": since,
            "anchor": anchor.isoformat(),
            "history": history,
        }
        _store_state(rdb, pair, state)
        summary["pairs"][pair] = {"eligible": fp.eligible,
                                  "atr_pct": fp.atr_pct,
                                  "drift_pips": fp.drift_pips,
                                  "flipped": flipped}

        if flipped and prev:   # don't notify on first-ever seed
            flips.append((pair, fp.eligible, fp.atr_pct,
                          fp.drift_pips, fp.fail_reason))

    _send_flip_summary(flips)
    return summary


if __name__ == "__main__":
    recompute()
