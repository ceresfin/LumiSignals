"""FX Intraday 4H Trend — Backtester v1.

Validates the strategy spec we locked in:

  Universe: 7 majors (EUR_USD, USD_JPY, GBP_USD, USD_CHF, AUD_USD, USD_CAD,
                      NZD_USD)
  Execute:  4H bar close, aligned to NY session (anchored at 17:00 ET)
  Filters:  4H EMA(20) AND weekly VWAP AND monthly VWAP must all agree
  Trigger:  green/red overwhelm pattern (same detect_overwhelm() as live)
  Stop:     1.5 × ATR(14) on 4H, capped at $1000 risk per trade
  Exit:     first of {stop hit, +2R take-profit, trend invalidation, Fri 12pm ET}
  Sizing:   units = $1000 / (stop_pips × pip_$_per_unit)
  Concurrency: max 2 simultaneous positions across the universe

Conservative simulation choices for v1:
  - If both stop and TP fell within the same bar, assume stop fills first
    (worst-case attribution — keeps us honest)
  - No three-step exit yet (1R-BE, 2R-50%-off, ATR-trail).  Add in v2 if v1
    shows edge.
  - No news blackout.  Major-event days will show up as outliers in trade
    audit if they matter.
  - Trend invalidation = next 4H bar closes back below EMA20 (long) /
    above EMA20 (short).  Checked at bar close, not intra-bar.

Run:  python -m saas.backtest_fx_4h --start 2024-05-01 --end 2026-05-01
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

# Allow running as a script from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumisignals.oanda_client import OandaClient
from lumisignals.overwhelm_detector import detect_overwhelm, detect_vwap_cross

# ─── Spec constants ────────────────────────────────────────────────────────
PAIRS = ["EUR_USD", "USD_JPY", "GBP_USD", "USD_CHF",
         "USD_CAD", "NZD_USD"]
# AUD_USD removed in v3 — consistently the worst-performing pair across
# both exit models (-$22K v1, -$25K v2).  Risk-on/off behavior doesn't
# pair well with the trend-momentum filter stack.
GRANULARITY = "H4"
EMA_PERIOD = 20
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
RR_TARGET = 2.0
RISK_PER_TRADE = 1000.0          # dollars
MAX_CONCURRENT = 2
WEEK_ANCHOR_HOUR_ET = 17         # Sunday 5 PM ET
MONTH_ANCHOR_HOUR_ET = 17        # First-of-month 5 PM ET
NY_TZ_OFFSET = -4                # EDT; flips to -5 in winter but H4 alignment
                                  # already lives on the Oanda side so this is
                                  # only used for week/month bucketing.
FRIDAY_CUTOFF_HOUR_ET = 12       # No new entries Friday after noon ET

# ─── Regime filter (v4) ────────────────────────────────────────────────────
# Pair must match the "USD_CAD profile" we identified in regime analysis:
# low volatility + range-bound (not trending hard).  Recomputed weekly
# at each Sunday 17:00 ET boundary using the prior 90 days of data.
REGIME_ENABLED = True
REGIME_LOOKBACK_DAYS = 90
REGIME_MAX_ATR_PCT = 0.30        # ATR / price ratio %
REGIME_MAX_DRIFT_PIPS = 500      # Abs net drift over 90 days


# ─── Data structures ───────────────────────────────────────────────────────
@dataclass
class Bar:
    """A 4H candle, parsed from Oanda's response."""
    ts: datetime           # UTC, candle close time
    o: float
    h: float
    l: float
    c: float
    volume: int

    def to_ohlc_dict(self) -> dict:
        """Shape detect_overwhelm() expects."""
        return {"open": self.o, "high": self.h, "low": self.l, "close": self.c}


@dataclass
class Trade:
    pair: str
    direction: str          # "BUY" or "SELL"
    entry_ts: datetime
    entry_price: float
    stop_price: float
    target_price: float
    units: int
    stop_distance_pips: float
    pip_value_usd: float    # $ per pip per single unit (e.g. 0.0001 for non-JPY)
    pip_dollars_per_unit: float
    # filled at exit:
    exit_ts: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl_dollars: float = 0.0
    pnl_pips: float = 0.0
    bars_held: int = 0


