#!/usr/bin/env python3
"""
MarketAwareMomentumCalculator - Sophisticated momentum analysis for forex trading

This module provides market-aware momentum calculations that handle forex trading sessions,
weekend gaps, and multi-timeframe analysis for psychological level trading strategies.

Features:
- 5-timeframe momentum analysis (15m, 60m, 4h, 24h, 48h)
- Forex trading hour awareness (skips weekends)
- Start-of-week logic for consistent 24h/48h references
- Multi-strategy support (pennies, quarters, dimes, small quarters)
- Adaptive granularity for efficient OANDA API usage
- ForexFactory validation capabilities
- Momentum consensus and alignment detection
"""

import pytz
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any
import logging

from .forex_market_schedule import ForexMarketSchedule

# Setup logging
logger = logging.getLogger(__name__)


class MarketAwareMomentumCalculator:
    """
    Market-aware momentum calculator that handles forex trading sessions and weekends
    
    This calculator provides sophisticated momentum analysis that:
    1. Skips weekend gaps when calculating historical lookbacks
    2. Uses start-of-week logic for 24h/48h momentum consistency
    3. Adapts API granularity based on lookback period
    4. Supports multiple strategy types with different timeframe sets
    """
    
    def __init__(self, oanda_api):
        """
        Initialize the momentum calculator
        
        Args:
            oanda_api: Instance of OandaAPI or compatible API client
        """
        self.api = oanda_api
        self.market_schedule = ForexMarketSchedule()
        
        # Define momentum intervals for different strategy types (in trading hours)
        self.momentum_intervals = {
            'pennies': {
                '48h': 48,      # 48 trading hours - 2 trading days
                '24h': 24,      # 24 trading hours - 1 trading day
                '4h': 4,        # 4 trading hours - quarter day
                '60m': 1,       # 1 trading hour - hourly momentum
                '15m': 0.25     # 15 minutes - intraday momentum
            },
            'quarters': {
                '72h': 72,      # 72 trading hours - 3 trading days
                '24h': 24,      # 24 trading hours - 1 trading day
                '8h': 8,        # 8 trading hours - third of day
                '2h': 2,        # 2 trading hours - shorter term
                '30m': 0.5      # 30 minutes - intraday
            },
            'dimes': {
                '168h': 168,    # 168 trading hours - 1 trading week
                '72h': 72,      # 72 trading hours - 3 trading days
                '24h': 24,      # 24 trading hours - 1 trading day
                '4h': 4,        # 4 trading hours - quarter day
                '1h': 1         # 1 trading hour - hourly
            },
            'small_quarters': {
                '24h': 24,      # 24 trading hours - 1 trading day
                '8h': 8,        # 8 trading hours - third of day
                '2h': 2,        # 2 trading hours - shorter term
                '30m': 0.5,     # 30 minutes - intraday
                '15m': 0.25     # 15 minutes - very short term
            }
        }
        
        # Thresholds for momentum significance
        self.default_threshold = 0.05  # 5 basis points minimum momentum
        
        logger.info(f"MarketAwareMomentumCalculator initialized with {len(self.momentum_intervals)} strategy types")
    
    def get_momentum_data(self, instrument: str, strategy_type: str = 'pennies') -> Dict[str, Any]:
        """
        Get comprehensive momentum analysis for a given instrument and strategy type
        
        This method calculates momentum across all timeframes defined for the strategy type,
        using market-aware timing that properly handles forex trading sessions.
        
        Args:
            instrument: Currency pair (e.g., 'EUR_USD', 'USD_JPY')
            strategy_type: Strategy type - 'pennies', 'quarters', 'dimes', or 'small_quarters'
        
        Returns:
            Dictionary with momentum data including:
            - current_price: Current market price
            - current_market_time: Current market time (EST/EDT)
            - momentum: Dict of momentum data for each timeframe
            - market_session_info: Current market session details
        """
        try:
            # Validate strategy type
            if strategy_type not in self.momentum_intervals:
                raise ValueError(f"Unknown strategy type: {strategy_type}. Available: {list(self.momentum_intervals.keys())}")
            
            # Get current price and market time
            current_price = self._get_current_price(instrument)
            if current_price is None:
                return {'error': f'Unable to retrieve current price for {instrument}'}
            
            current_market_time = self.market_schedule.get_market_time()
            
            logger.debug(f"Calculating momentum for {instrument} ({strategy_type})")
            logger.debug(f"Current market time: {current_market_time}")
            logger.debug(f"Current price: {current_price:.5f}")
            
            # Get market session info for context
            session_info = self.market_schedule.get_session_info(current_market_time)
            
            # Get the timeframe intervals for this strategy
            intervals = self.momentum_intervals[strategy_type]
            
            momentum_results = {
                'instrument': instrument,
                'strategy_type': strategy_type,
                'current_price': current_price,
                'current_market_time': current_market_time.isoformat(),
                'timestamp': datetime.now().isoformat(),
                'market_session_info': session_info,
                'momentum': {}
            }
            
            # Calculate momentum for each timeframe
            for period_name, hours_back in intervals.items():
                try:
                    logger.debug(f"Calculating {period_name} momentum ({hours_back}h back)")
                    
                    # Get target market time using trading hour logic
                    target_market_time = self._get_target_market_time(current_market_time, hours_back)
                    
                    # Convert to UTC for OANDA API
                    target_utc_time = target_market_time.astimezone(pytz.UTC)
                    
                    # Get historical price
                    historical_price = self._get_price_at_time(instrument, target_utc_time)
                    
                    if historical_price:
                        # Calculate percentage change
                        pct_change = ((current_price - historical_price) / historical_price) * 100
                        
                        momentum_results['momentum'][period_name] = {
                            'historical_price': historical_price,
                            'percent_change': round(pct_change, 4),
                            'hours_back': hours_back,
                            'target_time_market': target_market_time.isoformat(),
                            'target_time_utc': target_utc_time.isoformat(),
                            'price_direction': 'UP' if pct_change > 0 else 'DOWN' if pct_change < 0 else 'FLAT'
                        }
                        
                        logger.debug(f"{period_name}: {historical_price:.5f} -> {current_price:.5f} = {pct_change:+.4f}%")
                    else:
                        momentum_results['momentum'][period_name] = {
                            'error': f'Could not retrieve historical price for {hours_back} trading hours ago',
                            'hours_back': hours_back,
                            'target_time_market': target_market_time.isoformat(),
                            'target_time_utc': target_utc_time.isoformat()
                        }
                        
                except Exception as e:
                    logger.error(f"Error calculating {period_name} momentum: {e}")
                    momentum_results['momentum'][period_name] = {
                        'error': str(e),
                        'hours_back': hours_back
                    }
            
            return momentum_results
            
        except Exception as e:
            logger.error(f"Failed to calculate momentum for {instrument}: {e}")
            return {
                'error': f'Failed to calculate momentum: {str(e)}',
                'instrument': instrument,
                'strategy_type': strategy_type
            }
    
    def get_momentum_summary(self, instrument: str, strategy_type: str = 'pennies') -> Dict[str, Any]:
        """
        Get momentum summary with directional bias and strength analysis
        
        Args:
            instrument: Currency pair
            strategy_type: Strategy type
            
        Returns:
            Summary with overall momentum direction, strength, and detailed analysis
        """
        momentum_data = self.get_momentum_data(instrument, strategy_type)
        
        if 'error' in momentum_data:
            return momentum_data
        
        # Extract valid momentum values
        momentum_values = []
        momentum_directions = []
        
        for period, data in momentum_data['momentum'].items():
            if 'percent_change' in data:
                pct_change = data['percent_change']
                momentum_values.append(pct_change)
                
                # Classify direction with threshold
                if pct_change > self.default_threshold:
                    momentum_directions.append(1)  # Positive
                elif pct_change < -self.default_threshold:
                    momentum_directions.append(-1)  # Negative
                else:
                    momentum_directions.append(0)  # Neutral
        
        if not momentum_values:
            return {
                'error': 'No valid momentum data available',
                'instrument': instrument,
                'strategy_type': strategy_type
            }
        
        # Calculate summary statistics
        avg_momentum = sum(momentum_values) / len(momentum_values)
        positive_count = sum(1 for x in momentum_directions if x > 0)
        negative_count = sum(1 for x in momentum_directions if x < 0)
        neutral_count = len(momentum_directions) - positive_count - negative_count
        
        # Determine overall bias using majority rule
        total_periods = len(momentum_directions)
        if positive_count > negative_count and positive_count > neutral_count:
            bias = 'BULLISH'
            confidence = positive_count / total_periods
        elif negative_count > positive_count and negative_count > neutral_count:
            bias = 'BEARISH'
            confidence = negative_count / total_periods
        else:
            bias = 'NEUTRAL'
            confidence = max(positive_count, negative_count, neutral_count) / total_periods
        
        # Determine strength based on average absolute momentum
        abs_avg = abs(avg_momentum)
        if abs_avg > 1.0:
            strength = 'STRONG'
        elif abs_avg > 0.5:
            strength = 'MODERATE'
        elif abs_avg > 0.2:
            strength = 'WEAK'
        else:
            strength = 'VERY_WEAK'
        
        # Build comprehensive summary
        summary_result = {
            'instrument': instrument,
            'strategy_type': strategy_type,
            'current_price': momentum_data['current_price'],
            'current_market_time': momentum_data['current_market_time'],
            'market_session_info': momentum_data['market_session_info'],
            'momentum_summary': {
                'overall_bias': bias,
                'strength': strength,
                'confidence': round(confidence, 3),
                'average_momentum': round(avg_momentum, 4),
                'positive_periods': positive_count,
                'negative_periods': negative_count,
                'neutral_periods': neutral_count,
                'total_periods': total_periods,
                'alignment_ratio': round(max(positive_count, negative_count) / total_periods, 3)
            },
            'detailed_momentum': momentum_data['momentum'],
            'timestamp': datetime.now().isoformat()
        }
        
        return summary_result
    
    def get_consensus_signal(self, instrument: str, strategy_type: str = 'pennies', 
                           required_confidence: float = 0.6) -> Dict[str, Any]:
        """
        Get trading consensus signal based on multi-timeframe momentum alignment
        
        This implements the 3+ out of 5 timeframes alignment rule for high-quality signals.
        
        Args:
            instrument: Currency pair
            strategy_type: Strategy type
            required_confidence: Minimum confidence required (0.6 = 3/5 alignment)
            
        Returns:
            Dictionary with consensus signal, confidence, and supporting data
        """
        momentum_summary = self.get_momentum_summary(instrument, strategy_type)
        
        if 'error' in momentum_summary:
            return momentum_summary
        
        summary = momentum_summary['momentum_summary']
        bias = summary['overall_bias']
        confidence = summary['confidence']
        
        # Determine if signal meets quality threshold
        signal_quality = 'HIGH' if confidence >= 0.8 else 'MEDIUM' if confidence >= 0.6 else 'LOW'
        trading_ready = confidence >= required_confidence
        
        consensus_result = {
            'instrument': instrument,
            'strategy_type': strategy_type,
            'signal': bias,
            'confidence': confidence,
            'signal_quality': signal_quality,
            'trading_ready': trading_ready,
            'aligned_timeframes': summary['positive_periods'] if bias == 'BULLISH' else summary['negative_periods'],
            'total_timeframes': summary['total_periods'],
            'strength': summary['strength'],
            'average_momentum': summary['average_momentum'],
            'market_session': momentum_summary['market_session_info']['session_name'],
            'reasoning': self._generate_consensus_reasoning(summary, bias, confidence, trading_ready),
            'momentum_data': momentum_summary,
            'timestamp': datetime.now().isoformat()
        }
        
        return consensus_result
    
    def _get_current_price(self, instrument: str) -> Optional[float]:
        """Get current market price for instrument"""
        try:
            current_price_data = self.api.get_current_prices([instrument])
            
            if 'prices' in current_price_data and len(current_price_data['prices']) > 0:
                price_data = current_price_data['prices'][0]
                
                # Try different price fields in order of preference
                if 'mid' in price_data:
                    return float(price_data['mid'])
                elif 'closeoutBid' in price_data and 'closeoutAsk' in price_data:
                    return (float(price_data['closeoutBid']) + float(price_data['closeoutAsk'])) / 2
                elif 'bid' in price_data and 'ask' in price_data:
                    return (float(price_data['bid']) + float(price_data['ask'])) / 2
                
            logger.error(f"No valid price data found for {instrument}: {current_price_data}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting current price for {instrument}: {e}")
            return None
    
    def _get_target_market_time(self, current_market_time: datetime, hours_back: float) -> datetime:
        """Get target market time accounting for trading hours"""
        if hours_back >= 1:
            # Use trading hour logic for hour+ intervals
            return self.market_schedule.get_last_trading_time(current_market_time, int(hours_back))
        else:
            # For sub-hour intervals, just subtract minutes (assume intraday)
            minutes_back = int(hours_back * 60)
            return current_market_time - timedelta(minutes=minutes_back)
    
    def _get_price_at_time(self, instrument: str, target_utc_time: datetime) -> Optional[float]:
        """
        Get historical price closest to target UTC time using adaptive granularity
        """
        try:
            # Calculate lookback period for granularity selection
            current_utc = datetime.now(pytz.UTC)
            time_diff = current_utc - target_utc_time
            hours_back = time_diff.total_seconds() / 3600
            
            # Adaptive granularity based on lookback period
            if hours_back <= 1:
                granularity = 'M1'
                count = max(int(hours_back * 60) + 10, 20)
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
            
            # Respect OANDA API limits
            count = min(count, 5000)
            
            logger.debug(f"Getting {instrument} historical price: {granularity}, count={count}")
            
            # Get historical candle data
            candles_data = self.api.get_candles(
                instrument=instrument,
                granularity=granularity,
                count=count,
                price='M'  # Midpoint price
            )
            
            candles = candles_data.get('candles', [])
            if not candles:
                logger.warning(f"No candles returned for {instrument}")
                return None
            
            # Find closest candle to target time
            target_timestamp = target_utc_time.timestamp()
            best_candle = None
            best_time_diff = float('inf')
            
            for candle in candles:
                candle_time = datetime.fromisoformat(candle['time'].replace('Z', '+00:00'))
                candle_timestamp = candle_time.timestamp()
                time_diff = abs(candle_timestamp - target_timestamp)
                
                if time_diff < best_time_diff:
                    best_time_diff = best_time_diff
                    best_candle = candle
            
            if best_candle and 'mid' in best_candle and 'c' in best_candle['mid']:
                historical_price = float(best_candle['mid']['c'])
                logger.debug(f"Found price {historical_price:.5f} with {best_time_diff:.0f}s difference")
                return historical_price
                
            return None
            
        except Exception as e:
            logger.error(f"Error getting historical price for {instrument}: {e}")
            return None
    
    def _generate_consensus_reasoning(self, summary: Dict, bias: str, confidence: float, 
                                   trading_ready: bool) -> List[str]:
        """Generate human-readable reasoning for consensus signal"""
        reasoning = []
        
        aligned_count = summary['positive_periods'] if bias == 'BULLISH' else summary['negative_periods']
        total_count = summary['total_periods']
        
        # Main signal reasoning
        if trading_ready:
            reasoning.append(f"✅ {bias} signal: {aligned_count}/{total_count} timeframes aligned ({confidence:.1%} confidence)")
        else:
            reasoning.append(f"⚠️ {bias} signal: {aligned_count}/{total_count} timeframes aligned ({confidence:.1%} confidence - below threshold)")
        
        # Strength reasoning
        avg_momentum = abs(summary['average_momentum'])
        if avg_momentum > 1.0:
            reasoning.append(f"Strong momentum: {summary['average_momentum']:+.3f}% average movement")
        elif avg_momentum > 0.5:
            reasoning.append(f"Moderate momentum: {summary['average_momentum']:+.3f}% average movement")
        else:
            reasoning.append(f"Weak momentum: {summary['average_momentum']:+.3f}% average movement")
        
        # Alignment quality
        if confidence >= 0.8:
            reasoning.append("High-quality signal: Excellent timeframe alignment")
        elif confidence >= 0.6:
            reasoning.append("Medium-quality signal: Acceptable timeframe alignment") 
        else:
            reasoning.append("Low-quality signal: Poor timeframe alignment")
        
        return reasoning


