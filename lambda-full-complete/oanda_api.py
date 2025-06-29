import requests
import json
from datetime import datetime
from typing import Dict, List, Optional, Union

class OandaAPI:
    """
    Oanda brokerage integration class for trading operations
    """
    
    def __init__(self, api_key: str, account_id: str, environment: str = "practice"):
        """
        Initialize Oanda API client
        
        Args:
            api_key: Your Oanda API token
            account_id: Your Oanda account ID
            environment: 'practice' for demo or 'live' for real trading
        """
        self.api_key = api_key
        self.account_id = account_id
        self.environment = environment
        
        # Set base URLs
        if environment == "practice":
            self.api_url = "https://api-fxpractice.oanda.com"
            self.stream_url = "https://stream-fxpractice.oanda.com"
        else:
            self.api_url = "https://api-fxtrade.oanda.com"
            self.stream_url = "https://stream-fxtrade.oanda.com"
        
        # Headers for API requests
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def get_account_info(self) -> Dict:
        """Get account information"""
        url = f"{self.api_url}/v3/accounts/{self.account_id}"
        response = requests.get(url, headers=self.headers)
        return self._handle_response(response)
    
    def get_account_summary(self) -> Dict:
        """Get account summary including balance, equity, margin"""
        url = f"{self.api_url}/v3/accounts/{self.account_id}/summary"
        response = requests.get(url, headers=self.headers)
        return self._handle_response(response)
    
    def get_instruments(self) -> List[Dict]:
        """Get all tradeable instruments"""
        url = f"{self.api_url}/v3/accounts/{self.account_id}/instruments"
        response = requests.get(url, headers=self.headers)
        data = self._handle_response(response)
        return data.get('instruments', [])
    
    def get_current_prices(self, instruments: List[str]) -> Dict:
        """
        Get current bid/ask prices for instruments
        
        Args:
            instruments: List of instrument names (e.g., ['EUR_USD', 'GBP_USD'])
        """
        instruments_str = ",".join(instruments)
        url = f"{self.api_url}/v3/accounts/{self.account_id}/pricing"
        params = {"instruments": instruments_str}
        
        response = requests.get(url, headers=self.headers, params=params)
        return self._handle_response(response)
    
    def get_candles(self, instrument: str, granularity: str = "M1", 
                   count: int = 100, price: str = "M") -> Dict:
        """
        Get historical candle data
        
        Args:
            instrument: Instrument name (e.g., 'EUR_USD')
            granularity: Timeframe (S5, S10, S15, S30, M1, M5, M15, M30, H1, H4, H12, D, W, M)
            count: Number of candles (max 5000)
            price: Price type ('M'=midpoint, 'B'=bid, 'A'=ask, 'BA'=bid+ask)
        """
        url = f"{self.api_url}/v3/instruments/{instrument}/candles"
        params = {
            "granularity": granularity,
            "count": count,
            "price": price
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        return self._handle_response(response)
    
    def place_market_order(self, instrument: str, units: int, 
                          stop_loss: Optional[float] = None,
                          take_profit: Optional[float] = None) -> Dict:
        """
        Place a market order
        
        Args:
            instrument: Instrument to trade (e.g., 'EUR_USD')
            units: Number of units (positive for buy, negative for sell)
            stop_loss: Stop loss price
            take_profit: Take profit price
        """
        order_data = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units)
            }
        }
        
        # Add stop loss if provided
        if stop_loss:
            order_data["order"]["stopLossOnFill"] = {
                "price": str(stop_loss)
            }
        
        # Add take profit if provided
        if take_profit:
            order_data["order"]["takeProfitOnFill"] = {
                "price": str(take_profit)
            }
        
        url = f"{self.api_url}/v3/accounts/{self.account_id}/orders"
        response = requests.post(url, headers=self.headers, json=order_data)
        return self._handle_response(response)
    
    def place_limit_order(self, instrument: str, units: int, price: float,
                         stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None) -> Dict:
        """
        Place a limit order
        
        Args:
            instrument: Instrument to trade
            units: Number of units (positive for buy, negative for sell)
            price: Limit price
            stop_loss: Stop loss price
            take_profit: Take profit price
        """
        order_data = {
            "order": {
                "type": "LIMIT",
                "instrument": instrument,
                "units": str(units),
                "price": str(price)
            }
        }
        
        if stop_loss:
            order_data["order"]["stopLossOnFill"] = {
                "price": str(stop_loss)
            }
        
        if take_profit:
            order_data["order"]["takeProfitOnFill"] = {
                "price": str(take_profit)
            }
        
        url = f"{self.api_url}/v3/accounts/{self.account_id}/orders"
        response = requests.post(url, headers=self.headers, json=order_data)
        return self._handle_response(response)
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        url = f"{self.api_url}/v3/accounts/{self.account_id}/openPositions"
        response = requests.get(url, headers=self.headers)
        data = self._handle_response(response)
        return data.get('positions', [])
    
    def get_open_orders(self) -> List[Dict]:
        """Get all pending orders"""
        url = f"{self.api_url}/v3/accounts/{self.account_id}/orders"
        response = requests.get(url, headers=self.headers)
        data = self._handle_response(response)
        return data.get('orders', [])
    
    def close_position(self, instrument: str, units: str = "ALL") -> Dict:
        """
        Close a position
        
        Args:
            instrument: Instrument name
            units: Number of units to close or "ALL"
        """
        # Determine if we're closing long or short position
        positions = self.get_open_positions()
        long_units = short_units = "0"
        
        for pos in positions:
            if pos['instrument'] == instrument:
                if float(pos['long']['units']) != 0:
                    long_units = units if units != "ALL" else pos['long']['units']
                if float(pos['short']['units']) != 0:
                    short_units = units if units != "ALL" else pos['short']['units']
        
        close_data = {}
        if long_units != "0":
            close_data["longUnits"] = long_units
        if short_units != "0":
            close_data["shortUnits"] = short_units
        
        url = f"{self.api_url}/v3/accounts/{self.account_id}/positions/{instrument}/close"
        response = requests.put(url, headers=self.headers, json=close_data)
        return self._handle_response(response)
    
    def cancel_order(self, order_id: str) -> Dict:
        """Cancel a pending order"""
        url = f"{self.api_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel"
        response = requests.put(url, headers=self.headers)
        return self._handle_response(response)
    
    def get_transaction_history(self, count: int = 100) -> List[Dict]:
        """Get recent transactions"""
        url = f"{self.api_url}/v3/accounts/{self.account_id}/transactions"
        params = {"count": count}
        
        response = requests.get(url, headers=self.headers, params=params)
        data = self._handle_response(response)
        return data.get('transactions', [])
    
    def _handle_response(self, response: requests.Response) -> Dict:
        """Handle API response and errors"""
        try:
            data = response.json()
            if response.status_code >= 400:
                error_msg = data.get('errorMessage', f'HTTP {response.status_code}')
                raise Exception(f"Oanda API Error: {error_msg}")
            return data
        except json.JSONDecodeError:
            raise Exception(f"Invalid JSON response: {response.text}")


