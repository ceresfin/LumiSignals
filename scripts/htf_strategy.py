"""HTF Supply/Demand Strategy — Python port of pinescripts/htf_strategy.pine.

This builds on htf_levels.py (which finds untouched supply/demand levels +
ADX trend across 8 TFs) and adds the signal layer:

  - Proximity check: is price within `zone_mult × ATR` of a level?
  - Duration scoring: how many higher-TF trends align with the level's side?
  - Signal generation: dSell / dBuy / hSell / hBuy / fSell / fBuy
  - Webhook payload builder (matches the Pine alert JSON shape)
  - Forex/crypto gate (matches Pine: skip trade alerts on those asset classes)

Three duration models, mirroring the Pine:
  Daily  — trades W/M supply + demand,  scored by W + M trend
  Hourly — trades D supply + demand,    scored by D + W trend
  5-min  — trades 4H supply + demand,   scored by 4H + D + 1H trend

Usage:
  POLYGON_API_KEY=xxx python scripts/htf_strategy.py SPY
  POLYGON_API_KEY=xxx python scripts/htf_strategy.py I:SPX --webhook-key foo
  POLYGON_API_KEY=xxx python scripts/htf_strategy.py SPY --json
  POLYGON_API_KEY=xxx python scripts/htf_strategy.py SPY --send-webhook https://...

Importable:
  from htf_strategy import scan, HTFSignal
  signals = scan("SPY", api_key="...", zone_mult=1.0, min_score=2)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from typing import Optional

# Allow running as a script or imported as a module
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from htf_levels import (  # noqa: E402
    TF_ORDER,
    TFLevels,
    fetch_and_compute,
)


# ============================================================================
# Strategy parameters (defaults match the Pine inputs)
# ============================================================================

DEFAULT_ADX_PERIOD = 14
DEFAULT_ZONE_MULT = 1.0    # how many ATRs counts as "near" a level
DEFAULT_MIN_SCORE = 2      # min confluence required to fire a signal
DEFAULT_ADX_THRESHOLD = 25 # what counts as "strong trend" in scoring


# ============================================================================
# Data model
# ============================================================================

@dataclass
class HTFSignal:
    """One triggered signal — buy/sell at a specific TF's level."""
    duration: str       # "daily" | "hourly" | "5min"
    direction: str      # "BUY" | "SELL"
    level_tf: str       # which TF's level price is sitting near
    level_price: float
    score: int
    max_score: int
    trends_summary: str  # e.g., "W:UP M:DOWN"

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# Proximity check — matches Pine's nearSupply / nearDemand
# ============================================================================