# ─── Pip math ──────────────────────────────────────────────────────────────
def pip_factor(pair: str) -> float:
    """Returns 0.01 for JPY pairs, 0.0001 otherwise.  One pip = this in price."""
    return 0.01 if "JPY" in pair else 0.0001


def pip_dollars_per_unit(pair: str, price: float) -> float:
    """$ per pip per 1 unit of base currency.

    For *_USD pairs:        pip_factor (USD is quote currency).
    For USD_* pairs (e.g. USD_JPY, USD_CAD, USD_CHF): pip_factor / price.
    Cross pairs we don't trade in the universe, so this covers all 7.
    """
    quote = pair.split("_")[1]
    pf = pip_factor(pair)
    if quote == "USD":
        return pf                       # e.g. EUR_USD: 1 pip on 1 unit = $0.0001
    # USD is base.  $/pip = pf / quote-price.
    return pf / price if price else pf


def position_size_units(risk_dollars: float, stop_pips: float,
                         pip_dollar_per_unit: float) -> int:
    """units = risk / (stop_pips × $/pip/unit).  Rounded to whole units."""
    if stop_pips <= 0 or pip_dollar_per_unit <= 0:
        return 0
    return int(risk_dollars / (stop_pips * pip_dollar_per_unit))


# ─── Anchors ───────────────────────────────────────────────────────────────
def to_et(ts: datetime) -> datetime:
    """Approximate NY time using a fixed EDT offset.  We're bucketing weeks
    and months, not pricing trades, so DST drift is acceptable."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone(timedelta(hours=NY_TZ_OFFSET)))


def week_anchor(ts: datetime) -> datetime:
    """Most recent Sunday 17:00 ET on or before ts."""
    et = to_et(ts)
    # Sunday = 6 in Python's weekday().  Roll back to Sunday.
    days_back = (et.weekday() + 1) % 7   # Mon=0→1, Tue=1→2, ..., Sun=6→0
    sunday = et - timedelta(days=days_back)
    anchor = sunday.replace(hour=WEEK_ANCHOR_HOUR_ET, minute=0,
                             second=0, microsecond=0)
    # If we landed AT Sunday but before 17:00 ET, use previous Sunday
    if anchor > et:
        anchor -= timedelta(days=7)
    return anchor


def month_anchor(ts: datetime) -> datetime:
    """First 17:00 ET on or after the 1st of the current month, going back if
    we're earlier than 1st-of-month 17:00 ET."""
    et = to_et(ts)
    candidate = et.replace(day=1, hour=MONTH_ANCHOR_HOUR_ET,
                            minute=0, second=0, microsecond=0)
    if candidate > et:
        # Roll to previous month's 1st 17:00
        prev_month_last = et.replace(day=1) - timedelta(days=1)
        candidate = prev_month_last.replace(day=1, hour=MONTH_ANCHOR_HOUR_ET,
                                             minute=0, second=0, microsecond=0)
    return candidate


# ─── Rolling indicators ────────────────────────────────────────────────────
def rolling_ema(series: list[float], period: int) -> list[Optional[float]]:
    """Standard EMA: seeded with the SMA of first `period`, alpha=2/(N+1)."""
    out: list[Optional[float]] = []
    if len(series) < period:
        return [None] * len(series)
    sma = sum(series[:period]) / period
    out = [None] * (period - 1) + [sma]
    alpha = 2.0 / (period + 1)
    ema = sma
    for v in series[period:]:
        ema = alpha * v + (1 - alpha) * ema
        out.append(ema)
    return out