# Example usage and utility functions
class OandaTrader:
    """High-level trading interface"""
    
    def __init__(self, api_key: str, account_id: str, environment: str = "practice"):
        self.api = OandaAPI(api_key, account_id, environment)
    
    def buy_market(self, instrument: str, units: int, 
                   stop_loss_pips: Optional[int] = None,
                   take_profit_pips: Optional[int] = None) -> Dict:
        """
        Buy at market price with pip-based stops
        
        Args:
            instrument: Currency pair
            units: Position size
            stop_loss_pips: Stop loss in pips
            take_profit_pips: Take profit in pips
        """
        current_price = self._get_current_price(instrument, 'ask')
        pip_value = self._get_pip_value(instrument)
        
        stop_loss = None
        take_profit = None
        
        if stop_loss_pips:
            stop_loss = current_price - (stop_loss_pips * pip_value)
        
        if take_profit_pips:
            take_profit = current_price + (take_profit_pips * pip_value)
        
        return self.api.place_market_order(instrument, units, stop_loss, take_profit)
    
    def sell_market(self, instrument: str, units: int,
                   stop_loss_pips: Optional[int] = None,
                   take_profit_pips: Optional[int] = None) -> Dict:
        """
        Sell at market price with pip-based stops
        """
        current_price = self._get_current_price(instrument, 'bid')
        pip_value = self._get_pip_value(instrument)
        
        stop_loss = None
        take_profit = None
        
        if stop_loss_pips:
            stop_loss = current_price + (stop_loss_pips * pip_value)
        
        if take_profit_pips:
            take_profit = current_price - (take_profit_pips * pip_value)
        
        return self.api.place_market_order(instrument, -units, stop_loss, take_profit)
    
    def _get_current_price(self, instrument: str, price_type: str) -> float:
        """Get current bid or ask price"""
        pricing = self.api.get_current_prices([instrument])
        for price in pricing.get('prices', []):
            if price['instrument'] == instrument:
                return float(price[price_type])
        raise Exception(f"Price not found for {instrument}")
    
    def _get_pip_value(self, instrument: str) -> float:
        """Get pip value for instrument (simplified)"""
        if 'JPY' in instrument:
            return 0.01  # JPY pairs
        else:
            return 0.0001  # Most other pairs


# Example usage
if __name__ == "__main__":
    # Initialize with your credentials
    API_KEY = "your_api_token_here"
    ACCOUNT_ID = "your_account_id_here"
    
    # Create trader instance (use "practice" for demo, "live" for real)
    trader = OandaTrader(API_KEY, ACCOUNT_ID, "practice")
    
    try:
        # Get account info
        account = trader.api.get_account_summary()
        print(f"Account Balance: {account['account']['balance']}")
        print(f"Unrealized PL: {account['account']['unrealizedPL']}")
        
        # Get current prices
        prices = trader.api.get_current_prices(['EUR_USD', 'GBP_USD'])
        for price in prices['prices']:
            print(f"{price['instrument']}: Bid={price['bid']}, Ask={price['ask']}")
        
        # Place a buy order with stops (example - be careful with real money!)
        # order = trader.buy_market('EUR_USD', 1000, stop_loss_pips=20, take_profit_pips=30)
        # print(f"Order placed: {order}")
        
        # Get open positions
        positions = trader.api.get_open_positions()
        for pos in positions:
            print(f"Position: {pos['instrument']} - PL: {pos['unrealizedPL']}")
        
    except Exception as e:
        print(f"Error: {e}")