"""SNR Frequency filter — validates signals against untouched supply/demand levels."""

import logging
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Timeframes ordered from highest to lowest impact
ALL_TIMEFRAMES = ["1mo", "1w", "1d", "4h", "1h", "30m", "15m", "5m"]

# Alert levels — always monitored regardless of trading timeframe
ALERT_TIMEFRAMES = {"1mo", "1w", "1d"}

# Mapping from user-friendly trading timeframe to SNR API interval names
TIMEFRAME_ALIASES = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1H": "1h",
    "4h": "4h",
    "4H": "4h",
    "daily": "1d",
    "1d": "1d",
    "1D": "1d",
    "weekly": "1w",
    "1w": "1w",
    "1W": "1w",
    "monthly": "1mo",
    "1mo": "1mo",
    "1M": "1mo",
}

# For each trading timeframe, which primary levels to check (2-3 timeframes above)
# Alert levels (monthly, weekly, daily) are always added on top of these.
_PRIMARY_MAP = {
    "5m":  ["15m", "30m", "1h"],
    "15m": ["30m", "1h"],
    "30m": ["1h", "4h"],
    "1h":  ["4h"],
    "4h":  [],    # primary levels are already covered by alerts
    "1d":  [],    # alerts cover weekly + monthly
    "1w":  [],
    "1mo": [],
}


def get_relevant_timeframes(trading_timeframe: str) -> Tuple[List[str], List[str]]:
    """Determine which SNR timeframes to use based on the user's trading timeframe.

    Returns:
        (primary_timeframes, alert_timeframes)
        - primary: 2-3 timeframes above the trading TF, used for active trade decisions
        - alert: monthly/weekly/daily — always monitored, high-impact when price is near
    """
    tf = TIMEFRAME_ALIASES.get(trading_timeframe, trading_timeframe)

    primary = _PRIMARY_MAP.get(tf, ["1h", "4h"])
    # Remove any primary levels already covered by alert levels
    primary = [t for t in primary if t not in ALERT_TIMEFRAMES]

    # Alert levels that are above the trading timeframe
    tf_index = ALL_TIMEFRAMES.index(tf) if tf in ALL_TIMEFRAMES else len(ALL_TIMEFRAMES)
    alerts = [t for t in ALERT_TIMEFRAMES if ALL_TIMEFRAMES.index(t) < tf_index]
    # If trading on daily or above, alerts are the timeframes above it
    if not alerts and tf in ALERT_TIMEFRAMES:
        alerts = [t for t in ALERT_TIMEFRAMES if ALL_TIMEFRAMES.index(t) < ALL_TIMEFRAMES.index(tf)]

    return primary, alerts


class SNRClient:
    """Client for the LumiTrade Partner SNR Frequency API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def get_snr_levels(self, ticker: str, intervals: List[str],
                       market_type: str = "forex", days: int = 256) -> dict:
        """Fetch untouched S/R levels for a ticker across multiple timeframes.

        Returns:
            Dict keyed by interval, e.g.:
            {"1d": {"support_price": 1.08, "resistance_price": 1.10}, ...}
        """
        params = {
            "ticker": ticker,
            "intervals": ",".join(intervals),
            "type": market_type,
            "days": days,
        }
        try:
            resp = self.session.get(
                f"{self.base_url}/partners/technical-analysis/snr/frequency/",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            # API may wrap response in {"data": {...}}
            return result.get("data", result)
        except Exception as e:
            logger.error("SNR API error for %s: %s", ticker, e)
            return {}


def check_snr_confluence(entry: float, stop: float, target: float, action: str,
                         snr_data: dict, primary_tfs: List[str], alert_tfs: List[str],
                         tolerance_pct: float = 0.002) -> dict:
    """Check if a signal's levels align with untouched S/R.

    Args:
        entry: Signal entry price.
        stop: Signal stop price.
        target: Signal target price.
        action: "BUY" or "SELL".
        snr_data: Response from SNR API keyed by interval.
        primary_tfs: Primary timeframes to check for active trading.
        alert_tfs: Alert timeframes (monthly/weekly/daily).
        tolerance_pct: How close price must be to S/R as a fraction of price (default 0.2%).

    Returns:
        Dict with confluence analysis:
        {
            "has_primary_confluence": bool,
            "has_alert_confluence": bool,
            "primary_matches": [...],
            "alert_matches": [...],
            "grade": "A+" | "A" | "B" | "C",
            "summary": str,
        }
    """
    tolerance = entry * tolerance_pct

    primary_matches = []
    alert_matches = []

    for tf, levels in snr_data.items():
        if not isinstance(levels, dict):
            continue

        support = levels.get("support_price")
        resistance = levels.get("resistance_price")

        if support is None and resistance is None:
            continue

        matches_for_tf = []

        if action == "BUY":
            # For a BUY, entry near support is good, target near resistance is good
            if support and abs(entry - support) <= tolerance:
                matches_for_tf.append({
                    "timeframe": tf,
                    "level_type": "support",
                    "level_price": support,
                    "signal_price": entry,
                    "role": "entry_at_demand",
                    "distance": abs(entry - support),
                })
            if resistance and abs(target - resistance) <= tolerance:
                matches_for_tf.append({
                    "timeframe": tf,
                    "level_type": "resistance",
                    "level_price": resistance,
                    "signal_price": target,
                    "role": "target_at_supply",
                    "distance": abs(target - resistance),
                })
        else:  # SELL
            # For a SELL, entry near resistance is good, target near support is good
            if resistance and abs(entry - resistance) <= tolerance:
                matches_for_tf.append({
                    "timeframe": tf,
                    "level_type": "resistance",
                    "level_price": resistance,
                    "signal_price": entry,
                    "role": "entry_at_supply",
                    "distance": abs(entry - resistance),
                })
            if support and abs(target - support) <= tolerance:
                matches_for_tf.append({
                    "timeframe": tf,
                    "level_type": "support",
                    "level_price": support,
                    "signal_price": target,
                    "role": "target_at_demand",
                    "distance": abs(target - support),
                })

        for match in matches_for_tf:
            if tf in alert_tfs:
                alert_matches.append(match)
            elif tf in primary_tfs:
                primary_matches.append(match)

    has_primary = len(primary_matches) > 0
    has_alert = len(alert_matches) > 0

    # Grading
    if has_primary and has_alert:
        grade = "A+"
    elif has_alert:
        grade = "A"
    elif has_primary:
        grade = "B"
    else:
        grade = "C"

    # Summary
    parts = []
    if alert_matches:
        tfs = sorted(set(m["timeframe"] for m in alert_matches))
        parts.append(f"alert-level confluence ({', '.join(tfs)})")
    if primary_matches:
        tfs = sorted(set(m["timeframe"] for m in primary_matches))
        parts.append(f"primary confluence ({', '.join(tfs)})")
    summary = f"Grade {grade}: " + (" + ".join(parts) if parts else "no S/R confluence")

    return {
        "has_primary_confluence": has_primary,
        "has_alert_confluence": has_alert,
        "primary_matches": primary_matches,
        "alert_matches": alert_matches,
        "grade": grade,
        "summary": summary,
    }