def rolling_atr(bars: list[Bar], period: int) -> list[Optional[float]]:
    """Wilder ATR(N). TR = max(high-low, |high-prev_close|, |low-prev_close|)."""
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b.h - b.l)
            continue
        prev_c = bars[i - 1].c
        trs.append(max(b.h - b.l, abs(b.h - prev_c), abs(b.l - prev_c)))
    out: list[Optional[float]] = [None] * len(bars)
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period - 1] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def anchored_vwap_series(bars: list[Bar],
                          anchor_fn) -> list[Optional[float]]:
    """For each bar, return the running VWAP since its anchor (week or month).
    Resets when the anchor changes."""
    out: list[Optional[float]] = []
    current_anchor: Optional[datetime] = None
    num = 0.0
    den = 0.0
    for b in bars:
        anchor = anchor_fn(b.ts)
        if current_anchor is None or anchor != current_anchor:
            current_anchor = anchor
            num = 0.0
            den = 0.0
        vol = max(b.volume, 1)
        hlc3 = (b.h + b.l + b.c) / 3
        num += hlc3 * vol
        den += vol
        out.append(num / den if den > 0 else None)
    return out


# ─── Oanda historical fetch ────────────────────────────────────────────────
def fetch_h4_range(client: OandaClient, instrument: str,
                    start: datetime, end: datetime) -> list[Bar]:
    """Pull H4 candles between [start, end].  Oanda caps at 5000 per request;
    24 months of H4 is ~4,320 bars so usually one call covers it."""
    # Use raw _request to access from/to params (the cached helper doesn't
    # expose those).  Aligned to NY so the 4H buckets land on NY session
    # rollover.
    out: list[Bar] = []
    cursor = start
    # Force RFC3339 timestamps in the response. Default for this account
    # was UNIX (e.g. "1777611600.000000000") which we'd have to handle
    # separately; RFC3339 is what every other path expects.
    client.session.headers["Accept-Datetime-Format"] = "RFC3339"
    while cursor < end:
        page_end = min(end, cursor + timedelta(days=800))  # ~4800 H4 bars
        params = (
            f"granularity={GRANULARITY}&price=M"
            f"&from={cursor.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&to={page_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&alignmentTimezone=America/New_York"
            f"&dailyAlignment=17"          # NY 5 PM session anchor
        )
        url = f"/v3/instruments/{instrument}/candles?{params}"
        resp = client._request("GET", url)
        candles = resp.get("candles", []) if isinstance(resp, dict) else []
        page_last_ts: Optional[datetime] = None
        for c in candles:
            if not c.get("complete", True):
                continue
            mid = c.get("mid", {})
            try:
                # Oanda returns nanosecond-precision timestamps like
                # "2024-05-12T21:00:00.000000000Z" which fromisoformat
                # can't always parse cleanly.  Truncate fractional secs
                # to microseconds (6 digits) which all Python versions
                # accept.
                ts_raw = c.get("time", "").replace("Z", "")
                if "." in ts_raw:
                    base, frac = ts_raw.split(".", 1)
                    ts_raw = f"{base}.{frac[:6]}"
                ts = datetime.fromisoformat(ts_raw).replace(tzinfo=timezone.utc)
                out.append(Bar(
                    ts=ts,
                    o=float(mid.get("o", 0)),
                    h=float(mid.get("h", 0)),
                    l=float(mid.get("l", 0)),
                    c=float(mid.get("c", 0)),
                    volume=int(c.get("volume", 0)),
                ))
                page_last_ts = ts
            except Exception as e:
                # Surface parse errors so we don't silently lose bars
                print(f"WARN parse: {c.get('time', '?')}: {e}", file=sys.stderr)
                continue
        # Advance the cursor based on THIS PAGE's last bar (not the
        # cumulative list, which would stick forever on empty pages and
        # spin a $1000 cloud bill).  If the page was empty, jump to
        # page_end so we make forward progress.
        if page_last_ts is not None:
            cursor = page_last_ts + timedelta(hours=4)
        else:
            cursor = page_end + timedelta(seconds=1)
    return out


# ─── The simulator ─────────────────────────────────────────────────────────
@dataclass
class FilterAudit:
    """Why are we rejecting entries?  Helps tune the strategy."""
    overwhelm_no_signal: int = 0
    ema_disagree: int = 0
    weekly_vwap_disagree: int = 0
    monthly_vwap_disagree: int = 0
    body_filter_rejected: int = 0
    indicator_warmup: int = 0
    concurrency_cap: int = 0
    cutoff_friday: int = 0
    regime_paused: int = 0


