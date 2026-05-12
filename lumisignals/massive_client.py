"""Massive (formerly Polygon) market data client for stocks and crypto."""

import logging
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests

from .candle_classifier import CandleData

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"

# Per-timespan TTL for the in-memory candle cache. Values chosen to refresh
# faster than the bar size so the strategy never works off a stale bar.
# A bar that just closed can't change until the next bar of that timeframe
# closes, so we can cache aggressively.
CANDLE_CACHE_TTL = {
    "1m": 30,        # 30s
    "5m": 90,        # 1.5 min
    "15m": 300,      # 5 min
    "30m": 600,      # 10 min
    "1h": 1200,      # 20 min
    "4h": 7200,      # 2 hours
    "1d": 14400,     # 4 hours
    "1w": 86400,     # 1 day
    "1mo": 86400,    # 1 day
}
_DEFAULT_CACHE_TTL = 120

# -----------------------------------------------------------------------
# Ticker watchlists — easy to extend, just add tickers to the lists
# -----------------------------------------------------------------------

# Core watchlist
CORE_TICKERS = [
    # Major Indices (Polygon uses I: prefix for index data)
    "I:SPX", "I:NDX",           # S&P 500 Index, Nasdaq 100 Index
    "I:XSP", "I:XND",           # Mini S&P 500 (1/10), Mini Nasdaq 100 (1/100)

    # Major ETFs
    "SPY", "QQQ", "IWM",       # S&P 500, Nasdaq 100, Russell 2000
    "DIA",                       # Dow 30

    # 11 SPDR Sector ETFs
    "XLK",   # Technology
    "XLF",   # Financials
    "XLV",   # Health Care
    "XLE",   # Energy
    "XLI",   # Industrials
    "XLY",   # Consumer Discretionary
    "XLP",   # Consumer Staples
    "XLU",   # Utilities
    "XLB",   # Materials
    "XLRE",  # Real Estate
    "XLC",   # Communication Services

    # Mega-cap Tech
    "AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AVGO", "ORCL", "ADBE", "CRM", "AMD", "INTC", "QCOM", "AMAT",
    "MU", "NFLX", "CSCO", "IBM", "NOW", "INTU", "SNPS", "CDNS",

    # Financials
    "JPM", "V", "MA", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW",
    "AXP", "BX", "KKR", "COIN",

    # Health Care
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",

    # Consumer
    "WMT", "COST", "HD", "NKE", "MCD", "SBUX", "TGT", "LOW",
    "PG", "KO", "PEP",

    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",

    # Industrials / Transport
    "CAT", "DE", "HON", "UPS", "FDX", "BA", "GE", "RTX", "LMT",

    # Communication / Media
    "DIS", "CMCSA", "T", "VZ", "TMUS",

    # Hot / High-beta
    "PLTR", "UBER", "SQ", "SHOP", "SNOW", "DKNG", "SOFI",
    "RIVN", "LCID", "ARM", "SMCI", "MSTR",

    # Crypto ETFs
    "BITO", "IBIT", "FBTC",
]

# Crypto pairs (Massive/Polygon format: X:BTCUSD)
CRYPTO_TICKERS = [
    "X:BTCUSD",
    "X:ETHUSD",
    "X:SOLUSD",
    "X:XRPUSD",
    "X:DOGEUSD",
    "X:ADAUSD",
    "X:AVAXUSD",
    "X:DOTUSD",
    "X:LINKUSD",
    "X:MATICUSD",
    "X:LTCUSD",
    "X:UNIUSD",
]

