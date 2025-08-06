#!/usr/bin/env python3
"""
DualLimitCurveTemplate - Reusable Template for Penny/Quarter/Dime Curve Strategies
Implements the "Football Field" dual limit order methodology across all psychological levels

Key Concepts:
- Psychological levels = football fields  
- Zone width = bodyguard distance around each level
- Zone penetration = bodyguards getting overwhelmed
- Dual limit orders = two shots at each move
- Reset mechanism = touching next level clears old orders
- Configurable for Penny (0.01), Quarter (0.025), Dime (0.10) levels
"""

import sys
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod

# Add parent directories to path
current_dir = os.path.dirname(os.path.abspath(__file__))
strategies_dir = os.path.dirname(current_dir)
src_dir = os.path.dirname(strategies_dir)
sys.path.extend([strategies_dir, src_dir])

from base_strategy import BaseRenaissanceStrategy

class DualLimitCurveTemplate(BaseRenaissanceStrategy, ABC):
    """
    Abstract base template for dual limit curve strategies
    
    Implements the core "Football Field" methodology that can be configured for:
    - Penny Curve: 0.01 levels, 25-pip zones
    - Quarter Curve: 0.025 levels, 62.5-pip zones  
    - Dime Curve: 0.10 levels, 250-pip zones
    """
    
    def __init__(self, strategy_id: str, config: Dict):
        # Core template parameters (will be set by subclasses before calling super)
        # These should be set by subclass before calling super().__init__()
        if not hasattr(self, 'level_increment') or self.level_increment is None:
            raise ValueError(f"{strategy_id} must set level_increment before calling super().__init__()")
        if not hasattr(self, 'zone_width_pips') or self.zone_width_pips is None:
            raise ValueError(f"{strategy_id} must set zone_width_pips before calling super().__init__()")
        if not hasattr(self, 'curve_type') or self.curve_type is None:
            raise ValueError(f"{strategy_id} must set curve_type before calling super().__init__()")
        
        super().__init__(strategy_id, config)
        
        # Common parameters
        self.momentum_threshold = config.get('momentum_threshold', 0.05)
        self.stop_loss_pips = config.get('stop_loss_pips', 20)  # Default to 20-pip stops
        self.risk_per_trade = config.get('risk_per_trade', 5.0)
        
        # Dual order tracking
        self.active_orders = []
        self.last_reset_level = None
        self.current_momentum_direction = None
        
        # Instruments (major pairs for psychological level trading)
        self.instruments = config.get('instruments', [
            'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CHF', 'USD_CAD', 
            'AUD_USD', 'NZD_USD', 'EUR_GBP', 'EUR_JPY', 'GBP_JPY'
        ])
    
    @abstractmethod
    def _set_curve_parameters(self):
        """Subclasses must implement this to set curve-specific parameters"""
        pass
    
    def analyze_market(self, market_data: Dict) -> Dict:
        """
        Core market analysis for dual limit curve opportunities
        """
        instrument = market_data['instrument']
        current_price = market_data['current_price']
        
        analysis = {
            'timestamp': datetime.now(),
            'instrument': instrument,
            'current_price': current_price,
            'strategy_type': f'{self.curve_type}_DUAL_LIMIT',
            'curve_type': self.curve_type
        }
        
        # Determine momentum direction
        momentum_data = self._calculate_momentum(market_data)
        analysis['momentum'] = momentum_data
        
        # Get primary momentum for direction
        primary_momentum = momentum_data.get('momentum_60m', 0)
        
        if abs(primary_momentum) < self.momentum_threshold:
            analysis['signal'] = None
            analysis['reason'] = f'Momentum {abs(primary_momentum):.3f}% below threshold {self.momentum_threshold}%'
            return analysis
        
        # Set momentum direction
        self.current_momentum_direction = 'POSITIVE' if primary_momentum > 0 else 'NEGATIVE'
        
        # Detect psychological levels and zones
        curve_data = self._detect_psychological_levels_and_zones(current_price, instrument)
        analysis['curve_data'] = curve_data
        
        # Check for reset conditions (price touching next level)
        reset_triggered = self._check_reset_condition(current_price, curve_data)
        if reset_triggered:
            analysis['reset_triggered'] = True
            self._reset_orders()
        
        # Check for zone penetration
        penetration_data = self._check_zone_penetration(current_price, curve_data, market_data)
        analysis['penetration'] = penetration_data
        
        return analysis
    
    def _calculate_momentum(self, market_data: Dict) -> Dict:
        """Calculate momentum for direction determination"""
        return {
            'momentum_5m': market_data.get('momentum_5m', 0),
            'momentum_60m': market_data.get('momentum_60m', 0),
            'momentum_4h': market_data.get('momentum_4h', 0),
            'momentum_24h': market_data.get('momentum_24h', 0)
        }
    
    def _detect_psychological_levels_and_zones(self, current_price: float, instrument: str) -> Dict:
        """
        Detect psychological levels and their associated zones
        Configurable for penny/quarter/dime levels
        """
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        zone_buffer = self.zone_width_pips * pip_value
        
        # Calculate psychological levels based on curve type
        if is_jpy:
            # JPY levels: 110.00, 111.00, etc. (for penny)
            # Quarter: 110.25, 110.50, 110.75, 111.00, etc.
            # Dime: 110.0, 111.0, 112.0, etc.
            if self.curve_type == "PENNY":
                current_level = round(current_price)
                level_range = 5
                levels = [current_level + i for i in range(-level_range, level_range + 1)]
            elif self.curve_type == "QUARTER":
                base_level = int(current_price * 4) / 4  # Round to nearest 0.25
                level_range = 10
                levels = [base_level + (i * 0.25) for i in range(-level_range, level_range + 1)]
            else:  # DIME
                current_level = round(current_price / 10) * 10
                level_range = 3
                levels = [current_level + (i * 10) for i in range(-level_range, level_range + 1)]
        else:
            # Non-JPY levels
            if self.curve_type == "PENNY":
                # Penny: 1.1800, 1.1900, 1.2000, etc.
                base_level = int(current_price * 100) / 100
                level_range = 5
                levels = [round(base_level + (i * self.level_increment), 4) 
                         for i in range(-level_range, level_range + 1)]
            elif self.curve_type == "QUARTER":
                # Quarter: 1.1750, 1.1775, 1.1800, 1.1825, etc.
                base_level = int(current_price * 400) / 400  # Round to nearest 0.0025
                level_range = 8
                levels = [round(base_level + (i * self.level_increment), 4) 
                         for i in range(-level_range, level_range + 1)]
            else:  # DIME
                # Dime: 1.1000, 1.2000, 1.3000, etc.
                base_level = int(current_price * 10) / 10
                level_range = 3
                levels = [round(base_level + (i * self.level_increment), 4) 
                         for i in range(-level_range, level_range + 1)]
        
        # Filter positive levels
        levels = [level for level in levels if level > 0]
        
        # Create zones based on momentum direction
        zones = []
        for level in levels:
            if self.current_momentum_direction == 'POSITIVE':
                # BUY zones: zone_width ABOVE each level
                zone = {
                    'level': level,
                    'zone_type': 'BUY',
                    'zone_bottom': level,
                    'zone_top': level + zone_buffer,
                    'target_level': level + self.level_increment,  # Next level up
                    'stop_level': level - (self.stop_loss_pips * pip_value)
                }
            else:
                # SELL zones: zone_width BELOW each level
                zone = {
                    'level': level,
                    'zone_type': 'SELL', 
                    'zone_bottom': level - zone_buffer,
                    'zone_top': level,
                    'target_level': level - self.level_increment,  # Next level down
                    'stop_level': level + (self.stop_loss_pips * pip_value)
                }
            
            zone['in_zone'] = zone['zone_bottom'] <= current_price <= zone['zone_top']
            zones.append(zone)
        
        return {
            'current_price': current_price,
            'is_jpy': is_jpy,
            'pip_value': pip_value,
            'levels': levels,
            'zones': zones,
            'momentum_direction': self.current_momentum_direction,
            'curve_type': self.curve_type,
            'level_increment': self.level_increment,
            'zone_width_pips': self.zone_width_pips
        }
    
    def _check_reset_condition(self, current_price: float, curve_data: Dict) -> bool:
        """
        Check if price has touched a new psychological level (reset condition)
        """
        levels = curve_data['levels']
        is_jpy = curve_data['is_jpy']
        
        # Check if price has touched any level
        for level in levels:
            # Allow tolerance based on curve type
            if self.curve_type == "PENNY":
                tolerance = 0.0005 if not is_jpy else 0.05
            elif self.curve_type == "QUARTER":
                tolerance = 0.00125 if not is_jpy else 0.125
            else:  # DIME
                tolerance = 0.005 if not is_jpy else 0.5
            
            if abs(current_price - level) <= tolerance:
                if self.last_reset_level != level:
                    self.last_reset_level = level
                    self.logger.info(f"Reset triggered: Price touched {self.curve_type} level {level}")
                    return True
        
        return False
    
    def _reset_orders(self):
        """Reset mechanism: Cancel all active orders"""
        if self.active_orders:
            self.logger.info(f"Resetting: Canceling {len(self.active_orders)} active orders")
            self.active_orders.clear()
    
    def _check_zone_penetration(self, current_price: float, curve_data: Dict, market_data: Dict) -> Dict:
        """
        Check if price has completely penetrated through a zone
        """
        zones = curve_data['zones']
        momentum_direction = curve_data['momentum_direction']
        
        for zone in zones:
            if momentum_direction == 'POSITIVE' and zone['zone_type'] == 'BUY':
                # Check if price penetrated from below to above the BUY zone
                if current_price > zone['zone_top']:
                    return {
                        'penetrated': True,
                        'zone': zone,
                        'direction': 'BUY',
                        'penetration_type': 'UPWARD_BREAKOUT'
                    }
            
            elif momentum_direction == 'NEGATIVE' and zone['zone_type'] == 'SELL':
                # Check if price penetrated from above to below the SELL zone  
                if current_price < zone['zone_bottom']:
                    return {
                        'penetrated': True,
                        'zone': zone,
                        'direction': 'SELL',
                        'penetration_type': 'DOWNWARD_BREAKOUT'
                    }
        
        return {'penetrated': False}
    
    def generate_signal(self, analysis: Dict) -> Optional[Dict]:
        """
        Generate dual limit order signals when zone penetration occurs
        Returns primary signal for base strategy compatibility
        """
        if not analysis.get('curve_data') or not analysis.get('penetration', {}).get('penetrated'):
            return None
        
        penetration = analysis['penetration']
        zone = penetration['zone']
        direction = penetration['direction']
        current_price = analysis['current_price']
        instrument = analysis['instrument']
        
        # Create dual limit orders
        signals = []
        
        if direction == 'BUY':
            # Order 1: Limit BUY at psychological level
            signal_1 = self._create_limit_buy_signal(
                instrument, zone['level'], zone['target_level'], 
                zone['stop_level'], current_price, 1
            )
            
            # Order 2: Limit BUY at zone top (edge) with adjusted stop
            zone_edge_stop = zone['zone_top'] - (self.stop_loss_pips * analysis['curve_data']['pip_value'])
            signal_2 = self._create_limit_buy_signal(
                instrument, zone['zone_top'], zone['target_level'],
                zone_edge_stop, current_price, 2
            )
            
        else:  # SELL
            # Order 1: Limit SELL at psychological level
            signal_1 = self._create_limit_sell_signal(
                instrument, zone['level'], zone['target_level'],
                zone['stop_level'], current_price, 1
            )
            
            # Order 2: Limit SELL at zone bottom (edge) with adjusted stop
            zone_edge_stop = zone['zone_bottom'] + (self.stop_loss_pips * analysis['curve_data']['pip_value'])
            signal_2 = self._create_limit_sell_signal(
                instrument, zone['zone_bottom'], zone['target_level'],
                zone_edge_stop, current_price, 2
            )
        
        signals = [signal_1, signal_2]
        
        # Add to active orders tracking
        self.active_orders.extend(signals)
        
        self.logger.info(f"Generated dual limit orders: {direction} at {zone['level']} ({self.curve_type})")
        
        # Return first signal for base strategy compatibility
        return signal_1
    
    def _create_limit_buy_signal(self, instrument: str, entry_price: float, 
                                take_profit: float, stop_loss: float,
                                current_price: float, order_num: int) -> Dict:
        """Create a limit BUY order signal"""
        
        # Calculate R:R ratio
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price) 
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Calculate confidence based on curve type and order positioning
        base_confidence = {
            "PENNY": 80, "QUARTER": 85, "DIME": 90
        }.get(self.curve_type, 80)
        
        if order_num == 1:  # Level order (better R:R)
            confidence = base_confidence + 15
        else:  # Zone edge order
            confidence = base_confidence + 10
        
        return {
            'action': 'BUY',
            'order_type': 'LIMIT',
            'instrument': instrument,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_amount': self.risk_per_trade,
            'rr_ratio': round(rr_ratio, 2),
            'confidence': confidence,
            'order_number': order_num,
            'reasoning': [
                f"{self.curve_type} DUAL LIMIT BUY #{order_num} - Zone penetration detected",
                f"Entry: {entry_price:.4f}, Target: {take_profit:.4f}",
                f"Bodyguards overwhelmed - momentum carrying through",
                f"R:R Ratio: {rr_ratio:.2f}:1",
                f"Football field strategy: {self.curve_type} level trading"
            ],
            'strategy_type': f'{self.curve_type}_DUAL_LIMIT',
            'timestamp': datetime.now(),
            'expiration': 'GOOD_TILL_CANCELLED'
        }
    
    def _create_limit_sell_signal(self, instrument: str, entry_price: float,
                                 take_profit: float, stop_loss: float, 
                                 current_price: float, order_num: int) -> Dict:
        """Create a limit SELL order signal"""
        
        # Calculate R:R ratio
        risk = abs(stop_loss - entry_price)
        reward = abs(entry_price - take_profit)
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Calculate confidence
        base_confidence = {
            "PENNY": 80, "QUARTER": 85, "DIME": 90
        }.get(self.curve_type, 80)
        
        if order_num == 1:  # Level order (better R:R)
            confidence = base_confidence + 15
        else:  # Zone edge order  
            confidence = base_confidence + 10
        
        return {
            'action': 'SELL',
            'order_type': 'LIMIT',
            'instrument': instrument,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_amount': self.risk_per_trade,
            'rr_ratio': round(rr_ratio, 2),
            'confidence': confidence,
            'order_number': order_num,
            'reasoning': [
                f"{self.curve_type} DUAL LIMIT SELL #{order_num} - Zone penetration detected",
                f"Entry: {entry_price:.4f}, Target: {take_profit:.4f}",
                f"Bodyguards overwhelmed - momentum carrying through", 
                f"R:R Ratio: {rr_ratio:.2f}:1",
                f"Football field strategy: {self.curve_type} level trading"
            ],
            'strategy_type': f'{self.curve_type}_DUAL_LIMIT',
            'timestamp': datetime.now(),
            'expiration': 'GOOD_TILL_CANCELLED'
        }
    
    def validate_signal(self, signal: Dict) -> Tuple[bool, str]:
        """
        Validate dual limit signals (adjusted for curve type)
        """
        if not signal:
            return False, "No signal generated"
        
        # Risk checks
        if signal.get('risk_amount', 0) > self.risk_per_trade:
            return False, f"Risk amount exceeds limit {self.risk_per_trade}"
        
        # R:R ratio check (higher expectations for larger curves)
        min_rr_by_curve = {
            "PENNY": 3.0 if signal.get('order_number') == 1 else 2.5,
            "QUARTER": 4.0 if signal.get('order_number') == 1 else 3.0,
            "DIME": 8.0 if signal.get('order_number') == 1 else 6.0
        }
        min_rr = min_rr_by_curve.get(self.curve_type, 3.0)
        
        if signal.get('rr_ratio', 0) < min_rr:
            return False, f"R:R ratio {signal['rr_ratio']} below minimum {min_rr} for {self.curve_type}"
        
        # Confidence check
        min_confidence = 75 if self.curve_type == "PENNY" else 80
        if signal.get('confidence', 0) < min_confidence:
            return False, f"Confidence {signal['confidence']}% below threshold"
        
        # Order type validation
        if signal.get('order_type') != 'LIMIT':
            return False, "Dual limit strategy requires LIMIT orders only"
        
        return True, f"Dual limit signal validated ({self.curve_type})"
    
    def calculate_position_size(self, signal: Dict, account_balance: float) -> float:
        """Calculate position size for dual limit orders"""
        risk_amount = signal.get('risk_amount', self.risk_per_trade)
        entry_price = signal.get('entry_price', 0)
        stop_loss = signal.get('stop_loss', 0)
        
        if entry_price == 0 or stop_loss == 0:
            return 0
        
        # Calculate pips at risk
        instrument = signal.get('instrument', '')
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        
        pips_at_risk = abs(entry_price - stop_loss) / pip_value
        
        if pips_at_risk == 0:
            return 0
        
        # Position size calculation (units per pip = $1 per pip for 10K units)
        position_size = (risk_amount / pips_at_risk) * 10000
        
        return round(position_size, 0)
    
    def get_active_orders(self) -> List[Dict]:
        """Get currently active orders"""
        return self.active_orders.copy()
    
    def cancel_all_orders(self):
        """Cancel all active orders (manual reset)"""
        self._reset_orders()
    
    def get_curve_info(self) -> Dict:
        """Get curve configuration information"""
        return {
            'curve_type': self.curve_type,
            'level_increment': self.level_increment,
            'zone_width_pips': self.zone_width_pips,
            'stop_loss_pips': self.stop_loss_pips,
            'expected_rr_range': self._get_expected_rr_range()
        }
    
    def _get_expected_rr_range(self) -> str:
        """Get expected R:R range for this curve type"""
        ranges = {
            "PENNY": "4-6:1",
            "QUARTER": "6-10:1", 
            "DIME": "12-20:1"
        }
        return ranges.get(self.curve_type, "Unknown")