def compute_regime_states(bars: list[Bar], pair: str
                           ) -> list[tuple[datetime, bool, float, float]]:
    """Walk forward in weekly steps, computing the pair's regime fingerprint
    each Sunday 17:00 ET from the prior 90 days of bars.  Returns a list of
    (effective_from_ts, is_eligible, atr_pct, drift_pips) tuples; the
    simulator picks the latest entry whose effective_from <= bar.ts.

    No look-ahead: only bars strictly before the anchor are used.
    """
    if not bars:
        return []
    pf = pip_factor(pair)
    out: list[tuple[datetime, bool, float, float]] = []
    # Walk in 4H steps but only emit on week boundaries (Sun 17:00 ET).
    last_anchor: Optional[datetime] = None
    for b in bars:
        anchor = week_anchor(b.ts)
        if anchor == last_anchor:
            continue
        last_anchor = anchor
        # Bars in the prior 90 days strictly before this week's anchor.
        cutoff = b.ts - timedelta(days=REGIME_LOOKBACK_DAYS)
        window = [x for x in bars if cutoff <= x.ts < b.ts]
        if len(window) < 50:
            continue
        # ATR(14) over the window
        atrs = rolling_atr(window, ATR_PERIOD)
        valid = [(window[i].c, a) for i, a in enumerate(atrs) if a is not None]
        if not valid:
            continue
        atr_pct = sum(a / c for c, a in valid) / len(valid) * 100
        drift_pips = (window[-1].c - window[0].c) / pf
        eligible = (atr_pct < REGIME_MAX_ATR_PCT and
                    abs(drift_pips) < REGIME_MAX_DRIFT_PIPS)
        out.append((anchor, eligible, atr_pct, drift_pips))
    return out


def is_eligible_at(states: list[tuple[datetime, bool, float, float]],
                    ts: datetime) -> bool:
    """Lookup the most-recent regime state at-or-before ts."""
    if not states:
        return False
    current = False
    for state_ts, eligible, _, _ in states:
        if state_ts <= ts:
            current = eligible
        else:
            break
    return current


