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
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "UNIX",
        })

    def _request(self, method: str, endpoint: str, json_data: dict = None) -> dict:
        """Make an HTTP request to the Oanda API."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(method, url, json=json_data, timeout=30)
        if not response.ok:
            logger.error("Oanda API error: %s - %s", response.status_code, response.text)
            response.raise_for_status()
        return response.json()

    def validate_connection(self) -> bool:
        """Test that credentials are valid by fetching account info."""
        try:
            result = self.get_account()
            account = result.get("account", {})
            logger.info(
                "Connected to Oanda — Account %s, Balance: %s",
                account.get("id", "?"),
                account.get("balance", "?"),
            )
            return True
        except Exception as e:
            logger.error("Failed to connect to Oanda: %s", e)
            return False

    def get_account(self) -> dict:
        """Get account details including balance."""
        return self._request("GET", f"/v3/accounts/{self.account_id}")

    def get_price(self, instrument: str) -> dict:
        """Get current price for an instrument."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/pricing?instruments={instrument}")

    def create_order(self, order_data: dict) -> dict:
        """Create a new order."""
        return self._request("POST", f"/v3/accounts/{self.account_id}/orders", {"order": order_data})

    def get_open_positions(self) -> dict:
        """Get all open positions."""
        return self._request("GET", f"/v3/accounts/{self.account_id}/openPositions")

    def close_position(self, instrument: str) -> dict:
        """Close all positions for an instrument."""
        return self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/positions/{instrument}/close",
            {"longUnits": "ALL", "shortUnits": "ALL"},
        )
