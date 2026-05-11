"""Oanda API client for trading operations."""

import logging
import requests

logger = logging.getLogger(__name__)

OANDA_ENVIRONMENTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

# Symbol mapping: common symbol format -> Oanda instrument
SYMBOL_MAP = {
    # Forex pairs
    "EURUSD": "EUR_USD",
    "GBPUSD": "GBP_USD",
    "USDJPY": "USD_JPY",
    "USDCHF": "USD_CHF",
    "AUDUSD": "AUD_USD",
    "NZDUSD": "NZD_USD",
    "USDCAD": "USD_CAD",
    "EURGBP": "EUR_GBP",
    "EURJPY": "EUR_JPY",
    "GBPJPY": "GBP_JPY",
    "AUDJPY": "AUD_JPY",
    "EURAUD": "EUR_AUD",
    "EURCHF": "EUR_CHF",
    "GBPCHF": "GBP_CHF",
    "CADJPY": "CAD_JPY",
    # Indices
    "US30": "US30_USD",
    "SPX500": "SPX500_USD",
    "NAS100": "NAS100_USD",
    "UK100": "UK100_GBP",
    "DE30": "DE30_EUR",
    "JP225": "JP225_USD",
    # Commodities
    "XAUUSD": "XAU_USD",
    "XAGUSD": "XAG_USD",
    "WTICOUSD": "WTICO_USD",
    "BCOUSD": "BCO_USD",
    # Crypto
    "BTCUSD": "BTC_USD",
    "ETHUSD": "ETH_USD",
}


def resolve_instrument(symbol: str) -> str:
    """Convert a common symbol format to Oanda instrument name."""
    clean = symbol.upper().replace("/", "").replace("_", "")
    if clean in SYMBOL_MAP:
        return SYMBOL_MAP[clean]
    # Try auto-formatting 6-char forex pairs
    if len(clean) == 6 and "_" not in clean:
        return f"{clean[:3]}_{clean[3:]}"
    return clean


class OandaClient:
    """Oanda REST API v20 client."""

    def __init__(self, account_id: str, api_key: str, environment: str = "practice"):
        self.account_id = account_id
        self.api_key = api_key
        self.base_url = OANDA_ENVIRONMENTS.get(environment, OANDA_ENVIRONMENTS["practice"])
        self.tradeable = set()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "UNIX",
        })
        # Candle cache: {(instrument, granularity, count): (timestamp, result)}
        self._candle_cache = {}
        self._candle_cache_ttl = 25  # seconds — just under the 30s bot loop

    def _request(self, method: str, endpoint: str, json_data: dict = None) -> dict:
        """Make an HTTP request to the Oanda API."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(method, url, json=json_data, timeout=30)
        if not response.ok:
            logger.error("Oanda API error: %s - %s", response.status_code, response.text)
            response.raise_for_status()
        return response.json()

    def validate_connection(self) -> bool:
        """Test that credentials are valid and load tradeable instruments."""
        try:
            result = self.get_account()
            account = result.get("account", {})
            logger.info(
                "Connected to Oanda — Account %s, Balance: %s",
                account.get("id", "?"),
                account.get("balance", "?"),
            )
            # Cache tradeable instruments
            self._load_tradeable_instruments()
            return True
        except Exception as e:
            logger.error("Failed to connect to Oanda: %s", e)
            return False

    def _load_tradeable_instruments(self):
        """Fetch and cache the list of tradeable instruments."""
        try:
            result = self._request("GET", f"/v3/accounts/{self.account_id}/instruments")
            self.tradeable = {i["name"] for i in result.get("instruments", [])}
            logger.info("Loaded %d tradeable instruments", len(self.tradeable))
        except Exception as e:
            logger.warning("Could not load instruments: %s", e)
            self.tradeable = set()

    def is_tradeable(self, instrument: str) -> bool:
        """Check if an instrument is tradeable on this account."""
        if not self.tradeable:
            return True  # If we couldn't load the list, don't block
        return instrument in self.tradeable

    def get_account(self) -> dict:
        """Get account details including balance."""
        return self._request("GET", f"/v3/accounts/{self.account_id}")

    def get_price(self, instrument: str) -> dict:
        """Get current price for an instrument."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/pricing?instruments={instrument}")

    def get_candles(self, instrument: str, granularity: str = "D", count: int = 2) -> list:
        """Get recent candles for an instrument. Results cached for 25 seconds.

        Args:
            instrument: e.g. "EUR_USD"
            granularity: "M" (monthly), "W" (weekly), "D" (daily), "H4", "H1", etc.
            count: Number of candles to return.

        Returns:
            List of candle dicts with mid OHLC.
        """
        import time as _time
        cache_key = (instrument, granularity, count)
        cached = self._candle_cache.get(cache_key)
        if cached:
            ts, data = cached
            if _time.time() - ts < self._candle_cache_ttl:
                return data

        result = self._request(
            "GET",
            f"/v3/instruments/{instrument}/candles?granularity={granularity}&count={count}&price=M",
        )
        candles = result.get("candles", [])
        self._candle_cache[cache_key] = (_time.time(), candles)
        return candles

    def create_order(self, order_data: dict) -> dict:
        """Create a new order."""
        return self._request("POST", f"/v3/accounts/{self.account_id}/orders", {"order": order_data})

    def get_open_positions(self) -> dict:
        """Get all open positions."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/openPositions")

    def get_orders(self) -> dict:
        """Get all pending orders."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/pendingOrders")

    def get_trades(self, state: str = "ALL", count: int = 50) -> dict:
        """Get trades. state: OPEN, CLOSED, ALL."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/trades?state={state}&count={count}")

    def get_trade(self, trade_id: str) -> dict:
        """Get a specific trade by ID."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/trades/{trade_id}")

    def get_transactions(self, page_size: int = 100, type_filter: str = "") -> dict:
        """Get recent transactions. type_filter e.g. 'ORDER_FILL,STOP_LOSS_ORDER'."""
        url = f"/v3/accounts/{self.account_id}/transactions?pageSize={page_size}"
        if type_filter:
            url += f"&type={type_filter}"
        return self._request("GET", url)

    def get_transactions_since(self, since_id: str) -> dict:
        """Get transactions since a given transaction ID."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/transactions/sinceid?id={since_id}")

    def close_position(self, instrument: str) -> dict:
        """Close all positions for an instrument."""
        return self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/positions/{instrument}/close",
            {"longUnits": "ALL", "shortUnits": "ALL"},
        )

    def close_trade(self, trade_id: str, units: str = "ALL") -> dict:
        """Close a single open trade by its Oanda trade ID. Use this when
        multiple trades exist on the same instrument and only one should be
        flattened (close_position would close all of them).

        units defaults to "ALL"; pass a numeric string for partial close."""
        return self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/trades/{trade_id}/close",
            {"units": str(units)},
        )