def simulate_pair(pair: str, bars: list[Bar],
                   open_trades_ref: list[Trade],
                   audit: FilterAudit) -> tuple[list[Trade], list[tuple]]:
    """Walk forward through `bars`, generating trades for this pair.
    `open_trades_ref` is the shared concurrency list (mutated).

    Returns (completed_trades, regime_state_history) where state_history
    is the per-week (anchor_ts, eligible, atr_pct, drift_pips) tuples
    used to gate entries.  The history is surfaced for reporting.
    """
    if len(bars) < 30:
        return [], []

    closes = [b.c for b in bars]
    ema = rolling_ema(closes, EMA_PERIOD)
    atr = rolling_atr(bars, ATR_PERIOD)
    vwap_w = anchored_vwap_series(bars, week_anchor)
    vwap_m = anchored_vwap_series(bars, month_anchor)
    regime_states = compute_regime_states(bars, pair) if REGIME_ENABLED else []

    completed: list[Trade] = []
    open_trade: Optional[Trade] = None

    for i, bar in enumerate(bars):
        # ── Manage open position first (exit check) ──
        if open_trade is not None and open_trade.pair == pair:
            t = open_trade
            t.bars_held += 1

            # Backstop hit at any point inside the bar — conservative
            # attribution (stop fills if both stop and a reversal happened
            # in the same bar).
            hit_stop = (t.direction == "BUY" and bar.l <= t.stop_price) or \
                        (t.direction == "SELL" and bar.h >= t.stop_price)

            # Minimum-reward gate (v3): behavioral exits (overwhelm /
            # VWAP cross / EMA cross) only fire after the trade has
            # moved +1R in our favor.  Below that floor, only the
            # backstop stop can close.  Without this, 4H reversals fire
            # mid-trend and clip winners that would otherwise reach
            # meaningful targets — that's why v2 underperformed v1.
            stop_dist = abs(t.entry_price - t.stop_price)
            if t.direction == "BUY":
                progress = bar.c - t.entry_price
            else:
                progress = t.entry_price - bar.c
            past_1r = stop_dist > 0 and progress >= stop_dist

            # 2n20-style exit: opposite-color overwhelm pattern OR
            # weekly-VWAP cross OR EMA20 cross.  All evaluated at the
            # current bar's close, but only allowed once past +1R.
            window = [b.to_ohlc_dict() for b in bars[max(0, i - 11):i + 1]]
            ex_green, ex_red = detect_overwhelm(window)
            opposite_overwhelm = (t.direction == "BUY" and ex_red) or \
                                  (t.direction == "SELL" and ex_green)

            crossed_below_w = crossed_above_w = False
            if vwap_w[i] is not None and i > 0:
                two_bar = [{"close": bars[i - 1].c}, {"close": bar.c}]
                crossed_below_w, crossed_above_w = detect_vwap_cross(two_bar, vwap_w[i])
            vwap_exit = (t.direction == "BUY" and crossed_below_w) or \
                         (t.direction == "SELL" and crossed_above_w)

            # EMA20 strict cross: prior bar on one side, current on the
            # other. Avoids the "hovering at EMA" noise that triggered
            # invalidation on every wiggle in v1.
            ema_cross_exit = False
            if ema[i] is not None and i > 0 and ema[i - 1] is not None:
                prev_above = bars[i - 1].c > ema[i - 1]
                prev_below = bars[i - 1].c < ema[i - 1]
                curr_above = bar.c > ema[i]
                curr_below = bar.c < ema[i]
                if t.direction == "BUY" and prev_above and curr_below:
                    ema_cross_exit = True
                elif t.direction == "SELL" and prev_below and curr_above:
                    ema_cross_exit = True

            # Friday-after-noon ET hard close (carryover safety)
            et = to_et(bar.ts)
            friday_close = (et.weekday() == 4 and et.hour >= 16)

            exit_now = False
            if hit_stop:
                t.exit_price = t.stop_price
                t.exit_reason = "STOP"
                exit_now = True
            elif past_1r and opposite_overwhelm:
                t.exit_price = bar.c
                t.exit_reason = "OPPOSITE_OVERWHELM"
                exit_now = True
            elif past_1r and vwap_exit:
                t.exit_price = bar.c
                t.exit_reason = "VWAP_CROSS"
                exit_now = True
            elif past_1r and ema_cross_exit:
                t.exit_price = bar.c
                t.exit_reason = "EMA_CROSS"
                exit_now = True
            elif friday_close:
                t.exit_price = bar.c
                t.exit_reason = "WEEKEND_FLAT"
                exit_now = True

            if exit_now:
                t.exit_ts = bar.ts
                price_move = (t.exit_price - t.entry_price) \
                              if t.direction == "BUY" \
                              else (t.entry_price - t.exit_price)
                t.pnl_pips = price_move / pip_factor(pair)
                t.pnl_dollars = price_move * t.units
                # Adjust for USD-quote pairs: PnL already in USD.
                # For USD_* (quote not USD) the move is in quote currency.
                quote = pair.split("_")[1]
                if quote != "USD":
                    # Convert quote-currency P&L to USD at the exit price.
                    t.pnl_dollars = t.pnl_dollars / t.exit_price
                completed.append(t)
                open_trades_ref.remove(t)
                open_trade = None

        # ── Entry check (only if flat on this pair) ──
        if open_trade is not None:
            continue
        if i < max(EMA_PERIOD + 5, ATR_PERIOD + 5, 12):
            audit.indicator_warmup += 1
            continue
        if ema[i] is None or atr[i] is None or vwap_w[i] is None or vwap_m[i] is None:
            audit.indicator_warmup += 1
            continue
        if len(open_trades_ref) >= MAX_CONCURRENT:
            audit.concurrency_cap += 1
            continue
        et = to_et(bar.ts)
        if et.weekday() == 4 and et.hour >= FRIDAY_CUTOFF_HOUR_ET:
            audit.cutoff_friday += 1
            continue
        # Regime gate — pair must be in the eligible set this week
        if REGIME_ENABLED and not is_eligible_at(regime_states, bar.ts):
            audit.regime_paused += 1
            continue

        # Overwhelm pattern on the current bar (uses last 12 bars)
        window = [b.to_ohlc_dict() for b in bars[max(0, i - 11):i + 1]]
        green, red = detect_overwhelm(window)

        if not green and not red:
            audit.overwhelm_no_signal += 1
            continue

        # Apply trend filters
        if green:
            checks_ok = True
            if not (bar.c > ema[i]):
                audit.ema_disagree += 1; checks_ok = False
            elif not (bar.c > vwap_w[i]):
                audit.weekly_vwap_disagree += 1; checks_ok = False
            elif not (bar.c > vwap_m[i]):
                audit.monthly_vwap_disagree += 1; checks_ok = False
            if not checks_ok:
                continue
            direction = "BUY"
        else:  # red
            checks_ok = True
            if not (bar.c < ema[i]):
                audit.ema_disagree += 1; checks_ok = False
            elif not (bar.c < vwap_w[i]):
                audit.weekly_vwap_disagree += 1; checks_ok = False
            elif not (bar.c < vwap_m[i]):
                audit.monthly_vwap_disagree += 1; checks_ok = False
            if not checks_ok:
                continue
            direction = "SELL"

        # Size the position
        stop_distance_price = ATR_STOP_MULT * atr[i]
        stop_distance_pips = stop_distance_price / pip_factor(pair)
        pdu = pip_dollars_per_unit(pair, bar.c)
        units = position_size_units(RISK_PER_TRADE, stop_distance_pips, pdu)
        if units <= 0:
            continue

        if direction == "BUY":
            stop = bar.c - stop_distance_price
        else:
            stop = bar.c + stop_distance_price

        # No fixed take-profit — 2n20-style exits handle the upside via
        # opposite overwhelm / VWAP cross.  Target_price kept on the
        # struct as 0 so the CSV schema doesn't change.
        open_trade = Trade(
            pair=pair, direction=direction, entry_ts=bar.ts,
            entry_price=bar.c, stop_price=stop, target_price=0.0,
            units=units, stop_distance_pips=stop_distance_pips,
            pip_value_usd=pip_factor(pair),
            pip_dollars_per_unit=pdu,
        )
        open_trades_ref.append(open_trade)

    # End of bars — flatten anything still open at last close
    if open_trade is not None:
        t = open_trade
        t.exit_ts = bars[-1].ts
        t.exit_price = bars[-1].c
        t.exit_reason = "END_OF_DATA"
        price_move = (t.exit_price - t.entry_price) \
                      if t.direction == "BUY" \
                      else (t.entry_price - t.exit_price)
        t.pnl_pips = price_move / pip_factor(pair)
        t.pnl_dollars = price_move * t.units
        quote = pair.split("_")[1]
        if quote != "USD":
            t.pnl_dollars = t.pnl_dollars / t.exit_price
        completed.append(t)
        open_trades_ref.remove(t)

    return completed, regime_states