# Ticker short names for scanner display
TICKER_NAMES = {
    # Indices
    "I:SPX": "S&P 500", "I:NDX": "Nasdaq 100", "I:XSP": "Mini S&P", "I:XND": "Mini Nasdaq",
    "I:DJI": "Dow Jones", "I:COMP": "Nasdaq Comp", "I:RUT": "Russell 2000", "I:RUI": "Russell 1000",
    "I:DJT": "Dow Transport", "I:DJU": "Dow Utilities", "I:SOX": "Semiconductors", "I:BKX": "KBW Bank",
    "I:KRX": "Regional Bank", "I:HGX": "Housing", "I:OSX": "Oil Service", "I:NBI": "Biotech",
    "I:XAU": "Gold & Silver", "I:UTY": "Utilities", "I:DJUSRE": "Real Estate",
    "I:DJCI": "Commodities", "I:DJCIEN": "Energy Cmdty", "I:DJCIPM": "Precious Metals",
    "I:DJCIIM": "Industrial Metals", "I:DJCIGC": "Gold", "I:DJCISI": "Silver",
    "I:DJCICL": "Crude Oil", "I:DJCING": "Natural Gas", "I:DJCIHO": "Heating Oil",
    "I:DJCIRB": "RBOB Gas", "I:DJCIHG": "Copper", "I:DJCIWH": "Wheat",
    "I:DJCICN": "Corn", "I:DJCISY": "Soybeans", "I:DJCISB": "Sugar",
    "I:DJCIKC": "Coffee", "I:DJCICT": "Cotton", "I:DJCICC": "Cocoa",
    "I:DJCILH": "Lean Hogs", "I:DJCILC": "Live Cattle", "I:DJCIFC": "Feeder Cattle",
    "I:MXEF": "EM Markets", "I:MXEA": "EAFE", "I:MXWO": "World",
    "I:GDOW": "Global Dow", "I:EDOW": "Europe Dow", "I:ADOW": "Asia Dow",
    "I:DJDVY": "Dividend Sel", "I:QMI": "Nasdaq Mini", "I:TRAN": "Nasdaq Trans", "I:MSTAR": "Morningstar",
    # ETFs
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq ETF", "IWM": "Russell ETF", "DIA": "Dow ETF",
    "XLK": "Tech Sector", "XLF": "Financial Sec", "XLV": "Health Sector", "XLE": "Energy Sector",
    "XLI": "Industrial Sec", "XLY": "Cons Disc Sec", "XLP": "Cons Staple", "XLU": "Utility Sector",
    "XLB": "Materials Sec", "XLRE": "Real Est Sec", "XLC": "Comms Sector",
    "GLD": "Gold ETF", "USO": "Oil ETF", "AGG": "Bond AGG", "BITO": "Bitcoin ETF",
    "IBIT": "iShares BTC", "FBTC": "Fidelity BTC",
    # Mega-cap
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOG": "Google", "GOOGL": "Google A",
    "AMZN": "Amazon", "META": "Meta", "NVDA": "Nvidia", "TSLA": "Tesla",
    "AVGO": "Broadcom", "ORCL": "Oracle", "ADBE": "Adobe", "CRM": "Salesforce",
    "AMD": "AMD", "INTC": "Intel", "QCOM": "Qualcomm", "AMAT": "Applied Mat",
    "MU": "Micron", "NFLX": "Netflix", "CSCO": "Cisco", "IBM": "IBM",
    "NOW": "ServiceNow", "INTU": "Intuit", "SNPS": "Synopsys", "CDNS": "Cadence",
    # Financials
    "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard", "BAC": "BofA",
    "GS": "Goldman", "MS": "Morgan Stan", "WFC": "Wells Fargo", "C": "Citigroup",
    "BLK": "BlackRock", "SCHW": "Schwab", "AXP": "AmEx", "BX": "Blackstone",
    "KKR": "KKR", "COIN": "Coinbase",
    # Health Care
    "UNH": "UnitedHealth", "JNJ": "J&J", "LLY": "Eli Lilly", "ABBV": "AbbVie",
    "MRK": "Merck", "PFE": "Pfizer", "TMO": "Thermo Fish", "ABT": "Abbott",
    "DHR": "Danaher", "BMY": "Bristol-Myers",
    # Consumer
    "WMT": "Walmart", "COST": "Costco", "HD": "Home Depot", "NKE": "Nike",
    "MCD": "McDonald's", "SBUX": "Starbucks", "TGT": "Target", "LOW": "Lowe's",
    "PG": "Procter&Gamb", "KO": "Coca-Cola", "PEP": "PepsiCo",
    # Energy
    "XOM": "Exxon", "CVX": "Chevron", "COP": "ConocoPhil", "SLB": "Schlumberger", "EOG": "EOG Res",
    # Industrials
    "CAT": "Caterpillar", "DE": "Deere", "HON": "Honeywell", "UPS": "UPS",
    "FDX": "FedEx", "BA": "Boeing", "GE": "GE Aero", "RTX": "RTX", "LMT": "Lockheed",
    # Comms
    "DIS": "Disney", "CMCSA": "Comcast", "T": "AT&T", "VZ": "Verizon", "TMUS": "T-Mobile",
    # Hot / High-beta
    "PLTR": "Palantir", "UBER": "Uber", "SQ": "Block", "SHOP": "Shopify",
    "SNOW": "Snowflake", "DKNG": "DraftKings", "SOFI": "SoFi",
    "RIVN": "Rivian", "LCID": "Lucid", "ARM": "ARM", "SMCI": "Super Micro",
    "MSTR": "MicroStrat", "CRWD": "CrowdStrike", "PANW": "Palo Alto",
    # Additional names for scanner
    "DDOG": "Datadog", "WDAY": "Workday", "TTD": "Trade Desk", "SPOT": "Spotify",
    "CVNA": "Carvana", "APP": "AppLovin", "AXON": "Axon", "DELL": "Dell",
    "HPE": "HP Enterp", "HPQ": "HP Inc", "LULU": "Lululemon", "LYV": "Live Nation",
    "PYPL": "PayPal", "VST": "Vistra", "GEV": "GE Vernova", "RKLB": "Rocket Lab",
    "IREN": "IREN", "QBTS": "D-Wave", "RGTI": "Rigetti",
    "EIX": "Edison Intl", "QYLD": "Nasdaq CovCall", "LIN": "Linde", "EA": "EA Games",
    "PNC": "PNC Financial", "AES": "AES Corp", "PCG": "PG&E", "EXC": "Exelon",
    "XEL": "Xcel Energy", "WEC": "WEC Energy", "CMS": "CMS Energy", "ED": "Con Edison",
    "PEG": "PSEG", "EVRG": "Evergy", "CNP": "CenterPoint", "AEE": "Ameren",
    "D": "Dominion", "NEE": "NextEra",
    "BSX": "Boston Sci", "MDT": "Medtronic", "HCA": "HCA Health", "REGN": "Regeneron",
    "BIIB": "Biogen", "ILMN": "Illumina", "IQV": "IQVIA", "DGX": "Quest Diag",
    "CAH": "Cardinal Hlth", "COR": "Cencora",
    "BK": "BNY Mellon", "USB": "US Bancorp", "STT": "State Street",
    "HBAN": "Huntington", "RF": "Regions Fin", "CME": "CME Group",
    "ICE": "Intercont Ex", "NDAQ": "Nasdaq Inc", "SPGI": "S&P Global", "MCO": "Moody's",
    "KR": "Kroger", "DG": "Dollar Gen", "ORLY": "O'Reilly", "AZO": "AutoZone",
    "ROST": "Ross Stores", "TJX": "TJX Cos", "ULTA": "Ulta Beauty",
    "DPZ": "Domino's", "CCL": "Carnival", "MGM": "MGM Resorts", "CZR": "Caesars",
    "GD": "General Dyn", "NOC": "Northrop", "EMR": "Emerson", "ETN": "Eaton",
    "IR": "Ingersoll", "PH": "Parker Hann", "ROK": "Rockwell", "WAB": "Wabtec",
    "FAST": "Fastenal", "ODFL": "Old Dominion",
    "DVN": "Devon Energy", "HAL": "Halliburton", "MPC": "Marathon Pet", "OXY": "Occidental",
    "FANG": "Diamondback", "EA": "EA Games", "TTWO": "Take-Two",
    "AVB": "AvalonBay", "EQR": "Equity Res", "KIM": "Kimco Realty", "REG": "Regency Ctr",
    "FRT": "Fed Realty", "HST": "Host Hotels", "ARE": "Alexandria",
    "FCX": "Freeport-McM", "NUE": "Nucor", "MLM": "Martin Mar", "APD": "Air Products",
    "IFF": "IFF", "AVY": "Avery Denn", "BALL": "Ball Corp", "FMC": "FMC Corp",
    "IDV": "Intl Div ETF", "IEO": "Energy ETF", "JEPI": "JPM Equity Pr",
    "SPYD": "S&P Div ETF", "DBMF": "Managed Fut",
}

