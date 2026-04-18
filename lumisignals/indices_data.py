"""Indices data fetcher — grabs all major indices from Polygon/Massive API.

Usage:
    from lumisignals.indices_data import IndicesClient

    client = IndicesClient(api_key="your_key")
    data = client.get_all()          # All 80 indices, latest values
    spx = client.get("I:SPX")       # Single index
    vols = client.get_category("volatility")  # By category
    candles = client.get_candles("I:SPX", "1d", 30)  # OHLC history

CLI:
    python3 -m lumisignals.indices_data              # Print all
    python3 -m lumisignals.indices_data I:SPX I:VIX  # Print specific
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"

# -----------------------------------------------------------------------
# Eastern Time helpers
# -----------------------------------------------------------------------

ET_OFFSET_EDT = timedelta(hours=-4)  # Mar-Nov
ET_OFFSET_EST = timedelta(hours=-5)  # Nov-Mar


def utc_to_et(dt_utc: datetime) -> datetime:
    """Convert UTC datetime to US Eastern Time (auto-detect EDT/EST)."""
    # Simple DST rule: EDT Mar second Sun - Nov first Sun
    year = dt_utc.year
    # Second Sunday in March
    mar1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)
    # First Sunday in November
    nov1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    if dst_start <= dt_utc.replace(tzinfo=timezone.utc) < dst_end:
        return dt_utc + ET_OFFSET_EDT
    return dt_utc + ET_OFFSET_EST


def timestamp_to_et(ts_ms: int) -> str:
    """Convert Polygon millisecond timestamp to ET string."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    et = utc_to_et(dt)
    return et.strftime("%Y-%m-%d %I:%M %p ET")