# ─── Reporting ─────────────────────────────────────────────────────────────
def print_report(all_trades: dict[str, list[Trade]], audit: FilterAudit,
                  start: datetime, end: datetime, out_csv: str):
    """Print per-pair stats + aggregate, dump trades CSV."""
    print()
    print("=" * 76)
    print(f"FX 4H Intraday backtest — {start.date()} to {end.date()}")
    print("=" * 76)
    print(f"{'PAIR':9} {'TRADES':>7} {'WINS':>6} {'WIN%':>6} "
          f"{'AVG R':>7} {'NET $':>10} {'MAX DD':>10}")

    grand_trades = 0
    grand_wins = 0
    grand_pnl = 0.0
    grand_equity_curve: list[tuple[datetime, float]] = []

    for pair in PAIRS:
        ts = all_trades.get(pair, [])
        if not ts:
            print(f"{pair:9} {'0':>7} {'-':>6} {'-':>6} {'-':>7} {'-':>10} {'-':>10}")
            continue
        wins = sum(1 for t in ts if t.pnl_dollars > 0)
        win_pct = wins / len(ts) * 100
        avg_r = sum(t.pnl_dollars for t in ts) / len(ts) / RISK_PER_TRADE
        net = sum(t.pnl_dollars for t in ts)
        # Running max-DD for this pair
        peak = 0.0
        eq = 0.0
        max_dd = 0.0
        for t in sorted(ts, key=lambda x: x.exit_ts or x.entry_ts):
            eq += t.pnl_dollars
            peak = max(peak, eq)
            max_dd = min(max_dd, eq - peak)
        print(f"{pair:9} {len(ts):>7d} {wins:>6d} {win_pct:>5.1f}% "
              f"{avg_r:>+6.2f}R {net:>+9.2f} {max_dd:>+9.2f}")
        grand_trades += len(ts)
        grand_wins += wins
        grand_pnl += net

    print("-" * 76)
    grand_winpct = (grand_wins / grand_trades * 100) if grand_trades else 0
    print(f"{'TOTAL':9} {grand_trades:>7d} {grand_wins:>6d} {grand_winpct:>5.1f}% "
          f"{'':>7} {grand_pnl:>+9.2f}")
    print()

    # Aggregate equity curve across pairs (chronological)
    all_t_sorted = []
    for ts in all_trades.values():
        all_t_sorted.extend(ts)
    all_t_sorted.sort(key=lambda x: x.exit_ts or x.entry_ts)
    peak = 0.0
    eq = 0.0
    max_dd = 0.0
    max_eq = 0.0
    for t in all_t_sorted:
        eq += t.pnl_dollars
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
        max_eq = max(max_eq, eq)
    print(f"Portfolio peak equity: ${max_eq:+,.2f}")
    print(f"Portfolio max drawdown: ${max_dd:+,.2f}")
    print(f"Risk/trade: ${RISK_PER_TRADE:.0f}  →  "
          f"Net / Risk = {grand_pnl / RISK_PER_TRADE:+.1f}R total")

    # Exit-reason breakdown
    print()
    reasons = defaultdict(int)
    reason_pnl = defaultdict(float)
    for t in all_t_sorted:
        reasons[t.exit_reason] += 1
        reason_pnl[t.exit_reason] += t.pnl_dollars
    print("Exit reasons:")
    for r, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:20} {n:>5d} trades   ${reason_pnl[r]:>+10,.2f}")

    # Filter audit
    print()
    print("Filter rejections (bars where a signal was blocked):")
    print(f"  overwhelm_no_signal  {audit.overwhelm_no_signal:>7d}")
    print(f"  ema_disagree         {audit.ema_disagree:>7d}")
    print(f"  weekly_vwap_disagree {audit.weekly_vwap_disagree:>7d}")
    print(f"  monthly_vwap_disagree{audit.monthly_vwap_disagree:>7d}")
    print(f"  indicator_warmup     {audit.indicator_warmup:>7d}")
    print(f"  concurrency_cap      {audit.concurrency_cap:>7d}")
    print(f"  cutoff_friday        {audit.cutoff_friday:>7d}")

    # CSV
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair", "direction", "entry_ts", "entry_price",
                    "exit_ts", "exit_price", "exit_reason",
                    "units", "stop_pips", "pnl_pips", "pnl_dollars",
                    "bars_held"])
        for t in all_t_sorted:
            w.writerow([t.pair, t.direction,
                        t.entry_ts.isoformat() if t.entry_ts else "",
                        f"{t.entry_price:.5f}",
                        t.exit_ts.isoformat() if t.exit_ts else "",
                        f"{t.exit_price:.5f}" if t.exit_price else "",
                        t.exit_reason, t.units,
                        f"{t.stop_distance_pips:.1f}",
                        f"{t.pnl_pips:.1f}",
                        f"{t.pnl_dollars:.2f}",
                        t.bars_held])
    print()
    print(f"Trade log: {out_csv}")