# Expanded swing watchlist — indices + all LumiTrade stocks with options
# Used only for swing scans (M/W/Q timeframes). Intraday/scalp uses CORE_TICKERS.
SWING_TICKERS = [
    # Major Indices
    "I:SPX", "I:NDX", "I:XSP", "I:XND",
    "I:DJI", "I:COMP", "I:RUT", "I:RUI",
    "I:DJT", "I:DJU", "I:SOX", "I:BKX", "I:KRX",
    "I:HGX", "I:OSX", "I:NBI", "I:XAU", "I:UTY", "I:DJUSRE",
    # Commodity Indices
    "I:DJCI", "I:DJCIEN", "I:DJCIPM", "I:DJCIIM", "I:DJCIGC", "I:DJCISI",
    "I:DJCICL", "I:DJCING", "I:DJCIHO", "I:DJCIRB", "I:DJCIHG",
    "I:DJCIWH", "I:DJCICN", "I:DJCISY", "I:DJCISB", "I:DJCIKC",
    "I:DJCICT", "I:DJCICC", "I:DJCILH", "I:DJCILC", "I:DJCIFC",
    # Global Indices
    "I:MXEF", "I:MXEA", "I:MXWO", "I:GDOW", "I:EDOW", "I:ADOW",
    "I:DJDVY", "I:QMI", "I:TRAN", "I:MSTAR",
    # ETFs
    "SPY", "QQQ", "IWM", "DIA",
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "GLD", "USO", "AGG", "BITO", "IBIT", "FBTC",
    "IDV", "IEO", "JEPI", "SPYD", "QYLD", "DBMF",
    # Mega-cap Tech
    "AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AVGO", "ORCL", "ADBE", "CRM", "AMD", "INTC", "QCOM", "AMAT",
    "MU", "NFLX", "CSCO", "IBM", "NOW", "INTU", "SNPS", "CDNS",
    # Financials
    "JPM", "V", "MA", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW",
    "AXP", "BX", "KKR", "COIN", "BK", "PNC", "USB", "STT", "HBAN", "RF",
    "CME", "ICE", "NDAQ", "SPGI", "MCO",
    # Health Care
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    "BSX", "MDT", "HCA", "REGN", "BIIB", "ILMN", "IQV", "DGX", "CAH", "COR",
    # Consumer
    "WMT", "COST", "HD", "NKE", "MCD", "SBUX", "TGT", "LOW",
    "PG", "KO", "PEP", "KR", "DG", "ORLY", "AZO", "ROST", "TJX", "ULTA",
    "DPZ", "CCL", "LVS", "MGM", "CZR",
    # Industrials
    "CAT", "DE", "HON", "UPS", "FDX", "BA", "GE", "RTX", "LMT", "GD", "NOC",
    "EMR", "ETN", "IR", "PH", "ROK", "WAB", "FAST", "ODFL",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "DVN", "HAL", "MPC", "OXY", "FANG",
    # Communication / Media
    "DIS", "CMCSA", "T", "VZ", "TMUS", "NFLX", "EA", "TTWO",
    # Real Estate
    "AVB", "EQR", "KIM", "REG", "FRT", "HST", "ARE",
    # Utilities
    "NEE", "D", "PCG", "EXC", "AES", "XEL", "WEC", "CMS", "EIX", "ED", "PEG", "EVRG", "CNP", "AEE",
    # Materials
    "FCX", "NUE", "MLM", "APD", "LIN", "IFF", "AVY", "BALL", "FMC",
    # Hot / High-beta
    "PLTR", "UBER", "SQ", "SHOP", "SNOW", "DKNG", "SOFI",
    "RIVN", "LCID", "ARM", "SMCI", "MSTR", "CRWD", "PANW",
    "DDOG", "WDAY", "TTD", "SPOT", "CVNA", "APP", "AXON",
    "DELL", "HPE", "HPQ", "LULU", "LYV", "PYPL",
    "VST", "GEV", "RKLB", "IREN", "QBTS", "RGTI",
]

