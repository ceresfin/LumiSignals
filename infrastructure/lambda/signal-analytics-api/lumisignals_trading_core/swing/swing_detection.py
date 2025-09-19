"""
LumiSignals Trading Core - Enhanced Swing Detection

Advanced swing point detection with adaptive thresholds, volume confirmation,
and market structure analysis for superior Fibonacci level accuracy.
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from ..fibonacci.atr_calculator import calculate_atr
import logging

logger = logging.getLogger(__name__)

class SwingPoint:
    """Represents a detected swing point with metadata."""
    
    def __init__(self, price: float, timestamp: str, swing_type: str, 
                 strength: float = 0.0, volume: float = 0.0, index: int = 0):
        self.price = price
        self.timestamp = timestamp
        self.swing_type = swing_type  # 'high' or 'low'
        self.strength = strength      # 0.0 - 1.0 confidence score
        self.volume = volume
        self.index = index
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            'price': self.price,
            'timestamp': self.timestamp,
            'type': self.swing_type,
            'strength': self.strength,
            'volume': self.volume,
            'index': self.index
        }

class MarketStructure:
    """Analyzes market structure from swing points."""
    
    @staticmethod
    def analyze_trend(swings: List[SwingPoint], lookback: int = 6) -> Dict[str, Any]:
        """Analyze market structure and trend direction."""
        if len(swings) < 4:
            return {
                'direction': 'ranging',
                'confidence': 0.0,
                'structure': 'insufficient_data'
            }
        
        # Get recent swings
        recent_swings = swings[-lookback:] if len(swings) >= lookback else swings
        
        # Separate highs and lows
        highs = [s for s in recent_swings if s.swing_type == 'high']
        lows = [s for s in recent_swings if s.swing_type == 'low']
        
        if len(highs) < 2 or len(lows) < 2:
            return {
                'direction': 'ranging',
                'confidence': 0.3,
                'structure': 'insufficient_swings'
            }
        
        # Analyze higher highs/higher lows vs lower highs/lower lows
        highs.sort(key=lambda x: x.timestamp)
        lows.sort(key=lambda x: x.timestamp)
        
        # Check for higher highs
        higher_highs = sum(1 for i in range(1, len(highs)) 
                          if highs[i].price > highs[i-1].price)
        
        # Check for higher lows
        higher_lows = sum(1 for i in range(1, len(lows)) 
                         if lows[i].price > lows[i-1].price)
        
        # Check for lower highs
        lower_highs = sum(1 for i in range(1, len(highs)) 
                         if highs[i].price < highs[i-1].price)
        
        # Check for lower lows
        lower_lows = sum(1 for i in range(1, len(lows)) 
                        if lows[i].price < lows[i-1].price)
        
        # Determine trend
        uptrend_score = (higher_highs + higher_lows) / max(len(highs) + len(lows) - 2, 1)
        downtrend_score = (lower_highs + lower_lows) / max(len(highs) + len(lows) - 2, 1)
        
        if uptrend_score > 0.6:
            direction = 'uptrend'
            confidence = uptrend_score
        elif downtrend_score > 0.6:
            direction = 'downtrend'
            confidence = downtrend_score
        else:
            direction = 'ranging'
            confidence = 1.0 - max(uptrend_score, downtrend_score)
        
        return {
            'direction': direction,
            'confidence': min(confidence, 1.0),
            'structure': 'clear_pattern',
            'higher_highs': higher_highs,
            'higher_lows': higher_lows,
            'lower_highs': lower_highs,
            'lower_lows': lower_lows,
            'recent_swings_count': len(recent_swings)
        }

class EnhancedSwingDetector:
    """Enhanced swing detection with adaptive thresholds and market context."""
    
    def __init__(self, timeframe: str = 'H1'):
        self.timeframe = timeframe
        self.adaptive_thresholds = self._get_adaptive_thresholds()
        
    def _get_adaptive_thresholds(self) -> Dict[str, float]:
        """Get adaptive thresholds based on timeframe and market conditions."""
        # Import the configuration from timeframe_config
        from ..fibonacci.timeframe_config import get_timeframe_parameters
        
        # Get configured parameters for this timeframe
        config_params = get_timeframe_parameters(self.timeframe)
        
        # Use configured values with proper key mapping
        return {
            'min_pips': config_params.get('min_pip_distance', 10),
            'window': config_params.get('window', 2),
            'strength_req': config_params.get('min_strength', 2)
        }
    
    def detect_swing_points_enhanced(self, price_data: List[Dict], 
                                   volume_confirmation: bool = True) -> List[SwingPoint]:
        """
        Enhanced swing point detection with volume confirmation and adaptive thresholds.
        """
        if len(price_data) < 10:
            return []
        
        swings = []
        thresholds = self.adaptive_thresholds
        window = thresholds['window']
        
        # Convert price data to arrays
        highs = np.array([float(candle.get('h', candle.get('high', 0))) for candle in price_data])
        lows = np.array([float(candle.get('l', candle.get('low', 0))) for candle in price_data])
        volumes = np.array([float(candle.get('volume', 1)) for candle in price_data])
        timestamps = [candle.get('time', candle.get('timestamp', '')) for candle in price_data]
        
        # Calculate average volume for confirmation
        avg_volume = np.mean(volumes) if volume_confirmation else 0
        
        # Detect swing highs
        for i in range(window, len(highs) - window):
            # Check if this is a local maximum
            is_high = all(highs[i] >= highs[j] for j in range(i - window, i + window + 1) if j != i)
            
            if is_high:
                # Calculate strength based on how much higher it is
                strength = self._calculate_swing_strength(highs, i, window, 'high')
                
                # Volume confirmation (optional)
                volume_confirmed = True
                if volume_confirmation and avg_volume > 0:
                    volume_confirmed = volumes[i] >= avg_volume * 0.8
                
                if strength >= 0.1 and volume_confirmed:  # Reduced to 0.1 for extreme low volatility
                    swing = SwingPoint(
                        price=highs[i],
                        timestamp=timestamps[i],
                        swing_type='high',
                        strength=strength,
                        volume=volumes[i],
                        index=i
                    )
                    swings.append(swing)
        
        # Detect swing lows
        for i in range(window, len(lows) - window):
            # Check if this is a local minimum
            is_low = all(lows[i] <= lows[j] for j in range(i - window, i + window + 1) if j != i)
            
            if is_low:
                # Calculate strength
                strength = self._calculate_swing_strength(lows, i, window, 'low')
                
                # Volume confirmation (optional)
                volume_confirmed = True
                if volume_confirmation and avg_volume > 0:
                    volume_confirmed = volumes[i] >= avg_volume * 0.8
                
                if strength >= 0.1 and volume_confirmed:  # Reduced to 0.1 for extreme low volatility
                    swing = SwingPoint(
                        price=lows[i],
                        timestamp=timestamps[i],
                        swing_type='low',
                        strength=strength,
                        volume=volumes[i],
                        index=i
                    )
                    swings.append(swing)
        
        # Sort by timestamp
        swings.sort(key=lambda x: x.timestamp)
        
        # Filter by pip distance
        return self._filter_by_pip_distance(swings, price_data[0].get('instrument', 'EUR_USD'))
    
    def _calculate_swing_strength(self, prices: np.ndarray, index: int, 
                                window: int, swing_type: str) -> float:
        """Calculate the strength of a swing point (0.0 - 1.0)."""
        if swing_type == 'high':
            # How much higher than surrounding points
            surrounding = prices[index - window:index + window + 1]
            surrounding = surrounding[surrounding != prices[index]]
            if len(surrounding) == 0:
                return 0.0
            max_diff = prices[index] - np.max(surrounding)
            avg_diff = prices[index] - np.mean(surrounding)
        else:  # swing_type == 'low'
            # How much lower than surrounding points
            surrounding = prices[index - window:index + window + 1]
            surrounding = surrounding[surrounding != prices[index]]
            if len(surrounding) == 0:
                return 0.0
            max_diff = np.min(surrounding) - prices[index]
            avg_diff = np.mean(surrounding) - prices[index]
        
        # Normalize strength (this is a simplified approach)
        # In practice, you might want to use ATR or recent volatility
        recent_range = np.max(prices[-20:]) - np.min(prices[-20:]) if len(prices) >= 20 else 0.001
        strength = min(avg_diff / (recent_range + 0.0001), 1.0)
        
        return max(strength, 0.0)
    
    def _filter_by_pip_distance(self, swings: List[SwingPoint], instrument: str) -> List[SwingPoint]:
        """Filter swings that meet minimum pip distance requirements."""
        if len(swings) < 2:
            return swings
        
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        min_pips = self.adaptive_thresholds['min_pips']
        min_price_distance = min_pips * pip_value
        
        filtered_swings = [swings[0]]  # Always keep first swing
        
        for swing in swings[1:]:
            last_swing = filtered_swings[-1]
            
            # Calculate distance
            price_distance = abs(swing.price - last_swing.price)
            
            # Allow if distance is sufficient OR if it's a stronger swing of different type
            if (price_distance >= min_price_distance or 
                (swing.swing_type != last_swing.swing_type and swing.strength > last_swing.strength)):
                filtered_swings.append(swing)
            elif swing.swing_type == last_swing.swing_type and swing.strength > last_swing.strength:
                # Replace with stronger swing of same type
                filtered_swings[-1] = swing
        
        return filtered_swings
    
    def get_recent_swing_levels(self, swings: List[SwingPoint], 
                              current_price: float) -> Dict[str, Any]:
        """Get the most recent and relevant swing high/low levels."""
        if not swings:
            return {
                'recent_swing_high': None,
                'recent_swing_low': None,
                'swing_range_pips': 0,
                'message': 'No significant swings detected'
            }
        
        # Find most recent swing high and low
        recent_high = None
        recent_low = None
        
        for swing in reversed(swings):
            if swing.swing_type == 'high' and recent_high is None:
                recent_high = swing
            elif swing.swing_type == 'low' and recent_low is None:
                recent_low = swing
            
            if recent_high and recent_low:
                break
        
        # Calculate swing range
        swing_range_pips = 0
        if recent_high and recent_low:
            price_range = abs(recent_high.price - recent_low.price)
            is_jpy = True  # This should be determined from instrument
            pip_value = 0.01 if is_jpy else 0.0001
            swing_range_pips = price_range / pip_value
        
        return {
            'recent_swing_high': recent_high.to_dict() if recent_high else None,
            'recent_swing_low': recent_low.to_dict() if recent_low else None,
            'swing_range_pips': round(swing_range_pips, 1),
            'total_swings_detected': len(swings),
            'analysis_timestamp': datetime.utcnow().isoformat() + 'Z'
        }

def analyze_swing_structure(instrument: str, price_data: List[Dict], 
                          timeframe: str = 'H1', current_price: float = None) -> Dict[str, Any]:
    """
    Main function to analyze swing structure for an instrument.
    
    Returns comprehensive swing analysis including recent levels and market structure.
    """
    detector = EnhancedSwingDetector(timeframe)
    
    # Log detection parameters
    logger.info(f"Swing detection for {instrument} {timeframe}: thresholds={detector.adaptive_thresholds}, candles={len(price_data)}")
    
    # Detect swing points
    swings = detector.detect_swing_points_enhanced(price_data, volume_confirmation=True)
    
    logger.info(f"Swing detection results for {instrument}: {len(swings)} swings found")
    
    # Get recent swing levels
    swing_levels = detector.get_recent_swing_levels(swings, current_price or 0.0)
    
    # Analyze market structure
    market_structure = MarketStructure.analyze_trend(swings)
    
    # Calculate additional metrics
    if current_price and swing_levels['recent_swing_high'] and swing_levels['recent_swing_low']:
        recent_high_price = swing_levels['recent_swing_high']['price']
        recent_low_price = swing_levels['recent_swing_low']['price']
        
        # Calculate position within swing range
        if recent_high_price != recent_low_price:
            position_in_range = (current_price - recent_low_price) / (recent_high_price - recent_low_price)
        else:
            position_in_range = 0.5
        
        swing_levels['current_position_pct'] = round(position_in_range * 100, 1)
        swing_levels['distance_to_high_pips'] = round(abs(current_price - recent_high_price) / (0.01 if 'JPY' in instrument else 0.0001), 1)
        swing_levels['distance_to_low_pips'] = round(abs(current_price - recent_low_price) / (0.01 if 'JPY' in instrument else 0.0001), 1)
    
    return {
        'instrument': instrument,
        'timeframe': timeframe,
        'swing_levels': swing_levels,
        'market_structure': market_structure,
        'detection_settings': {
            'min_pips': detector.adaptive_thresholds['min_pips'],
            'window': detector.adaptive_thresholds['window'],
            'volume_confirmation': True
        },
        'analysis_timestamp': datetime.utcnow().isoformat() + 'Z'
    }