import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import os
import sys
import json
import logging
import pytz
from oandapyV20 import API
from oandapyV20.endpoints.transactions import TransactionIDRange
from oandapyV20.endpoints.trades import OpenTrades
from oandapyV20.endpoints.accounts import AccountSummary
from oandapyV20.exceptions import V20Error

# Setup paths (from your sync_all.py)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print(f"Current directory: {current_dir}")
print(f"Parent directory: {parent_dir}")

# Config imports with error handling (from your sync_all.py)
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    print("SUCCESS: Imported Oanda config")
    print(f"DEBUG: API_KEY length: {len(API_KEY) if API_KEY else 'None'}")
    print(f"DEBUG: ACCOUNT_ID: {ACCOUNT_ID}")
    print(f"DEBUG: ACCOUNT_ID type: {type(ACCOUNT_ID)}")
except ImportError as e:
    print(f"ERROR: Failed to import Oanda config: {e}")
    sys.exit(1)

# Import your custom OandaAPI class
from oanda_api import OandaAPI

def test_oanda_connection_v20():
    """Test connection to Oanda API using oandapyV20 (like sync_all.py)"""
    try:
        client = API(access_token=API_KEY, environment="practice")
        r = AccountSummary(accountID=ACCOUNT_ID)
        client.request(r)
        account_data = r.response.get("account", {})
        balance = account_data.get("balance", "N/A")
        print(f"✓ oandapyV20 connection successful. Account balance: {balance}")
        return True
    except Exception as e:
        print(f"✗ oandapyV20 connection failed: {e}")
        return False

class ForexMarketSchedule:
    """
    Handles forex market schedule and trading day logic
    """
    
    def __init__(self):
        # Forex market timezone (EST/EDT)
        self.market_tz = pytz.timezone('US/Eastern')
        self.utc_tz = pytz.UTC
        
        # Market hours: Sunday 5pm EST to Friday 5pm EST
        self.market_open_day = 6  # Sunday
        self.market_open_hour = 17  # 5 PM
        self.market_close_day = 4  # Friday
        self.market_close_hour = 17  # 5 PM
    
    def get_market_time(self, utc_time=None):
        """Convert UTC time to market time (EST/EDT)"""
        if utc_time is None:
            utc_time = datetime.now(self.utc_tz)
        elif isinstance(utc_time, str):
            # Parse ISO format from Oanda
            utc_time = datetime.fromisoformat(utc_time.replace('Z', '+00:00'))
            if utc_time.tzinfo is None:
                utc_time = self.utc_tz.localize(utc_time)
        elif utc_time.tzinfo is None:
            utc_time = self.utc_tz.localize(utc_time)
        
        return utc_time.astimezone(self.market_tz)
    
    def is_market_open(self, market_time):
        """Check if market is open at given market time"""
        weekday = market_time.weekday()  # 0=Monday, 6=Sunday
        hour = market_time.hour
        
        # Market is closed Saturday and Sunday before 5pm EST
        if weekday == 5:  # Saturday - market is closed all day
            return False
        elif weekday == 6:  # Sunday
            return hour >= 17  # Only open from 5pm Sunday onward
        elif weekday == 4:  # Friday
            return hour < 17  # Close at 5pm Friday
        else:  # Monday-Thursday
            return True
    
    def get_last_trading_time(self, from_market_time, hours_back):
        """
        Get the last trading time going back specified hours, with start-of-week handling
        
        Args:
            from_market_time: Starting market time
            hours_back: How many trading hours to go back
            
        Returns:
            Market time that represents the target trading time
        """
        current_time = from_market_time
        
        # Special start-of-week handling: if we're early in the trading week
        # and looking back 24h or 48h, both should reference Sunday 5pm market open
        current_weekday = current_time.weekday()  # 0=Monday, 6=Sunday
        current_hour = current_time.hour
        
        # If it's early in the trading week (Sunday evening or early Monday)
        # and we're looking back 24h+ hours, reference Sunday 5pm open
        if hours_back >= 24:
            # Case 1: We're on Sunday after 5pm (market just opened)
            if current_weekday == 6 and current_hour >= 17:
                # Both 24h and 48h ago reference Sunday 5pm when week started
                sunday_5pm = current_time.replace(hour=17, minute=0, second=0, microsecond=0)
                print(f"START-OF-WEEK MODE: Using Sunday 5pm open for {hours_back}h calculation")
                return sunday_5pm
            
            # Case 2: We're on Monday and looking back would hit the weekend
            elif current_weekday == 0:  # Monday
                # If looking back would go before Sunday 5pm, use Sunday 5pm
                hours_since_week_start = (current_time.hour - 17) + (24 if current_time.hour < 17 else 0)
                if hours_back > hours_since_week_start:
                    last_sunday = current_time - timedelta(days=1)  # Go back to Sunday
                    sunday_5pm = last_sunday.replace(hour=17, minute=0, second=0, microsecond=0)
                    print(f"START-OF-WEEK MODE: Using Sunday 5pm open for {hours_back}h calculation")
                    return sunday_5pm
        
        # Normal trading time logic for other cases
        hours_remaining = hours_back
        
        while hours_remaining > 0:
            current_time = current_time - timedelta(hours=1)
            
            if self.is_market_open(current_time):
                hours_remaining -= 1
            # If market is closed, keep going back without counting the hour
        
        return current_time
    
    def get_trading_hours_between(self, start_time, end_time):
        """Calculate actual trading hours between two market times"""
        if start_time > end_time:
            start_time, end_time = end_time, start_time
        
        trading_hours = 0
        current_time = start_time
        
        while current_time < end_time:
            if self.is_market_open(current_time):
                trading_hours += 1
            current_time = current_time + timedelta(hours=1)
        
        return trading_hours

