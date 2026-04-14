"""Charles Schwab API client — OAuth2 auth + market data."""

import base64
import json
import logging
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from .candle_classifier import CandleData

logger = logging.getLogger(__name__)

BASE_URL = "https://api.schwabapi.com"
AUTH_URL = f"{BASE_URL}/v1/oauth/authorize"
TOKEN_URL = f"{BASE_URL}/v1/oauth/token"
MARKET_DATA_URL = f"{BASE_URL}/marketdata/v1"

# Token file — persists tokens across restarts
TOKEN_FILE = "schwab_tokens.json"


class SchwabAuth:
    """Handles OAuth2 authorization code flow for Schwab API."""

    def __init__(self, client_id: str, client_secret: str,
                 redirect_uri: str = "https://127.0.0.1",
                 token_file: str = TOKEN_FILE):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_file = Path(token_file)
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = 0
        self._load_tokens()

    def _basic_auth(self) -> str:
        """Base64 encode client_id:client_secret for token requests."""
        credentials = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(credentials.encode()).decode()

    def _load_tokens(self):
        """Load saved tokens from disk."""
        if self.token_file.exists():
            try:
                data = json.loads(self.token_file.read_text())
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.token_expiry = data.get("token_expiry", 0)
                logger.info("Loaded Schwab tokens from %s", self.token_file)
            except (json.JSONDecodeError, OSError):
                pass

    def _save_tokens(self):
        """Save tokens to disk."""
        try:
            self.token_file.write_text(json.dumps({
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_expiry": self.token_expiry,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2))
        except OSError as e:
            logger.error("Failed to save Schwab tokens: %s", e)

    def get_authorization_url(self) -> str:
        """Build the URL the user must visit to authorize the app."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "scope": "readonly",
            "redirect_uri": self.redirect_uri,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, auth_code: str) -> bool:
        """Exchange authorization code for access + refresh tokens.

        Args:
            auth_code: The code from the redirect URL after user authorizes.

        Returns:
            True if tokens were obtained successfully.
        """
        resp = requests.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._basic_auth()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": self.redirect_uri,
            },
            timeout=30,
        )

        if resp.ok:
            data = resp.json()
            self.access_token = data["access_token"]
            self.refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 1800)  # Default 30 min
            self.token_expiry = time.time() + expires_in - 60  # Refresh 1 min early
            self._save_tokens()
            logger.info("Schwab OAuth2 tokens obtained — expires in %ds", expires_in)
            return True
        else:
            logger.error("Schwab token exchange failed: %s - %s", resp.status_code, resp.text)
            return False

    def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            logger.warning("No refresh token available — user must re-authorize")
            return False

        resp = requests.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._basic_auth()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )

        if resp.ok:
            data = resp.json()
            self.access_token = data["access_token"]
            if data.get("refresh_token"):
                self.refresh_token = data["refresh_token"]
            expires_in = data.get("expires_in", 1800)
            self.token_expiry = time.time() + expires_in - 60
            self._save_tokens()
            logger.debug("Schwab access token refreshed — expires in %ds", expires_in)
            return True
        else:
            logger.error("Schwab token refresh failed: %s - %s", resp.status_code, resp.text)
            return False

    def get_valid_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if needed."""
        if self.access_token and time.time() < self.token_expiry:
            return self.access_token

        if self.refresh_token:
            if self.refresh_access_token():
                return self.access_token

        logger.warning("Schwab token expired — user must re-authorize")
        return None

    @property
    def is_authenticated(self) -> bool:
        return self.access_token is not None

    def authorize_interactive(self):
        """Run the interactive authorization flow.

        Opens browser for user to log in, then prompts for the redirect URL.
        """
        auth_url = self.get_authorization_url()
        print(f"\n{'='*60}")
        print("Schwab Authorization Required")
        print(f"{'='*60}")
        print(f"\n1. Opening browser to Schwab login...")
        print(f"2. Log in and authorize the app")
        print(f"3. You'll be redirected to {self.redirect_uri}")
        print(f"4. Copy the FULL URL from your browser's address bar")
        print(f"5. Paste it below\n")

        webbrowser.open(auth_url)

        redirect_url = input("Paste the redirect URL here: ").strip()

        # Extract the auth code from the URL
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]

        if not code:
            # Maybe they pasted just the code
            code = redirect_url

        if self.exchange_code(code):
            print("Authorization successful! Tokens saved.")
            return True
        else:
            print("Authorization failed. Check your credentials.")
            return False


class SchwabMarketData:
    """Schwab Market Data API client."""

    def __init__(self, auth: SchwabAuth):
        self.auth = auth
        self.session = requests.Session()

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """Make an authenticated request to the Schwab Market Data API."""
        token = self.auth.get_valid_token()
        if not token:
            raise RuntimeError("No valid Schwab access token — authorize first")

        self.session.headers["Authorization"] = f"Bearer {token}"
        url = f"{MARKET_DATA_URL}{endpoint}"
        resp = self.session.get(url, params=params, timeout=30)
        if not resp.ok:
            logger.error("Schwab API error: %s - %s", resp.status_code, resp.text[:200])
            resp.raise_for_status()
        return resp.json()

    def get_quote(self, symbol: str) -> Optional[dict]:
        """Get a real-time quote for a symbol."""
        try:
            data = self._request(f"/{symbol}/quotes")
            return data.get(symbol, data)
        except Exception as e:
            logger.debug("Could not get Schwab quote for %s: %s", symbol, e)
            return None

    def get_quotes(self, symbols: list) -> dict:
        """Get quotes for multiple symbols."""
        try:
            data = self._request("/quotes", params={
                "symbols": ",".join(symbols),
            })
            return data
        except Exception as e:
            logger.debug("Could not get Schwab quotes: %s", e)
            return {}

    def get_price_history(self, symbol: str, period_type: str = "month",
                          period: int = 1, frequency_type: str = "daily",
                          frequency: int = 1) -> List[CandleData]:
        """Get price history candles.

        Args:
            symbol: e.g. "AAPL"
            period_type: "day", "month", "year", "ytd"
            period: number of periods
            frequency_type: "minute", "daily", "weekly", "monthly"
            frequency: 1, 5, 10, 15, 30 (for minute); 1 (for others)

        Returns:
            List of CandleData.
        """
        try:
            data = self._request(f"/pricehistory", params={
                "symbol": symbol,
                "periodType": period_type,
                "period": period,
                "frequencyType": frequency_type,
                "frequency": frequency,
            })

            candles = []
            for bar in data.get("candles", []):
                candles.append(CandleData(
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    timestamp=str(bar.get("datetime", 0) / 1000),
                ))
            return candles
        except Exception as e:
            logger.debug("Could not get Schwab price history for %s: %s", symbol, e)
            return []

    def get_movers(self, index: str = "$SPX", direction: str = "up",
                   change: str = "percent") -> list:
        """Get market movers.

        Args:
            index: "$SPX", "$DJI", "$COMPX"
            direction: "up" or "down"
            change: "percent" or "value"
        """
        try:
            data = self._request(f"/movers/{index}", params={
                "direction": direction,
                "change": change,
            })
            return data.get("screeners", [])
        except Exception as e:
            logger.debug("Could not get Schwab movers: %s", e)
            return []

    def validate_connection(self) -> bool:
        """Test that the connection works."""
        try:
            data = self.get_quote("AAPL")
            if data:
                logger.info("Connected to Schwab Market Data API")
                return True
        except Exception as e:
            logger.error("Schwab connection test failed: %s", e)
        return False
