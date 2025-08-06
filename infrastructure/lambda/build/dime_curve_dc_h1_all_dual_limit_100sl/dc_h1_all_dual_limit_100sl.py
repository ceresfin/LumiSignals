#!/usr/bin/env python3
"""
DC_H1_ALL_DUAL_LIMIT_100SL - Dime Curve H1 Dual Limit Strategy with 100-pip Stop Loss
Template-based implementation targeting dime psychological levels (0.1 increments)

Dime Curve Concept:
- Dime levels = 0.10 increments (1.1000, 1.2000, 1.3000, etc.)
- Zone width = 250 pips (10x penny curve)
- Stop loss = 100 pips (wider stops for dime moves)
- Expected R:R = 3-6:1 (dime moves with wider stops)
"""

import sys
import os
from typing import Dict

# Add parent directories to path
current_dir = os.path.dirname(os.path.abspath(__file__))
strategies_dir = os.path.dirname(os.path.dirname(current_dir))
src_dir = os.path.dirname(strategies_dir)
sys.path.extend([strategies_dir, src_dir])

from dual_limit_curve_template import DualLimitCurveTemplate

class DC_H1_ALL_DUAL_LIMIT_100SL(DualLimitCurveTemplate):
    """
    Dime Curve H1 Dual Limit Strategy with 100-pip Stop Loss
    
    Configuration:
    - Level increment: 0.10 (dime levels)
    - Zone width: 250 pips (10x penny curve)
    - Stop loss: 100 pips
    - Expected R:R: 3-6:1
    
    Dime Levels Examples:
    - EUR_USD: 1.1000, 1.2000, 1.3000, 1.4000, 1.5000, 1.6000
    - GBP_USD: 1.2000, 1.3000, 1.4000, 1.5000, 1.6000, 1.7000
    - USD_JPY: 100.0, 110.0, 120.0, 130.0, 140.0, 150.0
    """
    
    def __init__(self, config: Dict):
        # Set dime curve parameters before calling parent
        self.level_increment = 0.10   # Dime level spacing (0.10 increments)
        self.zone_width_pips = 250    # 250-pip bodyguard zones (10x penny)
        self.curve_type = "DIME"      # Curve identifier
        
        super().__init__("DC_H1_ALL_DUAL_LIMIT_100SL", config)
        
        self.logger.info(f"Initialized {self.strategy_id} - Template-based Dime Curve")
        self.logger.info(f"Level increment: {self.level_increment}, Zone: {self.zone_width_pips} pips")
        self.logger.info(f"Expected R:R range: {self._get_expected_rr_range()}")
    
    def _set_curve_parameters(self):
        """Required by parent class - already set in __init__"""
        pass
    
    def _detect_psychological_levels_and_zones(self, current_price: float, instrument: str) -> Dict:
        """
        Override to handle dime-specific level detection for major psychological levels
        """
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        zone_buffer = self.zone_width_pips * pip_value  # 250 pips
        
        # Calculate dime levels based on instrument type
        if is_jpy:
            # JPY dime levels: 100.0, 110.0, 120.0, 130.0, etc.
            base_level = round(current_price / 10) * 10  # Round to nearest 10
            level_range = 3  # Fewer levels since they're much farther apart
            levels = [base_level + (i * 10) for i in range(-level_range, level_range + 1)]
        else:
            # Non-JPY dime levels: 1.1, 1.2, 1.3, 1.4, 1.5, etc. (0.1 increments)
            base_level = round(current_price, 1)  # Round to nearest 0.1
            level_range = 5  # Reasonable range of dime levels
            levels = [round(base_level + (i * self.level_increment), 1) 
                     for i in range(-level_range, level_range + 1)]
        
        # Filter positive levels
        levels = [level for level in levels if level > 0]
        
        # Create zones based on momentum direction
        zones = []
        for i, level in enumerate(levels):
            if self.current_momentum_direction == 'POSITIVE':
                # BUY zones: 250 pips ABOVE each dime level
                # Target next major level up
                next_level = levels[i + 1] if i + 1 < len(levels) else level + 0.5
                zone = {
                    'level': level,
                    'zone_type': 'BUY',
                    'zone_bottom': level,
                    'zone_top': level + zone_buffer,
                    'target_level': next_level,  # Next major dime up
                    'stop_level': level - (self.stop_loss_pips * pip_value)
                }
            else:
                # SELL zones: 250 pips BELOW each dime level
                # Target next major level down
                prev_level = levels[i - 1] if i - 1 >= 0 else level - 0.5
                zone = {
                    'level': level,
                    'zone_type': 'SELL', 
                    'zone_bottom': level - zone_buffer,
                    'zone_top': level,
                    'target_level': prev_level,  # Next major dime down
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

def test_dime_curve_strategy():
    """Test the dime curve strategy"""
    config = {
        'momentum_threshold': 0.05,
        'stop_loss_pips': 100,
        'risk_per_trade': 5.0,
        'debug_mode': True,
        'log_signals': True
    }
    
    strategy = DC_H1_ALL_DUAL_LIMIT_100SL(config)
    
    # Test market data with dime level zone penetration
    market_data = {
        'instrument': 'EUR_USD',
        'current_price': 1.1251,  # Above 1.1000 + 250 pips zone (penetration)
        'momentum_60m': 0.08,     # Positive momentum
        'momentum_4h': 0.10
    }
    
    analysis = strategy.analyze_market(market_data)
    signal = strategy.generate_signal(analysis)
    
    if signal:
        print(f"Dime Curve Strategy Signal:")
        is_valid, reason = strategy.validate_signal(signal)
        print(f"Primary Order: {signal['action']} at {signal['entry_price']}")
        print(f"  Target: {signal['take_profit']}, Stop: {signal['stop_loss']}")
        print(f"  R:R: {signal['rr_ratio']}, Valid: {is_valid}")
        print(f"  Reasoning: {signal['reasoning'][0]}")
        
        # Show curve info
        curve_info = strategy.get_curve_info()
        print(f"\nCurve Info: {curve_info}")
        
        # Show detected levels
        if analysis.get('curve_data'):
            levels = analysis['curve_data']['levels']
            print(f"\nDetected Dime Levels: {levels}")
        
        # Show all active orders
        active_orders = strategy.get_active_orders()
        print(f"\nActive Orders: {len(active_orders)}")
        for i, order in enumerate(active_orders, 1):
            print(f"  Order {i}: {order['action']} at {order['entry_price']:.4f}")
            print(f"    R:R: {order['rr_ratio']}, Stop: {order['stop_loss']:.4f}")
    else:
        print("No signals generated")
        print(f"Analysis: {analysis.get('reason', 'No penetration detected')}")
        
        # Show why no signal
        if analysis.get('curve_data'):
            zones = analysis['curve_data']['zones']
            print(f"Current zones checked: {len(zones)}")
            for i, zone in enumerate(zones):
                print(f"  Zone {i+1}: {zone['zone_type']} {zone['zone_bottom']:.4f}-{zone['zone_top']:.4f}, In zone: {zone['in_zone']}")

def test_jpy_dime_levels():
    """Test JPY dime levels specifically"""
    config = {
        'momentum_threshold': 0.05,
        'stop_loss_pips': 100,
        'risk_per_trade': 5.0,
        'debug_mode': True
    }
    
    strategy = DC_H1_ALL_DUAL_LIMIT_100SL(config)
    
    # Test JPY with dime level zone penetration
    market_data = {
        'instrument': 'USD_JPY',
        'current_price': 112.51,  # Above 110.0 + 250 pips zone (penetration)
        'momentum_60m': 0.08,     # Positive momentum
        'momentum_4h': 0.10
    }
    
    print("\n" + "="*50)
    print("TESTING JPY DIME LEVELS")
    print("="*50)
    
    analysis = strategy.analyze_market(market_data)
    if analysis.get('curve_data'):
        levels = analysis['curve_data']['levels']
        print(f"JPY Dime Levels: {levels}")
        
        zones = analysis['curve_data']['zones']
        print(f"JPY Zones: {len(zones)} zones")
        for i, zone in enumerate(zones):
            print(f"  Zone {i+1}: {zone['zone_type']} {zone['zone_bottom']:.1f}-{zone['zone_top']:.1f}")

if __name__ == "__main__":
    test_dime_curve_strategy()
    test_jpy_dime_levels()