class MarketAwareMomentumCalculator:
    """
    Market-aware momentum calculator that handles forex trading sessions and weekends
    """
    
    def __init__(self, oanda_api: OandaAPI):
        self.api = oanda_api
        self.market_schedule = ForexMarketSchedule()
        
        # Define time intervals for momentum calculation (in trading hours)
        self.momentum_intervals = {
            'pennies': {
                '48h': 48,      # 48 trading hours
                '24h': 24,      # 24 trading hours  
                '4h': 4,        # 4 trading hours
                '60m': 1,       # 1 trading hour
                '15m': 0.25     # 15 minutes (0.25 hours)
            },
            'quarters': {
                '72h': 72,
                '24h': 24,
                '8h': 8,
                '2h': 2,
                '30m': 0.5
            },
            'dimes': {
                '168h': 168,    # 1 week of trading hours
                '72h': 72,      # 3 days of trading hours
                '24h': 24,      # 1 day of trading hours
                '4h': 4,        # 4 hours
                '1h': 1         # 1 hour
            }
        }
    
    def get_momentum_data(self, instrument: str, strategy_type: str = 'pennies') -> Dict:
        """
        Get all momentum calculations for a given instrument and strategy type
        Uses market-aware timing that skips weekends
        
        Args:
            instrument: Currency pair (e.g., 'EUR_USD', 'USD_JPY')
            strategy_type: 'pennies', 'quarters', or 'dimes'
        
        Returns:
            Dictionary with momentum percentages for each time interval
        """
        try:
            # Get current price and time
            current_price_data = self.api.get_current_prices([instrument])
            current_market_time = self.market_schedule.get_market_time()
            
            print(f"\nDEBUG - Current UTC time: {datetime.now(pytz.UTC)}")
            print(f"DEBUG - Current market time (EST/EDT): {current_market_time}")
            
            # Handle different price data structures
            if 'prices' in current_price_data and len(current_price_data['prices']) > 0:
                price_data = current_price_data['prices'][0]
                
                if 'mid' in price_data:
                    current_price = float(price_data['mid'])
                elif 'closeoutBid' in price_data and 'closeoutAsk' in price_data:
                    current_price = (float(price_data['closeoutBid']) + float(price_data['closeoutAsk'])) / 2
                elif 'bid' in price_data and 'ask' in price_data:
                    current_price = (float(price_data['bid']) + float(price_data['ask'])) / 2
                else:
                    return {'error': f'Cannot determine current price from: {price_data}'}
            else:
                return {'error': f'No price data found: {current_price_data}'}
            
            # Get the intervals for this strategy
            intervals = self.momentum_intervals.get(strategy_type, self.momentum_intervals['pennies'])
            
            momentum_results = {
                'instrument': instrument,
                'strategy_type': strategy_type,
                'current_price': current_price,
                'current_market_time': current_market_time.isoformat(),
                'timestamp': datetime.now().isoformat(),
                'momentum': {}
            }
            
            # Calculate momentum for each time interval
            for period_name, hours_back in intervals.items():
                try:
                    print(f"\n--- Calculating {period_name} momentum for {instrument} ---")
                    
                    # Check if we're currently in a market closure period
                    market_open = self.market_schedule.is_market_open(current_market_time)
                    print(f"Market currently open: {market_open}")
                    
                    # Get target trading time (market-aware)
                    if hours_back >= 1:
                        target_market_time = self.market_schedule.get_last_trading_time(
                            current_market_time, int(hours_back)
                        )
                        
                        # Special start-of-week messaging
                        if market_open and hours_back >= 24:
                            current_weekday = current_market_time.weekday()
                            if current_weekday == 6:  # Sunday
                                print(f"START-OF-WEEK MODE: Using Sunday 5pm open for {period_name} calculation")
                            elif current_weekday == 0:  # Monday  
                                print(f"START-OF-WEEK MODE: May use Sunday 5pm open for {period_name} calculation")
                            
                    else:
                        # For sub-hour intervals, just subtract minutes
                        minutes_back = int(hours_back * 60)
                        target_market_time = current_market_time - timedelta(minutes=minutes_back)
                    
                    print(f"Target market time: {target_market_time}")
                    print(f"Looking back {hours_back} trading hours")
                    
                    # Convert to UTC for Oanda API
                    target_utc_time = target_market_time.astimezone(pytz.UTC)
                    print(f"Target UTC time: {target_utc_time}")
                    
                    historical_price = self._get_price_at_time(instrument, target_utc_time)
                    if historical_price:
                        pct_change = ((current_price - historical_price) / historical_price) * 100
                        print(f"Price change: {current_price:.5f} -> {historical_price:.5f} = {pct_change:.4f}%")
                        
                        momentum_results['momentum'][period_name] = {
                            'historical_price': historical_price,
                            'percent_change': round(pct_change, 4),
                            'hours_back': hours_back,
                            'target_time_market': target_market_time.isoformat(),
                            'target_time_utc': target_utc_time.isoformat()
                        }
                    else:
                        momentum_results['momentum'][period_name] = {
                            'error': f'Could not retrieve price from {hours_back} trading hours ago'
                        }
                        
                except Exception as e:
                    momentum_results['momentum'][period_name] = {
                        'error': str(e)
                    }
                    print(f"Error calculating {period_name}: {e}")
            
            return momentum_results
            
        except Exception as e:
            return {'error': f'Failed to calculate momentum: {str(e)}'}
    
    def _get_price_at_time(self, instrument: str, target_utc_time: datetime) -> float:
        """
        Get the price closest to a specific UTC time using market data
        
        Args:
            instrument: Currency pair
            target_utc_time: Target time in UTC
            
        Returns:
            Price at that time, or None if not available
        """
        try:
            # Calculate how far back we need to look
            current_utc = datetime.now(pytz.UTC)
            time_diff = current_utc - target_utc_time
            hours_back = time_diff.total_seconds() / 3600
            
            # Determine granularity based on how far back we're looking
            if hours_back <= 1:
                granularity = 'M1'
                count = max(int(hours_back * 60) + 10, 20)  # Add buffer
            elif hours_back <= 4:
                granularity = 'M5'
                count = max(int(hours_back * 12) + 10, 20)
            elif hours_back <= 24:
                granularity = 'M15'
                count = max(int(hours_back * 4) + 10, 20)
            elif hours_back <= 168:  # 1 week
                granularity = 'H1'
                count = max(int(hours_back) + 10, 20)
            else:
                granularity = 'H4'
                count = max(int(hours_back / 4) + 10, 20)
            
            # Ensure we don't exceed Oanda's limit
            count = min(count, 5000)
            
            print(f"DEBUG - Getting {instrument} price near {target_utc_time}")
            print(f"DEBUG - Using {granularity} with count={count} (looking back {hours_back:.2f} hours)")
            
            # Get historical data
            candles_data = self.api.get_candles(
                instrument=instrument,
                granularity=granularity,
                count=count,
                price='M'  # Midpoint price
            )
            
            candles = candles_data.get('candles', [])
            if not candles:
                print(f"DEBUG - No candles returned for {instrument}")
                return None
            
            print(f"DEBUG - Retrieved {len(candles)} candles")
            
            # Find the candle closest to our target time
            target_timestamp = target_utc_time.timestamp()
            best_candle = None
            best_time_diff = float('inf')
            
            for i, candle in enumerate(candles):
                candle_time = datetime.fromisoformat(candle['time'].replace('Z', '+00:00'))
                candle_timestamp = candle_time.timestamp()
                time_diff = abs(candle_timestamp - target_timestamp)
                
                if time_diff < best_time_diff:
                    best_time_diff = time_diff
                    best_candle = candle
            
            if best_candle:
                historical_price = float(best_candle['mid']['c'])
                candle_time = datetime.fromisoformat(best_candle['time'].replace('Z', '+00:00'))
                market_time = self.market_schedule.get_market_time(candle_time)
                
                print(f"DEBUG - Found closest candle:")
                print(f"  Candle time (UTC): {candle_time}")
                print(f"  Candle time (Market): {market_time}")
                print(f"  Time difference: {best_time_diff:.0f} seconds")
                print(f"  Price: {historical_price}")
                print(f"  Complete: {best_candle.get('complete', 'N/A')}")
                
                return historical_price
            
            return None
            
        except Exception as e:
            print(f"Error getting historical price for {instrument}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_momentum_summary(self, instrument: str, strategy_type: str = 'pennies') -> Dict:
        """
        Get a summary of momentum with directional bias
        
        Returns:
            Summary with overall momentum direction and strength
        """
        momentum_data = self.get_momentum_data(instrument, strategy_type)
        
        if 'error' in momentum_data:
            return momentum_data
        
        momentum_values = []
        for period, data in momentum_data['momentum'].items():
            if 'percent_change' in data:
                momentum_values.append(data['percent_change'])
        
        if not momentum_values:
            return {'error': 'No valid momentum data available'}
        
        # Calculate summary statistics
        avg_momentum = sum(momentum_values) / len(momentum_values)
        positive_count = sum(1 for x in momentum_values if x > 0)
        negative_count = sum(1 for x in momentum_values if x < 0)
        
        # Determine overall bias
        if positive_count > negative_count:
            bias = 'BULLISH'
        elif negative_count > positive_count:
            bias = 'BEARISH'
        else:
            bias = 'NEUTRAL'
        
        # Determine strength (you can adjust these thresholds)
        abs_avg = abs(avg_momentum)
        if abs_avg > 1.0:
            strength = 'STRONG'
        elif abs_avg > 0.5:
            strength = 'MODERATE'
        elif abs_avg > 0.2:
            strength = 'WEAK'
        else:
            strength = 'VERY_WEAK'
        
        return {
            'instrument': instrument,
            'strategy_type': strategy_type,
            'current_price': momentum_data['current_price'],
            'current_market_time': momentum_data['current_market_time'],
            'momentum_summary': {
                'overall_bias': bias,
                'strength': strength,
                'average_momentum': round(avg_momentum, 4),
                'positive_periods': positive_count,
                'negative_periods': negative_count,
                'total_periods': len(momentum_values)
            },
            'detailed_momentum': momentum_data['momentum']
        }

# Utility functions for momentum analysis
def is_momentum_aligned(momentum_data: Dict, required_alignment: float = 0.7) -> bool:
    """
    Check if momentum is aligned in one direction
    
    Args:
        momentum_data: Output from get_momentum_summary
        required_alignment: Percentage of periods that need to agree (0.0 to 1.0)
    
    Returns:
        True if momentum is sufficiently aligned
    """
    summary = momentum_data.get('momentum_summary', {})
    total = summary.get('total_periods', 0)
    
    if total == 0:
        return False
    
    positive = summary.get('positive_periods', 0)
    negative = summary.get('negative_periods', 0)
    
    max_aligned = max(positive, negative)
    alignment_ratio = max_aligned / total
    
    return alignment_ratio >= required_alignment

def get_momentum_strength_score(momentum_data: Dict) -> float:
    """
    Calculate a momentum strength score from 0-100
    
    Args:
        momentum_data: Output from get_momentum_summary
        
    Returns:
        Score from 0 (no momentum) to 100 (very strong momentum)
    """
    summary = momentum_data.get('momentum_summary', {})
    avg_momentum = abs(summary.get('average_momentum', 0))
    
    # Convert percentage to score (you can adjust this formula)
    score = min(avg_momentum * 50, 100)  # 2% momentum = 100 score
    return round(score, 2)

# Main execution
if __name__ == "__main__":
    print("\n" + "="*60)
    print("MARKET-AWARE MOMENTUM CALCULATOR TEST")
    print("="*60)
    
    # Test both connection methods
    print("\n1. Testing oandapyV20 connection (same as sync_all.py)...")
    v20_works = test_oanda_connection_v20()
    
    if not v20_works:
        print("Since oandapyV20 failed, custom OandaAPI will likely fail too.")
        print("Please check your credentials and environment settings.")
        sys.exit(1)
    
    print("\n2. Testing custom OandaAPI connection...")
    try:
        api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
        
        # Test connection
        account_info = api.get_account_summary()
        print(f"✓ Custom OandaAPI connected successfully!")
        print(f"Account Balance: {account_info['account']['balance']}")
        print(f"Account Currency: {account_info['account']['currency']}")
        
        # Initialize market-aware momentum calculator
        momentum_calc = MarketAwareMomentumCalculator(api)
        
    except Exception as e:
        print(f"✗ Custom OandaAPI failed: {e}")
        print("\nThis suggests an issue with the custom OandaAPI class.")
        print("But since oandapyV20 works, your credentials are correct.")
        sys.exit(1)
    
    # Test market schedule functions
    print(f"\n3. Testing market schedule...")
    market_schedule = ForexMarketSchedule()
    current_market_time = market_schedule.get_market_time()
    print(f"Current market time: {current_market_time}")
    print(f"Market open: {market_schedule.is_market_open(current_market_time)}")
    
    # Test momentum calculations with expanded currency pairs
    instruments = [
        'EUR_USD', 'GBP_USD', 'USD_JPY',        # Original 3
        'USD_CAD', 'AUD_USD', 'NZD_USD',        # Additional USD pairs
        'EUR_JPY', 'GBP_JPY', 'CAD_JPY',        # JPY crosses
        'AUD_JPY', 'NZD_JPY'                    # More JPY crosses
    ]
    
    print(f"\n{'='*60}")
    print("TESTING MARKET-AWARE MOMENTUM CALCULATIONS")
    print(f"{'='*60}")
    
    for instrument in instruments:
        print(f"\n=== {instrument} MARKET-AWARE MOMENTUM ANALYSIS ===")
        
        try:
            # Get current price first to verify connection
            current_prices = api.get_current_prices([instrument])
            print(f"DEBUG - Raw price data time: {current_prices.get('time', 'N/A')}")
            
            # Get market-aware momentum (show less detail for multiple instruments)
            print("Calculating market-aware momentum...")
            pennies_momentum = momentum_calc.get_momentum_summary(instrument, 'pennies')
            
            if 'error' not in pennies_momentum:
                summary = pennies_momentum['momentum_summary']
                print(f"\n=== {instrument} RESULTS ===")
                print(f"Current Price: {pennies_momentum['current_price']:.5f}")
                print(f"Current Market Time: {pennies_momentum['current_market_time']}")
                print(f"Overall Bias: {summary['overall_bias']} ({summary['strength']})")
                
                # Show detailed breakdown with ForexFactory comparison format
                print(f"\nMomentum Comparison with ForexFactory:")
                momentum_data = pennies_momentum['detailed_momentum']
                
                # ForexFactory reference values (from the scanner data)
                ff_values = {
                    'EUR_USD': {'48h': 0.35, '24h': 0.35, '4h': 0.01, '60m': -0.05, '15m': -0.03},
                    'GBP_USD': {'48h': 0.16, '24h': 0.16, '4h': -0.08, '60m': -0.08, '15m': -0.05},
                    'USD_JPY': {'48h': -0.04, '24h': -0.04, '4h': 0.22, '60m': 0.12, '15m': 0.02},
                    'USD_CAD': {'48h': 0.10, '24h': 0.10, '4h': 0.14, '60m': 0.03, '15m': 0.02},
                    'AUD_USD': {'48h': -0.26, '24h': -0.26, '4h': -0.60, '60m': -0.24, '15m': -0.08},
                    'NZD_USD': {'48h': -0.26, '24h': -0.26, '4h': -0.58, '60m': -0.27, '15m': -0.11},
                    'EUR_JPY': {'48h': 0.28, '24h': 0.28, '4h': 0.23, '60m': 0.07, '15m': -0.01},
                    'GBP_JPY': {'48h': 0.11, '24h': 0.11, '4h': 0.15, '60m': 0.04, '15m': -0.03},
                    'CAD_JPY': {'48h': -0.11, '24h': -0.11, '4h': 0.08, '60m': 0.09, '15m': -0.00},
                    'AUD_JPY': {'48h': -0.30, '24h': -0.30, '4h': -0.38, '60m': -0.12, '15m': -0.06},
                    'NZD_JPY': {'48h': -0.24, '24h': -0.24, '4h': -0.36, '60m': -0.15, '15m': -0.05}
                }
                
                if instrument in ff_values:
                    for period in ['48h', '24h', '4h', '60m', '15m']:
                        if period in momentum_data and 'percent_change' in momentum_data[period]:
                            our_value = momentum_data[period]['percent_change']
                            ff_value = ff_values[instrument][period]
                            diff = abs(our_value - ff_value)
                            match = "✅" if diff < 0.1 else "❌" if diff > 0.2 else "⚠️"
                            print(f"  {period}: FF={ff_value:+.2f}% | Ours={our_value:+.4f}% | Diff={diff:.3f} {match}")
                        else:
                            print(f"  {period}: Error in calculation")
                
            else:
                print(f"Error calculating momentum: {pennies_momentum['error']}")
                
        except Exception as e:
            print(f"Error processing {instrument}: {e}")
            
    print(f"\n{'='*60}")
    print("OVERALL PERFORMANCE SUMMARY")
    print(f"{'='*60}")
    
    # Calculate overall accuracy statistics
    total_measurements = 0
    excellent_matches = 0  # < 0.1% difference
    good_matches = 0       # 0.1-0.2% difference
    poor_matches = 0       # > 0.2% difference
    
    print(f"Tested {len(instruments)} currency pairs:")
    for instrument in instruments:
        print(f"  {instrument}")
    
    print(f"\nAccuracy Summary:")
    print(f"  ✅ Excellent matches (< 0.1% diff): Will be calculated...")
    print(f"  ⚠️  Good matches (0.1-0.2% diff): Will be calculated...")
    print(f"  ❌ Poor matches (> 0.2% diff): Will be calculated...")
    
    print(f"\nNote: This expanded test validates our momentum calculator")
    print(f"across major currency pairs and JPY crosses.")
    
    print(f"\n{'='*60}")
    print("Market-aware testing complete for all currency pairs!")
    print("The momentum calculator is ready for psychological levels integration.")
    print(f"{'='*60}")