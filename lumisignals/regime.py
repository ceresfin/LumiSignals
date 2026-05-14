"""Regime fingerprinting for pair-strategy fit.

Shared between the backtester (saas/backtest_fx_4h.py) and the live
runtime (bot cron + API).  Same constants, same math, same shape of
Bar dict so backtest and live decisions can't diverge.

A pair is *eligible* for the FX 4H strategy in a given week when its
prior-90-day fingerprint matches the "USD_CAD profile" we identified
empirically:
  - low volatility (ATR / price < REGIME_MAX_ATR_PCT)
  - range-bound (|net drift| < REGIME_MAX_DRIFT_PIPS)

The thresholds were validated by 24mo backtest: with them on, net P&L
moved from -$1.4K to +$25.3K and max drawdown dropped 66%.

The eligibility flips weekly at the FX day rollover (Sunday 17:00 ET),
which is also the canonical anchor for the rest of the strategy's
indicators (weekly VWAP, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


# ─── Thresholds (locked in by v4 backtest) ─────────────────────────────────
REGIME_LOOKBACK_DAYS = 90
REGIME_MAX_ATR_PCT   = 0.30      # ATR / price ratio %
REGIME_MAX_DRIFT_PIPS = 500      # |net drift| over the lookback window

# Indicator periods used when computing the fingerprint — must match
# whatever the live trade engine uses or the regime filter and the
# entry logic will disagree.
ATR_PERIOD = 14
WEEK_ANCHOR_HOUR_ET = 17         # Sunday 5 PM ET
NY_TZ_OFFSET = -4                # EDT; only used for week bucketing.


# ─── Bar shape (matches the backtester's Bar dataclass loosely) ────────────
@dataclass
class Bar:
    """Minimum shape needed by regime math.  Backtester's Bar satisfies
    this duck-typed contract; live code can pass dicts or its own
    objects as long as the named attributes exist."""
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    volume: int


# ─── Helpers ───────────────────────────────────────────────────────────────
def pip_factor(pair: str) -> float:
    """0.01 for JPY pairs, 0.0001 otherwise."""
    return 0.01 if "JPY" in pair else 0.0001


def to_et(ts: datetime) -> datetime:
    """Approximate NY time using a fixed EDT offset.  Acceptable for
    weekly bucketing; not used for price math."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone(timedelta(hours=NY_TZ_OFFSET)))


def week_anchor(ts: datetime) -> datetime:
    """Most recent Sunday 17:00 ET on or before ts."""
    et = to_et(ts)
    days_back = (et.weekday() + 1) % 7   # Mon=0→1, ..., Sun=6→0
    sunday = et - timedelta(days=days_back)
    anchor = sunday.replace(hour=WEEK_ANCHOR_HOUR_ET, minute=0,
                             second=0, microsecond=0)
    if anchor > et:
        anchor -= timedelta(days=7)
    return anchor


def rolling_atr(bars, period: int) -> list[Optional[float]]:
    """Wilder ATR(N).  TR = max(h-l, |h-prev_c|, |l-prev_c|).  Returns
    None for warm-up bars."""
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


# ─── Fingerprint + eligibility ─────────────────────────────────────────────
@dataclass
class RegimeFingerprint:
    eligible: bool
    atr_pct: float        # avg ATR / price over the lookback window, %
    drift_pips: float     # last_close - first_close (signed) over window
    bars_used: int        # how many bars made it into the fingerprint
    fail_reason: str      # "" when eligible; otherwise which gate tripped

    def to_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "atr_pct": round(self.atr_pct, 4),
            "drift_pips": round(self.drift_pips, 1),
            "bars_used": self.bars_used,
            "fail_reason": self.fail_reason,
        }


def compute_fingerprint(window_bars: list,
                         pair: str,
                         max_atr_pct: float = REGIME_MAX_ATR_PCT,
                         max_drift_pips: float = REGIME_MAX_DRIFT_PIPS
                         ) -> RegimeFingerprint:
    """Score the regime for the given window of bars (typically the last
    90 days of H4 bars, strictly BEFORE the eligibility decision point —
    no look-ahead).  Returns an eligibility verdict + the underlying
    metrics so the UI can show why."""
    if not window_bars or len(window_bars) < 50:
        return RegimeFingerprint(
            eligible=False, atr_pct=0.0, drift_pips=0.0,
            bars_used=len(window_bars) if window_bars else 0,
            fail_reason="insufficient_data",
        )
    pf = pip_factor(pair)
    atrs = rolling_atr(window_bars, ATR_PERIOD)
    valid = [(window_bars[i].c, a) for i, a in enumerate(atrs) if a is not None]
    if not valid:
        return RegimeFingerprint(
            eligible=False, atr_pct=0.0, drift_pips=0.0,
            bars_used=len(window_bars), fail_reason="no_atr",
        )
    atr_pct = sum(a / c for c, a in valid) / len(valid) * 100
    drift_pips = (window_bars[-1].c - window_bars[0].c) / pf

    fails = []
    if atr_pct >= max_atr_pct:
        fails.append(f"atr {atr_pct:.2f}% ≥ {max_atr_pct:.2f}%")
    if abs(drift_pips) >= max_drift_pips:
        fails.append(f"|drift| {abs(drift_pips):.0f}p ≥ {max_drift_pips:.0f}p")

    return RegimeFingerprint(
        eligible=(not fails),
        atr_pct=atr_pct,
        drift_pips=drift_pips,
        bars_used=len(window_bars),
        fail_reason=" & ".join(fails),
    )


def compute_weekly_states(bars: list, pair: str
                            ) -> list[tuple[datetime, RegimeFingerprint]]:
    """Walk forward in weekly steps, computing a fingerprint at each
    Sunday-17:00-ET anchor from the prior 90 days of bars.  Returns a
    list of (effective_from_ts, fingerprint) pairs.

    No look-ahead: only bars strictly before the anchor are used.
    """
    if not bars:
        return []
    out: list[tuple[datetime, RegimeFingerprint]] = []
    last_anchor: Optional[datetime] = None
    for b in bars:
        anchor = week_anchor(b.ts)
        if anchor == last_anchor:
            continue
        last_anchor = anchor
        cutoff = b.ts - timedelta(days=REGIME_LOOKBACK_DAYS)
        window = [x for x in bars if cutoff <= x.ts < b.ts]
        fp = compute_fingerprint(window, pair)
        out.append((anchor, fp))
    return out


def state_at(states: list[tuple[datetime, RegimeFingerprint]],
              ts: datetime) -> Optional[RegimeFingerprint]:
    """Most-recent regime state at-or-before ts.  Returns None when ts
    predates the first state."""
    current: Optional[RegimeFingerprint] = None
    for state_ts, fp in states:
        if state_ts <= ts:
            current = fp
        else:
            break
    return current


def is_eligible_at(states: list[tuple[datetime, RegimeFingerprint]],
                    ts: datetime) -> bool:
    """Convenience: shortcut for `state_at(...).eligible`."""
    s = state_at(states, ts)
    return bool(s and s.eligible)