def _is_finite(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def near_supply(close: float, level: Optional[float], atr: float,
                zone_mult: float = DEFAULT_ZONE_MULT) -> bool:
    """True when close is within `zone_mult × atr` BELOW the supply level."""
    if not (_is_finite(level) and _is_finite(atr)):
        return False
    return (level - atr * zone_mult) <= close <= level


def near_demand(close: float, level: Optional[float], atr: float,
                zone_mult: float = DEFAULT_ZONE_MULT) -> bool:
    """True when close is within `zone_mult × atr` ABOVE the demand level."""
    if not (_is_finite(level) and _is_finite(atr)):
        return False
    return level <= close <= (level + atr * zone_mult)


# ============================================================================
# Scoring + signal evaluation
# ============================================================================

def _dir_to_int(direction: str) -> int:
    """UP → 1, DOWN → -1, SIDE → 0."""
    return {"UP": 1, "DOWN": -1}.get(direction, 0)


def _trends_summary(tfs: list[tuple[str, str]]) -> str:
    """Format like 'W:UP M:DOWN' from [('W', 'UP'), ('M', 'DOWN')]."""
    return " ".join(f"{tf}:{d}" for tf, d in tfs)


def evaluate_daily(levels: dict[str, TFLevels], close: float,
                   zone_mult: float, min_score: int,
                   adx_threshold: int = DEFAULT_ADX_THRESHOLD) -> Optional[HTFSignal]:
    """Daily-duration scoring: W and M trend, W+M ADX strength.

    Returns the best (highest score) qualifying signal between weekly and
    monthly side, or None if no signal triggers.
    """
    w = levels["W"]
    m = levels["M"]
    w_dir = _dir_to_int(w.direction)
    m_dir = _dir_to_int(m.direction)
    summary = _trends_summary([("W", w.direction), ("M", m.direction)])

    candidates: list[HTFSignal] = []

    # ─── SELL at weekly supply ───
    if near_supply(close, w.s1, w.atr, zone_mult) and w_dir == -1:
        score = (
            (1 if w_dir == -1 else 0)
            + (1 if m_dir == -1 else 0)
            + (1 if (w.adx >= adx_threshold or m.adx >= adx_threshold) else 0)
        )
        if score >= min_score and w.s1 is not None:
            candidates.append(HTFSignal("daily", "SELL", "W", w.s1, score, 3, summary))

    # ─── SELL at monthly supply ───
    if near_supply(close, m.s1, m.atr, zone_mult) and m_dir == -1:
        score = (
            (1 if m_dir == -1 else 0)
            + (1 if w_dir == -1 else 0)
            + (1 if m.adx >= adx_threshold else 0)
        )
        if score >= min_score and m.s1 is not None:
            candidates.append(HTFSignal("daily", "SELL", "M", m.s1, score, 3, summary))

    # ─── BUY at weekly demand ───
    if near_demand(close, w.d1, w.atr, zone_mult) and w_dir == 1:
        score = (
            (1 if w_dir == 1 else 0)
            + (1 if m_dir == 1 else 0)
            + (1 if (w.adx >= adx_threshold or m.adx >= adx_threshold) else 0)
        )
        if score >= min_score and w.d1 is not None:
            candidates.append(HTFSignal("daily", "BUY", "W", w.d1, score, 3, summary))

    # ─── BUY at monthly demand ───
    if near_demand(close, m.d1, m.atr, zone_mult) and m_dir == 1:
        score = (
            (1 if m_dir == 1 else 0)
            + (1 if w_dir == 1 else 0)
            + (1 if m.adx >= adx_threshold else 0)
        )
        if score >= min_score and m.d1 is not None:
            candidates.append(HTFSignal("daily", "BUY", "M", m.d1, score, 3, summary))

    if not candidates:
        return None
    # Prefer higher score; on tie, prefer monthly (matches Pine logic)
    return max(candidates, key=lambda s: (s.score, s.level_tf == "M"))


def evaluate_hourly(levels: dict[str, TFLevels], close: float,
                    zone_mult: float, min_score: int,
                    adx_threshold: int = DEFAULT_ADX_THRESHOLD) -> Optional[HTFSignal]:
    """Hourly-duration scoring at Daily levels, scored by D + W trend."""
    d = levels["D"]
    w = levels["W"]
    d_dir = _dir_to_int(d.direction)
    w_dir = _dir_to_int(w.direction)
    summary = _trends_summary([("D", d.direction), ("W", w.direction)])

    if near_supply(close, d.s1, d.atr, zone_mult) and d_dir == -1:
        score = (
            (1 if d_dir == -1 else 0)
            + (1 if w_dir == -1 else 0)
            + (1 if (d.adx >= adx_threshold or w.adx >= adx_threshold) else 0)
        )
        if score >= min_score and d.s1 is not None:
            return HTFSignal("hourly", "SELL", "D", d.s1, score, 3, summary)

    if near_demand(close, d.d1, d.atr, zone_mult) and d_dir == 1:
        score = (
            (1 if d_dir == 1 else 0)
            + (1 if w_dir == 1 else 0)
            + (1 if (d.adx >= adx_threshold or w.adx >= adx_threshold) else 0)
        )
        if score >= min_score and d.d1 is not None:
            return HTFSignal("hourly", "BUY", "D", d.d1, score, 3, summary)

    return None


def evaluate_5min(levels: dict[str, TFLevels], close: float,
                  zone_mult: float, min_score: int,
                  adx_threshold: int = DEFAULT_ADX_THRESHOLD) -> Optional[HTFSignal]:
    """5-min duration scoring at 4H levels, scored by 4H + D + 1H trend."""
    h4 = levels["4H"]
    d = levels["D"]
    h1 = levels["1H"]
    h4_dir = _dir_to_int(h4.direction)
    d_dir = _dir_to_int(d.direction)
    h1_dir = _dir_to_int(h1.direction)
    summary = _trends_summary([
        ("4H", h4.direction), ("D", d.direction), ("1H", h1.direction),
    ])

    if near_supply(close, h4.s1, h4.atr, zone_mult) and h4_dir == -1:
        score = (
            (1 if h4_dir == -1 else 0)
            + (1 if d_dir == -1 else 0)
            + (1 if h1_dir == -1 else 0)
            + (1 if (h4.adx >= adx_threshold or d.adx >= adx_threshold) else 0)
        )
        if score >= min_score and h4.s1 is not None:
            return HTFSignal("5min", "SELL", "4H", h4.s1, score, 4, summary)

    if near_demand(close, h4.d1, h4.atr, zone_mult) and h4_dir == 1:
        score = (
            (1 if h4_dir == 1 else 0)
            + (1 if d_dir == 1 else 0)
            + (1 if h1_dir == 1 else 0)
            + (1 if (h4.adx >= adx_threshold or d.adx >= adx_threshold) else 0)
        )
        if score >= min_score and h4.d1 is not None:
            return HTFSignal("5min", "BUY", "4H", h4.d1, score, 4, summary)

    return None


def evaluate_signals(levels: dict[str, TFLevels], close: float,
                     zone_mult: float = DEFAULT_ZONE_MULT,
                     min_score: int = DEFAULT_MIN_SCORE,
                     adx_threshold: int = DEFAULT_ADX_THRESHOLD) -> list[HTFSignal]:
    """Run all three duration evaluators and return any signals that triggered."""
    out: list[HTFSignal] = []
    for evaluator in (evaluate_daily, evaluate_hourly, evaluate_5min):
        sig = evaluator(levels, close, zone_mult, min_score, adx_threshold)
        if sig is not None:
            out.append(sig)
    return out


# ============================================================================
# Webhook payload (matches the Pine alert JSON shape)
# ============================================================================

def is_tradeable_ticker(ticker: str) -> bool:
    """Forex (C:) and crypto (X:) are gated out — they fail the server's
    Polygon equity-endpoint price lookup. Matches the Pine `tradeable` rule:
    syminfo.type != "forex" and != "crypto".
    """
    return not (ticker.startswith("C:") or ticker.startswith("X:"))


def build_webhook_payload(signal: HTFSignal, ticker: str, webhook_key: str,
                          trade_type: str = "stock",
                          spread_type: str = "both") -> dict:
    """Build the JSON dict the Pine alert sends to /api/webhook/tradingview."""
    fmt = lambda v: round(v, 4) if isinstance(v, float) else v
    return {
        "ticker": ticker,
        "direction": signal.direction,
        "strategy": "htf_supply_demand",
        "key": webhook_key,
        "type": trade_type,
        "spread_type": spread_type,
        "trade_duration": signal.duration,
        "score": signal.score,
        "level_price": fmt(signal.level_price),
        "level_tf": signal.level_tf,
        "htf_trends": signal.trends_summary,
        "msg": (
            f"HTF {signal.direction} {ticker} — {signal.level_tf} "
            f"{'S1' if signal.direction == 'SELL' else 'D1'}"
            f"{fmt(signal.level_price)} | {signal.trends_summary} | "
            f"Score {signal.score}/{signal.max_score}"
        ),
    }


# ============================================================================
# Top-level scan
# ============================================================================

def scan(ticker: str, api_key: Optional[str] = None,
         zone_mult: float = DEFAULT_ZONE_MULT,
         min_score: int = DEFAULT_MIN_SCORE,
         adx_period: int = DEFAULT_ADX_PERIOD,
         adx_threshold: int = DEFAULT_ADX_THRESHOLD) -> tuple[dict[str, TFLevels], list[HTFSignal], float]:
    """Fetch levels for `ticker`, evaluate signals, and return:
       (levels_by_tf, signals_list, current_close_price).

    The current close is taken from the 15M data (most recent intraday bar).
    """
    levels = fetch_and_compute(ticker, api_key=api_key, adx_period=adx_period)

    # Pull current close from the lowest-TF data that's present
    close: float = float("nan")
    for tf in ("15M", "30M", "1H", "4H", "D"):
        lvl = levels.get(tf)
        if lvl and _is_finite(lvl.atr):
            # Re-fetch the most recent bar from that TF to read its close.
            # (TFLevels itself doesn't carry close; we use Polygon directly.)
            from htf_levels import POLYGON_AGG, POLYGON_DAYS_BACK, _fetch_polygon_aggs
            multiplier, timespan = POLYGON_AGG[tf]
            df = _fetch_polygon_aggs(
                ticker, multiplier, timespan, POLYGON_DAYS_BACK[tf],
                api_key or os.environ.get("POLYGON_API_KEY") or os.environ.get("MASSIVE_API_KEY"),
            )
            if not df.empty:
                close = float(df["close"].iloc[-1])
                break

    signals = evaluate_signals(levels, close, zone_mult=zone_mult,
                               min_score=min_score, adx_threshold=adx_threshold)
    return levels, signals, close


# ============================================================================
# CLI
# ============================================================================

def _print_summary(ticker: str, levels: dict[str, TFLevels],
                   signals: list[HTFSignal], close: float) -> None:
    print(f"\nHTF Strategy — {ticker}  (close: {close:.4f})")
    print("=" * 76)
    # Compact level summary
    print(f"{'TF':<5} {'Trend':<5} {'ADX':>4}  {'S1':>10} {'D1':>10}")
    print("-" * 50)
    for tf in TF_ORDER:
        lvl = levels.get(tf)
        if lvl is None:
            continue
        s1 = f"{lvl.s1:.4f}" if _is_finite(lvl.s1) else "—"
        d1 = f"{lvl.d1:.4f}" if _is_finite(lvl.d1) else "—"
        adx = f"{lvl.adx:.0f}" if _is_finite(lvl.adx) else "—"
        print(f"{tf:<5} {lvl.direction:<5} {adx:>4}  {s1:>10} {d1:>10}")

    print()
    if not signals:
        print("Signal: No signal")
    else:
        print("Signal" + ("s" if len(signals) > 1 else "") + ":")
        for s in signals:
            print(
                f"  {s.duration.upper():<7} {s.direction} @ {s.level_tf} "
                f"{s.level_price:.4f}  | Score {s.score}/{s.max_score}  | {s.trends_summary}"
            )
    print()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the HTF supply/demand strategy on a single ticker.",
    )
    parser.add_argument(
        "ticker",
        help="Polygon ticker. Stocks: SPY/AAPL. Indices: I:SPX. Forex: C:EURUSD",
    )
    parser.add_argument("--zone-mult", type=float, default=DEFAULT_ZONE_MULT,
                        help=f"Proximity zone width as multiple of ATR (default {DEFAULT_ZONE_MULT})")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE,
                        help=f"Min score to trigger (default {DEFAULT_MIN_SCORE})")
    parser.add_argument("--webhook-key", default="lumisignals2026",
                        help="Webhook key to embed in payload")
    parser.add_argument("--api-key",
                        help="Polygon API key (otherwise POLYGON_API_KEY / MASSIVE_API_KEY env)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON (levels + signals + close)")
    parser.add_argument("--payloads", action="store_true",
                        help="Print the webhook payload(s) that would be sent")
    parser.add_argument("--send-webhook", metavar="URL",
                        help="POST each triggered signal's payload to this URL")
    args = parser.parse_args(argv)

    ticker = args.ticker.upper()

    try:
        levels, signals, close = scan(
            ticker, api_key=args.api_key,
            zone_mult=args.zone_mult, min_score=args.min_score,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    tradeable = is_tradeable_ticker(ticker)
    payloads = [
        build_webhook_payload(s, ticker, args.webhook_key)
        for s in signals
    ] if tradeable else []

    if args.json:
        print(json.dumps({
            "ticker": ticker,
            "close": close,
            "tradeable": tradeable,
            "levels": {tf: lvl.to_dict() for tf, lvl in levels.items()},
            "signals": [s.to_dict() for s in signals],
            "payloads": payloads,
        }, indent=2, default=str))
        return 0

    _print_summary(ticker, levels, signals, close)
    if not tradeable and signals:
        print(f"(Tradeable=False for {ticker} — webhook payloads suppressed; "
              f"this matches the Pine forex/crypto gate.)")

    if args.payloads and payloads:
        print("Webhook payloads:")
        for p in payloads:
            print("  " + json.dumps(p))

    if args.send_webhook and payloads:
        import requests  # imported here so the rest of the module has no hard dep
        for p in payloads:
            try:
                r = requests.post(args.send_webhook, json=p, timeout=15)
                print(f"  POST {args.send_webhook} → {r.status_code}")
            except Exception as e:
                print(f"  POST failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