def timestamp_to_date(ts_ms: int) -> str:
    """Convert Polygon millisecond timestamp to date string in ET."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    et = utc_to_et(dt)
    return et.strftime("%Y-%m-%d")


# -----------------------------------------------------------------------
# Index definitions — 80 indices organized by category
# -----------------------------------------------------------------------

INDICES = {
    # --- US Equity Broad Market ---
    "I:SPX":    {"name": "S&P 500",                     "category": "us_equity",    "hours": "9:30am-4:00pm ET"},
    "I:NDX":    {"name": "Nasdaq 100",                   "category": "us_equity",    "hours": "9:30am-4:00pm ET"},
    "I:DJI":    {"name": "Dow Jones Industrial",         "category": "us_equity",    "hours": "9:30am-4:00pm ET"},
    "I:COMP":   {"name": "Nasdaq Composite",             "category": "us_equity",    "hours": "9:30am-4:00pm ET"},
    "I:RUT":    {"name": "Russell 2000 (Small Cap)",     "category": "us_equity",    "hours": "9:30am-4:00pm ET"},
    "I:RUI":    {"name": "Russell 1000 (Large Cap)",     "category": "us_equity",    "hours": "9:30am-4:00pm ET"},
    "I:DJT":    {"name": "Dow Jones Transport",          "category": "us_equity",    "hours": "9:30am-4:00pm ET"},
    "I:DJU":    {"name": "Dow Jones Utilities",           "category": "us_equity",    "hours": "9:30am-4:00pm ET"},

    # --- Sector ---
    "I:SOX":    {"name": "Philadelphia Semiconductor",   "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:BKX":    {"name": "KBW Bank Index",               "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:KRX":    {"name": "KBW Regional Banking",         "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:HGX":    {"name": "Housing Index",                "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:OSX":    {"name": "Oil Service Index",            "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:NBI":    {"name": "Nasdaq Biotech",               "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:XAU":    {"name": "Gold & Silver (PHLX)",         "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:UTY":    {"name": "Utilities (PHLX)",             "category": "sector",       "hours": "9:30am-4:00pm ET"},
    "I:DJUSRE": {"name": "DJ US Real Estate",            "category": "sector",       "hours": "9:30am-4:00pm ET"},

    # --- Volatility ---
    "I:VIX":    {"name": "CBOE VIX (S&P 500 30d)",      "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VIX1D":  {"name": "VIX 1-Day",                   "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VIX9D":  {"name": "VIX 9-Day",                   "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VIX3M":  {"name": "VIX 3-Month",                 "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VIX1Y":  {"name": "VIX 1-Year",                  "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VVIX":   {"name": "VIX of VIX",                  "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:SKEW":   {"name": "CBOE Skew Index",             "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:RVX":    {"name": "Russell 2000 VIX",            "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VXN":    {"name": "Nasdaq 100 VIX",              "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VXD":    {"name": "Dow Jones VIX",               "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:OVX":    {"name": "Oil VIX (Crude)",             "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:GVZ":    {"name": "Gold VIX",                    "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:VXEEM":  {"name": "Emerging Markets VIX",        "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:TDEX":   {"name": "CBOE Tail Risk",              "category": "volatility",   "hours": "9:30am-4:15pm ET"},
    "I:DSPX":   {"name": "CBOE S&P 500 Dispersion",    "category": "volatility",   "hours": "9:30am-4:15pm ET"},

    # --- Options Strategy Benchmarks ---
    "I:BXM":    {"name": "S&P 500 BuyWrite (Covered Call)",     "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BXMD":   {"name": "S&P 500 30-Delta BuyWrite",          "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BXMC":   {"name": "S&P 500 Conditional BuyWrite",       "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BXN":    {"name": "Nasdaq 100 BuyWrite",                "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BXR":    {"name": "Russell 2000 BuyWrite",              "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BXY":    {"name": "S&P 500 2% OTM BuyWrite",            "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BXMW":   {"name": "S&P 500 Weekly BuyWrite",            "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BXHB":   {"name": "S&P 500 Half BuyWrite",              "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:PUT":    {"name": "S&P 500 PutWrite",                   "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:PUTD":   {"name": "S&P 500 Delta PutWrite",             "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:PUTR":   {"name": "Russell 2000 PutWrite",              "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:WPUT":   {"name": "S&P 500 Weekly PutWrite",            "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:PPUT":   {"name": "S&P 500 Protective Put",             "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:CLL":    {"name": "S&P 500 95-110 Collar",              "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:CLLZ":   {"name": "S&P 500 Zero-Cost Collar",           "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:CNDR":   {"name": "S&P 500 Iron Condor",                "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:BFLY":   {"name": "S&P 500 Iron Butterfly",             "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:CMBO":   {"name": "S&P 500 Combo (Put+Call)",            "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:LOVOL":  {"name": "S&P 500 Low Volatility",             "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:SPRI":   {"name": "S&P 500 Risk Premium",               "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:VPD":    {"name": "S&P 500 VIX Premium (daily)",         "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:VPN":    {"name": "S&P 500 VIX Premium (monthly)",       "category": "options_strategy", "hours": "9:30am-4:00pm ET"},
    "I:VXTH":   {"name": "VIX Tail Hedge",                     "category": "options_strategy", "hours": "9:30am-4:00pm ET"},

    # --- Commodities ---
    "I:DJCI":   {"name": "DJ Commodity Index (broad)",          "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIEN": {"name": "DJ Commodity Energy",                 "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIPM": {"name": "DJ Commodity Precious Metals",        "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIIM": {"name": "DJ Commodity Industrial Metals",      "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIGC": {"name": "DJ Commodity Gold",                   "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCISI": {"name": "DJ Commodity Silver",                 "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCICL": {"name": "DJ Commodity Crude Oil",              "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCING": {"name": "DJ Commodity Natural Gas",            "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIHO": {"name": "DJ Commodity Heating Oil",            "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIRB": {"name": "DJ Commodity RBOB Gasoline",          "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIHG": {"name": "DJ Commodity Copper",                 "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIWH": {"name": "DJ Commodity Wheat",                  "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCICN": {"name": "DJ Commodity Corn",                   "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCISY": {"name": "DJ Commodity Soybeans",               "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCISB": {"name": "DJ Commodity Sugar",                  "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIKC": {"name": "DJ Commodity Coffee",                 "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCICT": {"name": "DJ Commodity Cotton",                 "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCICC": {"name": "DJ Commodity Cocoa",                  "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCILH": {"name": "DJ Commodity Lean Hogs",              "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCILC": {"name": "DJ Commodity Live Cattle",            "category": "commodity",    "hours": "9:30am-4:00pm ET"},
    "I:DJCIFC": {"name": "DJ Commodity Feeder Cattle",          "category": "commodity",    "hours": "9:30am-4:00pm ET"},

    # --- International ---
    "I:MXEF":   {"name": "MSCI Emerging Markets",              "category": "international", "hours": "Varies"},
    "I:MXEA":   {"name": "MSCI EAFE (Developed ex-US)",        "category": "international", "hours": "Varies"},
    "I:MXWO":   {"name": "MSCI World",                         "category": "international", "hours": "Varies"},
    "I:GDOW":   {"name": "Global Dow",                         "category": "international", "hours": "Varies"},
    "I:EDOW":   {"name": "Europe Dow",                         "category": "international", "hours": "3:00am-11:30am ET"},
    "I:ADOW":   {"name": "Asia Dow",                           "category": "international", "hours": "8:00pm-3:00am ET"},
    "I:W1DOW":  {"name": "World Dow",                          "category": "international", "hours": "Varies"},

    # --- Other ---
    "I:DJDVY":  {"name": "DJ Dividend Select",                 "category": "other",        "hours": "9:30am-4:00pm ET"},
    "I:DJITR":  {"name": "DJ Industrial Total Return",         "category": "other",        "hours": "9:30am-4:00pm ET"},
    "I:QMI":    {"name": "Nasdaq 100 Mini",                    "category": "other",        "hours": "9:30am-4:00pm ET"},
    "I:TRAN":   {"name": "Nasdaq Transport",                   "category": "other",        "hours": "9:30am-4:00pm ET"},
    "I:MSTAR":  {"name": "Morningstar",                        "category": "other",        "hours": "9:30am-4:00pm ET"},
    "I:BTC10RP": {"name": "Cboe Bitcoin RealPrice",            "category": "other",        "hours": "24/7"},
}

CATEGORY_LABELS = {
    "us_equity": "US Equity Broad Market",
    "sector": "Sector Indices",
    "volatility": "Volatility",
    "options_strategy": "Options Strategy Benchmarks",
    "commodity": "Commodities",
    "international": "International / Global",
    "other": "Other",
}

CATEGORY_ORDER = ["us_equity", "sector", "volatility", "options_strategy", "commodity", "international", "other"]


# -----------------------------------------------------------------------
# Client
# -----------------------------------------------------------------------

class IndicesClient:
    """Fetch index data from Polygon/Massive API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("MASSIVE_API_KEY", "")
        self.session = requests.Session()

    def _request(self, endpoint: str, params: dict = None) -> dict:
        params = params or {}
        params["apiKey"] = self.api_key
        resp = self.session.get(f"{BASE_URL}{endpoint}", params=params, timeout=15)
        if not resp.ok:
            logger.error("Polygon API error: %s - %s", resp.status_code, resp.text[:200])
            return {}
        return resp.json()

    # --- Single index ---

    def get(self, ticker: str) -> Optional[dict]:
        """Get latest data for a single index.

        Returns dict with: ticker, name, category, close, open, high, low,
        change, change_pct, date, timestamp_et, hours.
        """
        info = INDICES.get(ticker)
        if not info:
            return None

        data = self._request(f"/v2/aggs/ticker/{ticker}/prev")
        results = data.get("results", [])
        if not results:
            return {"ticker": ticker, **info, "error": "No data"}

        bar = results[0]
        close = bar.get("c", 0)
        prev_close = bar.get("o", close)  # use open as proxy for prev close
        change = close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0

        return {
            "ticker": ticker,
            "name": info["name"],
            "category": info["category"],
            "hours": info["hours"],
            "open": bar.get("o", 0),
            "high": bar.get("h", 0),
            "low": bar.get("l", 0),
            "close": close,
            "volume": bar.get("v", 0),
            "vwap": bar.get("vw", 0),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "date": timestamp_to_date(bar.get("t", 0)),
            "timestamp_et": timestamp_to_et(bar.get("t", 0)),
        }

    # --- Multiple indices ---

    def get_many(self, tickers: List[str]) -> List[dict]:
        """Get latest data for multiple indices."""
        results = []
        for ticker in tickers:
            data = self.get(ticker)
            if data:
                results.append(data)
        return results

    def get_category(self, category: str) -> List[dict]:
        """Get all indices in a category.

        Categories: us_equity, sector, volatility, options_strategy,
                    commodity, international, other
        """
        tickers = [t for t, info in INDICES.items() if info["category"] == category]
        return self.get_many(tickers)

    def get_all(self) -> dict:
        """Get all 80 indices, organized by category.

        Returns dict of {category: [index_data, ...]}
        """
        result = {}
        for cat in CATEGORY_ORDER:
            label = CATEGORY_LABELS[cat]
            result[label] = self.get_category(cat)
        return result

    # --- OHLC candles ---

    def get_candles(self, ticker: str, timespan: str = "1d", count: int = 30) -> List[dict]:
        """Get OHLC candle history for an index.

        Args:
            ticker: e.g. "I:SPX"
            timespan: "1d", "1h", "1w", "1mo"
            count: Number of bars (approximate)

        Returns list of {date, open, high, low, close, volume, timestamp_et}
        """
        ts_map = {
            "1mo": ("1", "month"),
            "1w": ("1", "week"),
            "1d": ("1", "day"),
            "4h": ("4", "hour"),
            "1h": ("1", "hour"),
            "30m": ("30", "minute"),
            "15m": ("15", "minute"),
            "5m": ("5", "minute"),
        }
        multiplier, span = ts_map.get(timespan, ("1", "day"))

        # Calculate date range
        if span == "month":
            days_back = count * 31
        elif span == "week":
            days_back = count * 7
        elif span == "day":
            days_back = int(count * 1.5)  # account for weekends
        else:
            days_back = max(count // 6, 5)  # hours/minutes

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        data = self._request(
            f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{span}/{start}/{end}",
            params={"adjusted": "true", "sort": "asc", "limit": count},
        )

        candles = []
        for bar in data.get("results", []):
            candles.append({
                "date": timestamp_to_date(bar.get("t", 0)),
                "timestamp_et": timestamp_to_et(bar.get("t", 0)),
                "open": bar.get("o", 0),
                "high": bar.get("h", 0),
                "low": bar.get("l", 0),
                "close": bar.get("c", 0),
                "volume": bar.get("v", 0),
                "vwap": bar.get("vw", 0),
            })
        return candles

    # --- Convenience ---

    def get_vix_term_structure(self) -> dict:
        """Get VIX term structure (1d, 9d, 30d, 3m, 1y)."""
        vix_tickers = ["I:VIX1D", "I:VIX9D", "I:VIX", "I:VIX3M", "I:VIX1Y"]
        data = self.get_many(vix_tickers)
        return {
            "1d": next((d for d in data if d["ticker"] == "I:VIX1D"), None),
            "9d": next((d for d in data if d["ticker"] == "I:VIX9D"), None),
            "30d": next((d for d in data if d["ticker"] == "I:VIX"), None),
            "3m": next((d for d in data if d["ticker"] == "I:VIX3M"), None),
            "1y": next((d for d in data if d["ticker"] == "I:VIX1Y"), None),
        }

    def get_market_snapshot(self) -> dict:
        """Quick snapshot of key indices: SPX, NDX, DJI, RUT, VIX."""
        return self.get_many(["I:SPX", "I:NDX", "I:DJI", "I:RUT", "I:VIX"])

    @staticmethod
    def list_tickers(category: str = None) -> List[str]:
        """List available tickers, optionally filtered by category."""
        if category:
            return [t for t, info in INDICES.items() if info["category"] == category]
        return list(INDICES.keys())

    @staticmethod
    def list_categories() -> List[str]:
        """List available categories."""
        return list(CATEGORY_ORDER)


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.WARNING)
    api_key = os.environ.get("MASSIVE_API_KEY", "iuT5Pj3thRCf6dRliPm4cGlzolW99E2n")
    client = IndicesClient(api_key=api_key)

    # Specific tickers passed as args
    if len(sys.argv) > 1:
        for ticker in sys.argv[1:]:
            data = client.get(ticker)
            if data and not data.get("error"):
                print(f"{data['ticker']:12s} {data['name']:40s} {data['close']:>12,.2f}  {data['change_pct']:>+6.2f}%  ({data['date']})")
            else:
                print(f"{ticker}: not found")
        sys.exit(0)

    # Print all
    all_data = client.get_all()
    for category, indices in all_data.items():
        print(f"\n{'='*80}")
        print(f"  {category}")
        print(f"{'='*80}")
        for d in indices:
            if d.get("error"):
                print(f"  {d['ticker']:12s} {d['name']:40s} {'NO DATA':>12s}")
            else:
                print(f"  {d['ticker']:12s} {d['name']:40s} {d['close']:>12,.2f}  {d['change_pct']:>+6.2f}%")