# Combined default watchlist
DEFAULT_TICKERS = CORE_TICKERS + CRYPTO_TICKERS

# Granularity mapping: our internal format → Massive API format
# 1h and 4h are aggregated from 5m data to align with market open (9:30 ET)
MASSIVE_TIMESPAN = {
    "1mo": ("1", "month"),
    "1w": ("1", "week"),
    "1d": ("1", "day"),
    "30m": ("30", "minute"),
    "15m": ("15", "minute"),
    "5m": ("5", "minute"),
    "2m": ("2", "minute"),
    "1m": ("1", "minute"),
}

# Timespans that need market-aligned aggregation from 5m data
AGGREGATE_FROM_5M = {"1h", "4h"}

# US market hours in ET → UTC offset (EDT = UTC-4)
MARKET_OPEN_ET = (9, 30)   # 9:30 AM ET = 13:30 UTC
MARKET_CLOSE_ET = (16, 0)  # 4:00 PM ET = 20:00 UTC


class MassiveClient:
    """Massive (Polygon.io) REST API client for stocks and crypto."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        # Candle cache shared across strategies that hit this client. Levels
        # SCALP and INTRADAY both pull 1h bars for the same tickers, etc.
        self._candle_cache: Dict[Tuple[str, str, int], Tuple[float, List[CandleData]]] = {}

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """Make a request to the Massive/Polygon API."""
        params = params or {}
        params["apiKey"] = self.api_key
        url = f"{BASE_URL}{endpoint}"
        resp = self.session.get(url, params=params, timeout=30)
        if not resp.ok:
            logger.error("Massive API error: %s %s - %s", resp.status_code, endpoint, resp.text[:200])
            resp.raise_for_status()
        return resp.json()

    def get_candles(self, ticker: str, timespan: str = "1d",
                    count: int = 100) -> List[CandleData]:
        """Fetch OHLC candles for a ticker. TTL-cached per (ticker, timespan, count).

        Multiple levels-strategy models commonly request the same bars
        (SCALP and INTRADAY both want 1h stocks; SWING and SWING_OPTIONS both
        want 1w/1mo). Cache TTL is per timespan (see CANDLE_CACHE_TTL), tuned
        below the bar interval so we never serve stale-bar data.
        """
        cache_key = (ticker, timespan, count)
        ttl = CANDLE_CACHE_TTL.get(timespan, _DEFAULT_CACHE_TTL)
        cached = self._candle_cache.get(cache_key)
        if cached:
            fetched_at, candles = cached
            if (time.time() - fetched_at) < ttl:
                return candles

        candles = self._get_candles_uncached(ticker, timespan, count)
        if candles:
            self._candle_cache[cache_key] = (time.time(), candles)
        return candles

    def _get_candles_uncached(self, ticker: str, timespan: str = "1d",
                               count: int = 100) -> List[CandleData]:
        """Underlying implementation — hits Polygon. Use get_candles instead."""
        # Detect market type for candle alignment
        # Crypto (24/7): X:BTCUSD, X:ETHUSD etc. — in CRYPTO_TICKERS list
        # Forex (24/5): X:EURUSD, X:GBPCAD etc. — X: prefix but not crypto
        # Stocks/Indices: everything else (9:30-4:00 ET market hours)
        is_crypto = ticker in CRYPTO_TICKERS
        is_forex = ticker.startswith("C:") or (ticker.startswith("X:") and not is_crypto)
        is_stock = not is_crypto and not is_forex

        # 1h and 4h for stocks/indices: aggregate from 5m to align with market open (9:30 ET).
        # DISABLED — running the alignment path makes one extra Polygon call per ticker per
        # refresh, which compounds with rate limits and blocks the whole bot loop. Skipping
        # alignment means the levels strategy uses Polygon-native 1h/4h bars (slightly
        # misaligned to RTH) but the bot loop stays responsive so 2n20 MES/FX can run.
        # Re-enable once we have proper caching/throttling on the alignment path.
        if timespan in AGGREGATE_FROM_5M and (is_stock or is_forex):
            return self._get_market_aligned_candles(ticker, timespan, count)

        # Weekly: always Monday-start (TradingView uses Monday for all markets)
        if timespan == "1w" and not is_crypto:
            return self._get_monday_weekly_candles(ticker, count)

        # Monthly: always calendar month
        if timespan == "1mo" and not is_crypto:
            return self._get_calendar_monthly_candles(ticker, count)

        if timespan in AGGREGATE_FROM_5M:
            # Crypto: use native hour candles (24h market, no alignment needed)
            multiplier = "4" if timespan == "4h" else "1"
            span = "hour"
        else:
            multiplier, span = MASSIVE_TIMESPAN.get(timespan, ("1", "day"))

        # Calculate date range based on count and timespan
        now = datetime.now(timezone.utc)
        if span == "month":
            start = now - timedelta(days=count * 31)
        elif span == "week":
            start = now - timedelta(weeks=count)
        elif span == "day":
            start = now - timedelta(days=count * 1.5)  # buffer for weekends
        else:  # minute
            start = now - timedelta(minutes=count * int(multiplier) * 1.5)

        start_str = start.strftime("%Y-%m-%d")
        end_str = now.strftime("%Y-%m-%d")

        # Fetch newest-first with sort=desc so a small `limit` keeps the
        # MOST RECENT bars. Previously sort=asc + limit=count+10 returned the
        # oldest bars in the date window — a 5m chart could be hours stale.
        data = self._request(
            f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{span}/{start_str}/{end_str}",
            params={"adjusted": "true", "sort": "desc", "limit": min(count + 10, 50000)},
        )

        results = data.get("results", [])
        candles = []
        for bar in results:
            candles.append(CandleData(
                open=float(bar["o"]),
                high=float(bar["h"]),
                low=float(bar["l"]),
                close=float(bar["c"]),
                timestamp=str(bar.get("t", 0) / 1000),  # ms → seconds
            ))
        # Polygon returned newest→oldest; flip so charts get oldest→newest.
        candles.reverse()

        return candles

    def _get_market_aligned_candles(self, ticker: str, timespan: str,
                                     count: int) -> List[CandleData]:
        """Build market-aligned 1h or 4h candles from 5m data.

        Stock market hourly candles should start at 9:30 AM ET (market open):
          1h:  9:30-10:29, 10:30-11:29, 11:30-12:29, 12:30-1:29, 1:30-2:29, 2:30-3:29, 3:30-3:59
          4h:  9:30-1:29, 1:30-3:59

        We pull 5m bars from Massive, filter to regular market hours,
        then aggregate into market-aligned buckets.
        """
        is_forex = ticker.startswith("C:")

        # How many trading days of 5m data do we need?
        if is_forex:
            # Forex: 24h/day, ~288 5m bars/day
            if timespan == "4h":
                bars_per_day = 6
            else:
                bars_per_day = 24
        else:
            if timespan == "4h":
                bars_per_day = 2  # two 4h candles per session
            else:
                bars_per_day = 7  # seven 1h candles per session (9:30-3:59)

        days_needed = max(5, (count // bars_per_day) + 3)  # buffer for weekends
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days_needed * 1.5)

        # Fetch 5m bars — sort=desc so newest come back first. Polygon caps
        # responses well below limit=50000 in practice (~14k bars), so asc
        # would truncate the LATEST month of data instead of the oldest.
        data = self._request(
            f"/v2/aggs/ticker/{ticker}/range/5/minute/{start.strftime('%Y-%m-%d')}/{now.strftime('%Y-%m-%d')}",
            params={"adjusted": "true", "sort": "desc", "limit": 50000},
        )

        bars_5m = data.get("results", [])
        if not bars_5m:
            return []
        # Aggregation code below expects oldest-first
        bars_5m.reverse()

        if is_forex:
            # Forex trades 24h — use all bars, no market hours filter
            market_bars = bars_5m
        else:
            # Stock market hours in UTC (EDT: ET + 4h)
            # 9:30 ET = 13:30 UTC, 16:00 ET = 20:00 UTC
            market_open_utc = (13, 30)
            market_close_utc = (20, 0)

            market_bars = []
            for bar in bars_5m:
                dt = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
                bar_minutes = dt.hour * 60 + dt.minute
                open_minutes = market_open_utc[0] * 60 + market_open_utc[1]
                close_minutes = market_close_utc[0] * 60 + market_close_utc[1]
                if open_minutes <= bar_minutes < close_minutes:
                    market_bars.append(bar)

        if not market_bars:
            return []

        # Determine bucket boundaries
        if timespan == "1h":
            bucket_minutes = 60
        else:  # 4h
            bucket_minutes = 240

        # Group bars into buckets
        buckets = {}  # key = (date_str, bucket_index) → list of bars

        if is_forex:
            # Forex: clock-aligned buckets (00:00, 01:00, ... for 1h)
            for bar in market_bars:
                dt = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
                date_key = dt.strftime("%Y-%m-%d")
                minutes_since_midnight = dt.hour * 60 + dt.minute
                bucket_idx = minutes_since_midnight // bucket_minutes
                key = (date_key, bucket_idx)
                if key not in buckets:
                    buckets[key] = []
                buckets[key].append(bar)
        else:
            # Stocks: market-open-aligned buckets (9:30 ET start)
            market_open_utc = (13, 30)
            for bar in market_bars:
                dt = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
                date_key = dt.strftime("%Y-%m-%d")
                minutes_since_open = (dt.hour * 60 + dt.minute) - (market_open_utc[0] * 60 + market_open_utc[1])
                bucket_idx = minutes_since_open // bucket_minutes
                key = (date_key, bucket_idx)
                if key not in buckets:
                    buckets[key] = []
                buckets[key].append(bar)

        # Aggregate each bucket into a single candle
        candles = []
        for key in sorted(buckets.keys()):
            bars = buckets[key]
            if not bars:
                continue

            candle = CandleData(
                open=float(bars[0]["o"]),
                high=max(float(b["h"]) for b in bars),
                low=min(float(b["l"]) for b in bars),
                close=float(bars[-1]["c"]),
                timestamp=str(bars[0]["t"] / 1000),
            )
            candles.append(candle)

        # Return the last N candles
        return candles[-count:] if len(candles) > count else candles

    def _get_calendar_monthly_candles(self, ticker: str, count: int) -> List[CandleData]:
        """Build calendar-month candles from daily data.

        Massive/Polygon monthly candles don't always align with calendar months.
        This aggregates daily bars into proper Jan, Feb, Mar, etc. candles.
        """
        days_needed = count * 31 + 10
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days_needed)

        data = self._request(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start.strftime('%Y-%m-%d')}/{now.strftime('%Y-%m-%d')}",
            params={"adjusted": "true", "sort": "asc", "limit": 50000},
        )

        daily_bars = data.get("results", [])
        if not daily_bars:
            return []

        # Group daily bars by (year, month)
        months = {}
        for bar in daily_bars:
            dt = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
            key = (dt.year, dt.month)
            if key not in months:
                months[key] = []
            months[key].append(bar)

        # Aggregate each month
        candles = []
        for key in sorted(months.keys()):
            bars = months[key]
            if not bars:
                continue
            candle = CandleData(
                open=float(bars[0]["o"]),
                high=max(float(b["h"]) for b in bars),
                low=min(float(b["l"]) for b in bars),
                close=float(bars[-1]["c"]),
                timestamp=str(bars[0]["t"] / 1000),  # First trading day of month
            )
            candles.append(candle)

        return candles[-count:] if len(candles) > count else candles

    def _get_monday_weekly_candles(self, ticker: str, count: int) -> List[CandleData]:
        """Build Monday-start weekly candles from daily data.

        Massive/Polygon weekly candles start on Sunday, but TradingView
        and most traders use Monday-start weeks. This aggregates daily
        bars into Monday-Friday weekly candles.
        """
        # Fetch enough daily bars
        days_needed = count * 7 + 10
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days_needed)

        data = self._request(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start.strftime('%Y-%m-%d')}/{now.strftime('%Y-%m-%d')}",
            params={"adjusted": "true", "sort": "asc", "limit": 50000},
        )

        daily_bars = data.get("results", [])
        if not daily_bars:
            return []

        # Group daily bars by ISO week (Monday-start)
        weeks = {}
        for bar in daily_bars:
            dt = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
            # ISO calendar: week starts Monday
            iso_year, iso_week, _ = dt.isocalendar()
            key = (iso_year, iso_week)
            if key not in weeks:
                weeks[key] = []
            weeks[key].append(bar)

        # Aggregate each week
        candles = []
        for key in sorted(weeks.keys()):
            bars = weeks[key]
            if not bars:
                continue
            candle = CandleData(
                open=float(bars[0]["o"]),
                high=max(float(b["h"]) for b in bars),
                low=min(float(b["l"]) for b in bars),
                close=float(bars[-1]["c"]),
                timestamp=str(bars[0]["t"] / 1000),  # Monday's timestamp
            )
            candles.append(candle)

        return candles[-count:] if len(candles) > count else candles

    def get_price(self, ticker: str) -> Optional[float]:
        """Get the current/latest price for a ticker.

        Uses snapshot for stocks, last trade for crypto.
        """
        try:
            if ticker.startswith("X:"):
                # Crypto — use snapshot
                pair = ticker.replace("X:", "")
                data = self._request(f"/v2/snapshot/locale/global/markets/crypto/tickers/{ticker}")
                day = data.get("ticker", {}).get("day", {})
                if day.get("c"):
                    return float(day["c"])
                prev = data.get("ticker", {}).get("prevDay", {})
                return float(prev.get("c", 0)) or None
            elif ticker.startswith("C:") or ticker.startswith("I:"):
                # Forex / Commodities / Indices — use v3 universal snapshot
                data = self._request(f"/v3/snapshot", params={"ticker.any_of": ticker})
                results = data.get("results", [])
                if results:
                    session = results[0].get("session", {})
                    return float(session.get("close", 0)) or float(results[0].get("value", 0)) or None
                return None
            else:
                # Stocks — use snapshot
                data = self._request(
                    f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
                )
                day = data.get("ticker", {}).get("day", {})
                if day.get("c"):
                    return float(day["c"])
                # Fallback to previous day close
                prev = data.get("ticker", {}).get("prevDay", {})
                return float(prev.get("c", 0)) or None
        except Exception as e:
            logger.debug("Could not get price for %s: %s", ticker, e)
            return None

    def batch_get_prices(self, tickers: list) -> dict:
        """Get prices for multiple stock tickers in one call.

        Uses the snapshots endpoint for stocks. Crypto fetched individually.
        """
        prices = {}

        # Split into stocks and crypto
        stocks = [t for t in tickers if not t.startswith("X:")]
        crypto = [t for t in tickers if t.startswith("X:")]

        # Batch stocks via snapshot
        if stocks:
            try:
                data = self._request(
                    "/v2/snapshot/locale/us/markets/stocks/tickers",
                    params={"tickers": ",".join(stocks)},
                )
                for item in data.get("tickers", []):
                    ticker = item.get("ticker", "")
                    day = item.get("day", {})
                    price = day.get("c") or item.get("prevDay", {}).get("c")
                    if price:
                        prices[ticker] = float(price)
            except Exception as e:
                logger.debug("Batch stock price error: %s", e)

        # Crypto individually
        for t in crypto:
            p = self.get_price(t)
            if p:
                prices[t] = p

        return prices

    def validate_connection(self) -> bool:
        """Test that the API key works."""
        try:
            data = self._request("/v2/aggs/ticker/AAPL/prev")
            if data.get("resultsCount", 0) > 0:
                logger.info("Connected to Massive (Polygon) — API key valid")
                return True
        except Exception as e:
            logger.error("Failed to connect to Massive: %s", e)
        return False