# Utility functions for easy integration
def calculate_instrument_momentum(oanda_api, instrument: str, strategy_type: str = 'pennies') -> Dict[str, Any]:
    """
    Utility function to calculate momentum for a single instrument
    
    Args:
        oanda_api: OANDA API instance
        instrument: Currency pair
        strategy_type: Strategy type
        
    Returns:
        Momentum summary data
    """
    calc = MarketAwareMomentumCalculator(oanda_api)
    return calc.get_momentum_summary(instrument, strategy_type)


def get_trading_consensus(oanda_api, instrument: str, strategy_type: str = 'pennies') -> Dict[str, Any]:
    """
    Utility function to get trading consensus for a single instrument
    
    Args:
        oanda_api: OANDA API instance  
        instrument: Currency pair
        strategy_type: Strategy type
        
    Returns:
        Consensus signal data
    """
    calc = MarketAwareMomentumCalculator(oanda_api)
    return calc.get_consensus_signal(instrument, strategy_type)


def is_momentum_aligned(momentum_data: Dict, required_confidence: float = 0.6) -> bool:
    """
    Check if momentum is sufficiently aligned for trading
    
    Args:
        momentum_data: Output from get_momentum_summary or get_consensus_signal
        required_confidence: Minimum confidence threshold (0.6 = 60%)
        
    Returns:
        True if momentum meets alignment requirements
    """
    if 'confidence' in momentum_data:
        return momentum_data['confidence'] >= required_confidence
    elif 'momentum_summary' in momentum_data:
        return momentum_data['momentum_summary']['confidence'] >= required_confidence
    else:
        return False


def get_momentum_strength_score(momentum_data: Dict) -> float:
    """
    Calculate momentum strength score from 0-100
    
    Args:
        momentum_data: Output from get_momentum_summary
        
    Returns:
        Score from 0 (no momentum) to 100 (very strong momentum)
    """
    if 'momentum_summary' in momentum_data:
        avg_momentum = abs(momentum_data['momentum_summary']['average_momentum'])
    elif 'average_momentum' in momentum_data:
        avg_momentum = abs(momentum_data['average_momentum'])
    else:
        return 0.0
    
    # Convert percentage to score (2% momentum = 100 score)
    score = min(avg_momentum * 50, 100)
    return round(score, 2)


# Example usage and testing
if __name__ == "__main__":
    print("MarketAwareMomentumCalculator - Core module loaded successfully")
    print("Available strategy types:", ['pennies', 'quarters', 'dimes', 'small_quarters'])
    print("Use with OANDA API instance for momentum calculations")