# ─── CLI ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None,
                    help="YYYY-MM-DD (default: 24mo before --end)")
    ap.add_argument("--end", default=None,
                    help="YYYY-MM-DD (default: today)")
    ap.add_argument("--out", default="backtest_trades.csv")
    ap.add_argument("--pairs", default=",".join(PAIRS))
    args = ap.parse_args()

    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) \
            if args.end else datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0)
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc) \
              if args.start else end - timedelta(days=730)
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    # Credentials live in the users table (same place bot_runner reads them).
    # Env override available for ad-hoc runs.
    api_key = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
    if not api_key:
        try:
            import psycopg2
            db_url = os.environ.get("DATABASE_URL",
                "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db")
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT oanda_api_key, oanda_account_id, oanda_environment "
                        "FROM users WHERE bot_active = true "
                        "AND oanda_api_key IS NOT NULL ORDER BY id LIMIT 1"
                    )
                    row = cur.fetchone()
                    if row:
                        api_key, account_id, environment = row[0], row[1], row[2] or "practice"
        except Exception as e:
            print(f"ERROR: couldn't load Oanda creds from DB: {e}", file=sys.stderr)
            sys.exit(2)
    if not api_key:
        print("ERROR: no Oanda credentials found (env or DB).", file=sys.stderr)
        sys.exit(2)

    client = OandaClient(account_id=account_id, api_key=api_key,
                          environment=environment)

    audit = FilterAudit()
    all_trades: dict[str, list[Trade]] = {}
    all_regimes: dict[str, list[tuple]] = {}
    open_trades_ref: list[Trade] = []

    for pair in pairs:
        print(f"[{pair}] fetching H4 bars {start.date()} → {end.date()}...",
              flush=True)
        bars = fetch_h4_range(client, pair, start, end)
        print(f"[{pair}] {len(bars)} bars; simulating...", flush=True)
        trades, regimes = simulate_pair(pair, bars, open_trades_ref, audit)
        all_trades[pair] = trades
        all_regimes[pair] = regimes
        if REGIME_ENABLED and regimes:
            eligible_weeks = sum(1 for _, ok, *_ in regimes if ok)
            total_weeks = len(regimes)
            pct = eligible_weeks / total_weeks * 100 if total_weeks else 0
            print(f"[{pair}] {len(trades)} trades; "
                  f"eligible {eligible_weeks}/{total_weeks} weeks ({pct:.0f}%)",
                  flush=True)
        else:
            print(f"[{pair}] {len(trades)} trades", flush=True)

    print_report(all_trades, audit, start, end, args.out)

    if REGIME_ENABLED:
        print()
        print("=" * 76)
        print("Regime fingerprint (per pair, weekly recompute, 90d lookback)")
        print("=" * 76)
        print(f"{'PAIR':9s} {'ELIGIBLE':>14s}  {'AVG ATR%':>9s} {'AVG |DRIFT|':>13s}")
        for pair in pairs:
            regs = all_regimes.get(pair, [])
            if not regs:
                print(f"{pair:9s} {'no data':>14s}")
                continue
            elig = sum(1 for _, ok, *_ in regs if ok)
            total = len(regs)
            avg_atr = sum(r[2] for r in regs) / total
            avg_drift = sum(abs(r[3]) for r in regs) / total
            print(f"{pair:9s} {elig:>4d}/{total:<3d}({elig/total*100:>3.0f}%)  "
                  f"{avg_atr:>7.2f}%  {avg_drift:>10.0f}p")

        # Regime flip events — when a pair toggled eligibility
        print()
        print("Regime flip history (entries where status changed week-over-week):")
        for pair in pairs:
            regs = all_regimes.get(pair, [])
            flips = []
            prev = None
            for ts, ok, atrp, drift in regs:
                if prev is not None and ok != prev:
                    flips.append((ts, ok, atrp, drift))
                prev = ok
            if flips:
                print(f"  {pair}:")
                for ts, ok, atrp, drift in flips[:8]:
                    state = "ELIGIBLE" if ok else "PAUSED"
                    print(f"    {ts.date()}: → {state}  "
                          f"(ATR={atrp:.2f}%, drift={drift:+.0f}p)")
                if len(flips) > 8:
                    print(f"    ... ({len(flips) - 8} more)")


if __name__ == "__main__":
    main()
