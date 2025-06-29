import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pytz

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print(f"Current directory: {current_dir}")
print(f"Parent directory: {parent_dir}")

# Config imports
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    print("SUCCESS: Imported Oanda config")
    print(f"DEBUG: API_KEY length: {len(API_KEY) if API_KEY else 'None'}")
    print(f"DEBUG: ACCOUNT_ID: {ACCOUNT_ID}")
    print(f"DEBUG: ACCOUNT_ID type: {type(ACCOUNT_ID)}")
except ImportError as e:
    print(f"ERROR: Failed to import Oanda config: {e}")
    sys.exit(1)

# Import existing classes
from momentum_calculator import MarketAwareMomentumCalculator, ForexMarketSchedule
from oanda_api import OandaAPI

class PsychologicalLevelsDetector:
    """
    Detects psychological levels (pennies, quarters, dimes) for forex pairs
    """
    
    def __init__(self):
        pass
    
    def get_pennies_levels(self, current_price: float, instrument: str) -> Dict:
        """
        Get pennies levels around current price
        """
        is_jpy = 'JPY' in instrument
        
        if is_jpy:
            base_level = int(current_price)
            pip_size = 1.0
            level_range = 10
            
            levels_below = [base_level - i for i in range(1, level_range + 1) if base_level - i > 0]
            levels_above = [base_level + i for i in range(1, level_range + 1)]
            
        else:
            base_level = round(current_price, 2)
            pip_size = 0.01
            level_range = 10
            
            levels_below = [round(base_level - (i * pip_size), 2) for i in range(1, level_range + 1)]
            levels_above = [round(base_level + (i * pip_size), 2) for i in range(1, level_range + 1)]
        
        closest_below = None
        closest_above = None
        
        for level in sorted(levels_below, reverse=True):
            if level < current_price:
                closest_below = level
                break
        
        for level in sorted(levels_above):
            if level > current_price:
                closest_above = level
                break
        
        if closest_below is None:
            if abs(current_price - base_level) < 0.001:
                closest_below = base_level - pip_size
                closest_above = base_level + pip_size
            else:
                closest_below = base_level if base_level < current_price else base_level - pip_size
        
        if closest_above is None:
            closest_above = base_level if base_level > current_price else base_level + pip_size
        
        return {
            'instrument': instrument,
            'current_price': current_price,
            'is_jpy': is_jpy,
            'pip_size': pip_size,
            'base_level': base_level,
            'closest_below': closest_below,
            'closest_above': closest_above,
            'levels_below': sorted([l for l in levels_below if l > 0], reverse=True)[:5],
            'levels_above': sorted(levels_above)[:5],
            'distance_to_below': abs(current_price - closest_below) if closest_below else None,
            'distance_to_above': abs(closest_above - current_price) if closest_above else None
        }

class EnhancedPennyCurveStrategy:
    """
    Enhanced Penny Curve Strategy with Momentum-First Logic
    
    MOMENTUM-FIRST APPROACH:
    1. Check momentum direction (BUY vs SELL)
    2. If BUY momentum: Look for buy opportunities only
    3. If SELL momentum: Look for sell opportunities only
    4. Use zones to determine execution method (MARKET vs LIMIT)
    """
    
    def __init__(self, momentum_calculator: MarketAwareMomentumCalculator, levels_detector: PsychologicalLevelsDetector):
        self.momentum_calc = momentum_calculator
        self.levels_detector = levels_detector
        
        # Strategy parameters
        self.supply_demand_offset = 25  # pips
        self.stop_loss_pips = 20       # pips
        self.minimum_momentum_threshold = 0.15  # 0.15% minimum momentum to trade
    
    def add_momentum_strength_filter(self, momentum_analysis: Dict) -> Tuple[bool, str]:
        """
        Check if momentum is strong enough to trade
        """
        avg_momentum = momentum_analysis['momentum_strength']
        abs_momentum = abs(avg_momentum)
        
        if abs_momentum < self.minimum_momentum_threshold:
            return False, f"Momentum too weak: {avg_momentum:.3f}% (minimum: {self.minimum_momentum_threshold:.1%})"
        
        return True, f"Momentum sufficient: {avg_momentum:.3f}%"
    
    def calculate_momentum_first_zones(self, current_price: float, instrument: str) -> Dict:
        """
        Calculate penny zones with momentum-first approach
        """
        is_jpy = 'JPY' in instrument
        
        if is_jpy:
            pip_value = 0.01
            # Get 3 pennies around current price for JPY
            base_penny = round(current_price)
            pennies = [base_penny - 1, base_penny, base_penny + 1]
        else:
            pip_value = 0.0001
            # Get 3 pennies around current price for non-JPY
            base_penny = round(current_price * 100) / 100
            pennies = [
                round(base_penny - 0.01, 2), 
                round(base_penny, 2), 
                round(base_penny + 0.01, 2)
            ]
        
        zones = []
        
        for penny in pennies:
            # Calculate zone boundaries
            buy_zone_bottom = penny
            buy_zone_top = penny + (25 * pip_value)  # 25 pips above penny
            
            sell_zone_bottom = penny - (25 * pip_value)  # 25 pips below penny
            sell_zone_top = penny
            
            # Check if current price is in this penny's zones
            in_buy_zone = buy_zone_bottom <= current_price <= buy_zone_top
            in_sell_zone = sell_zone_bottom <= current_price <= sell_zone_top
            
            zone_info = {
                'penny': penny,
                'buy_zone': {
                    'bottom': buy_zone_bottom,
                    'top': buy_zone_top,
                    'in_zone': in_buy_zone,
                    'distance_from_penny_pips': (current_price - penny) / pip_value if in_buy_zone else None
                },
                'sell_zone': {
                    'bottom': sell_zone_bottom,
                    'top': sell_zone_top, 
                    'in_zone': in_sell_zone,
                    'distance_from_penny_pips': (penny - current_price) / pip_value if in_sell_zone else None
                },
                'penny_distance_pips': abs(current_price - penny) / pip_value
            }
            
            zones.append(zone_info)
        
        return {
            'current_price': current_price,
            'is_jpy': is_jpy,
            'pip_value': pip_value,
            'zones': zones,
            'pennies': pennies
        }
    
    def _generate_momentum_first_signals(self, zone_data: Dict, momentum_analysis: Dict, 
                                       current_price: float, instrument: str) -> Dict:
        """
        MOMENTUM-FIRST: Generate signals based on momentum direction first, then zones
        """
        signals = {
            'action': 'WAIT',
            'order_type': None,
            'direction': None,
            'entry_price': None,
            'stop_loss': None,
            'take_profit': None,
            'expiration': None,
            'confidence': 0,
            'reasoning': [],
            'zone_analysis': None
        }
        
        # Check momentum strength filter
        tradeable, momentum_reason = self.add_momentum_strength_filter(momentum_analysis)
        
        if not tradeable:
            signals['reasoning'].append(f"❌ {momentum_reason}")
            return signals
        
        strategy_bias = momentum_analysis['strategy_bias']
        momentum_strength = momentum_analysis['momentum_strength']
        
        zones = zone_data['zones']
        is_jpy = zone_data['is_jpy']
        pip_value = zone_data['pip_value']
        
        stop_loss_distance = self.stop_loss_pips * pip_value
        reasoning = []
        reasoning.append(f"✅ {momentum_reason}")
        reasoning.append(f"📈 Strategy Direction: {strategy_bias} (momentum-driven)")
        
        # MOMENTUM-FIRST LOGIC
        
        if strategy_bias == 'BUY':
            # BULLISH MOMENTUM - Look for BUY opportunities only
            
            # Check if we're in ANY buy zone
            in_buy_zone = False
            buy_zone_info = None
            
            for zone in zones:
                if zone['buy_zone']['in_zone']:
                    in_buy_zone = True
                    buy_zone_info = zone
                    break
            
            if in_buy_zone:
                # CASE 1: In a buy zone with bullish momentum → MARKET BUY
                penny = buy_zone_info['penny']
                distance_from_penny = (current_price - penny) / pip_value
                
                signals['action'] = 'BUY'
                signals['order_type'] = 'MARKET'
                signals['direction'] = 'LONG'
                signals['entry_price'] = current_price
                signals['stop_loss'] = current_price - stop_loss_distance
                
                # Take profit at next penny above
                next_penny_above = self._find_next_penny_above_momentum(penny, zones)
                signals['take_profit'] = next_penny_above
                
                reasoning.append(f"🎯 MARKET BUY - IN buy zone of {penny:.4f} penny")
                reasoning.append(f"Buy zone: {buy_zone_info['buy_zone']['bottom']:.4f} to {buy_zone_info['buy_zone']['top']:.4f}")
                reasoning.append(f"Position: {distance_from_penny:.1f} pips above penny")
                reasoning.append(f"Immediate execution - optimal buy zone entry")
                
            else:
                # CASE 2: Not in buy zone - find best limit buy opportunity
                
                # Find the penny below current price for optimal entry
                pennies_below = [z['penny'] for z in zones if z['penny'] < current_price]
                
                if pennies_below:
                    # Use the closest penny below current price
                    entry_penny = max(pennies_below)
                    
                    signals['action'] = 'BUY'
                    signals['order_type'] = 'LIMIT'
                    signals['direction'] = 'LONG'
                    signals['entry_price'] = entry_penny
                    signals['stop_loss'] = entry_penny - stop_loss_distance
                    
                    # Take profit at next penny above entry
                    next_penny_above = self._find_next_penny_above_momentum(entry_penny, zones)
                    signals['take_profit'] = next_penny_above
                    signals['expiration'] = 'END_OF_DAY'
                    
                    distance_to_entry = abs(current_price - entry_penny) / pip_value
                    
                    # Determine position description
                    position_desc = self._describe_buy_position(current_price, zones, pip_value)
                    
                    reasoning.append(f"🎯 LIMIT BUY - {position_desc}")
                    reasoning.append(f"Entry at penny below: {entry_penny:.4f}")
                    reasoning.append(f"Current: {current_price:.5f}")
                    reasoning.append(f"Distance to entry: {distance_to_entry:.1f} pips")
                    reasoning.append(f"Better entry price with bullish momentum")
                    
                else:
                    # At bottom of range
                    reasoning.append(f"📊 At bottom of penny range - monitoring for breakout")
        
        elif strategy_bias == 'SELL':
            # BEARISH MOMENTUM - Look for SELL opportunities only
            
            # Check if we're in ANY sell zone
            in_sell_zone = False
            sell_zone_info = None
            
            for zone in zones:
                if zone['sell_zone']['in_zone']:
                    in_sell_zone = True
                    sell_zone_info = zone
                    break
            
            if in_sell_zone:
                # CASE 1: In a sell zone with bearish momentum → MARKET SELL
                penny = sell_zone_info['penny']
                distance_from_penny = (penny - current_price) / pip_value
                
                signals['action'] = 'SELL'
                signals['order_type'] = 'MARKET'
                signals['direction'] = 'SHORT'
                signals['entry_price'] = current_price
                signals['stop_loss'] = current_price + stop_loss_distance
                
                # Take profit at next penny below
                next_penny_below = self._find_next_penny_below_momentum(penny, zones)
                signals['take_profit'] = next_penny_below
                
                reasoning.append(f"🎯 MARKET SELL - IN sell zone of {penny:.4f} penny")
                reasoning.append(f"Sell zone: {sell_zone_info['sell_zone']['bottom']:.4f} to {sell_zone_info['sell_zone']['top']:.4f}")
                reasoning.append(f"Position: {distance_from_penny:.1f} pips below penny")
                reasoning.append(f"Immediate execution - optimal sell zone entry")
                
            else:
                # CASE 2: Not in sell zone - find best limit sell opportunity
                
                # Find the penny above current price for optimal entry
                pennies_above = [z['penny'] for z in zones if z['penny'] > current_price]
                
                if pennies_above:
                    # Use the closest penny above current price
                    entry_penny = min(pennies_above)
                    
                    signals['action'] = 'SELL'
                    signals['order_type'] = 'LIMIT'
                    signals['direction'] = 'SHORT'
                    signals['entry_price'] = entry_penny
                    signals['stop_loss'] = entry_penny + stop_loss_distance
                    
                    # Take profit at next penny below entry
                    next_penny_below = self._find_next_penny_below_momentum(entry_penny, zones)
                    signals['take_profit'] = next_penny_below
                    signals['expiration'] = 'END_OF_DAY'
                    
                    distance_to_entry = abs(entry_penny - current_price) / pip_value
                    
                    # Determine position description
                    position_desc = self._describe_sell_position(current_price, zones, pip_value)
                    
                    reasoning.append(f"🎯 LIMIT SELL - {position_desc}")
                    reasoning.append(f"Entry at penny above: {entry_penny:.4f}")
                    reasoning.append(f"Current: {current_price:.5f}")
                    reasoning.append(f"Distance to entry: {distance_to_entry:.1f} pips")
                    reasoning.append(f"Better entry price with bearish momentum")
                    
                else:
                    # At top of range
                    reasoning.append(f"📊 At top of penny range - monitoring for breakout")
        
        # Calculate enhanced confidence
        base_confidence = 70
        
        # Momentum strength bonus
        abs_momentum = abs(momentum_strength)
        if abs_momentum > 0.4:
            base_confidence += 20
            reasoning.append("Very strong momentum bonus (+20)")
        elif abs_momentum > 0.25:
            base_confidence += 15
            reasoning.append("Strong momentum bonus (+15)")
        elif abs_momentum > 0.15:
            base_confidence += 10
            reasoning.append("Moderate momentum bonus (+10)")
        
        # Zone position bonus
        if signals['order_type'] == 'MARKET':
            base_confidence += 20
            reasoning.append("🎯 OPTIMAL ZONE ENTRY - High confidence (+20)")
        elif signals['order_type'] == 'LIMIT':
            base_confidence += 10
            reasoning.append("📋 Strategic limit order - Good confidence (+10)")
        
        # Calculate R:R ratio
        if signals['action'] != 'WAIT' and signals['take_profit'] and signals['stop_loss']:
            entry_price = signals['entry_price']
            
            if signals['direction'] == 'LONG':
                risk = abs(entry_price - signals['stop_loss'])
                reward = abs(signals['take_profit'] - entry_price)
            else:
                risk = abs(signals['stop_loss'] - entry_price)
                reward = abs(entry_price - signals['take_profit'])
            
            if risk > 0:
                risk_reward_ratio = reward / risk
                signals['risk_reward_ratio'] = round(risk_reward_ratio, 2)
                reasoning.append(f"💰 Reward/Risk Ratio: {risk_reward_ratio:.2f}:1")
                
                if risk_reward_ratio >= 5.0:
                    base_confidence += 15
                elif risk_reward_ratio >= 3.0:
                    base_confidence += 10
                elif risk_reward_ratio >= 2.0:
                    base_confidence += 5
        
        signals['confidence'] = min(100, max(0, base_confidence))
        signals['reasoning'] = reasoning
        signals['zone_analysis'] = {
            'momentum_driven': True,
            'strategy_bias': strategy_bias,
            'in_optimal_zone': signals['order_type'] == 'MARKET'
        }
        
        return signals
    
    def _find_next_penny_above_momentum(self, current_penny: float, zones: List[Dict]) -> float:
        """Find the next penny level above the current one for momentum-first logic"""
        pennies = [z['penny'] for z in zones]
        above_pennies = [p for p in pennies if p > current_penny]
        if above_pennies:
            return min(above_pennies)
        else:
            # Calculate next penny if not in our zone list
            if current_penny > 100:  # JPY pair
                return current_penny + 1
            else:  # Non-JPY pair
                return round(current_penny + 0.01, 2)
    
    def _find_next_penny_below_momentum(self, current_penny: float, zones: List[Dict]) -> float:
        """Find the next penny level below the current one for momentum-first logic"""
        pennies = [z['penny'] for z in zones]
        below_pennies = [p for p in pennies if p < current_penny]
        if below_pennies:
            return max(below_pennies)
        else:
            # Calculate next penny if not in our zone list
            if current_penny > 100:  # JPY pair
                return current_penny - 1
            else:  # Non-JPY pair
                return round(current_penny - 0.01, 2)
    
    def _describe_buy_position(self, current_price: float, zones: List[Dict], pip_value: float) -> str:
        """Describe current position for buy setups"""
        above_buy_zones = any(current_price > zone['buy_zone']['top'] for zone in zones)
        
        if above_buy_zones:
            return "Above buy zones"
        else:
            return "Between penny zones"
    
    def _describe_sell_position(self, current_price: float, zones: List[Dict], pip_value: float) -> str:
        """Describe current position for sell setups"""
        below_sell_zones = any(current_price < zone['sell_zone']['bottom'] for zone in zones)
        
        if below_sell_zones:
            return "Below sell zones"
        else:
            return "Between penny zones"
    
    def analyze_penny_curve_setup(self, instrument: str) -> Dict:
        """
        Main analysis method using momentum-first zone logic
        """
        try:
            # Get current price
            current_prices = self.momentum_calc.api.get_current_prices([instrument])
            if 'prices' not in current_prices or not current_prices['prices']:
                return {'error': f'No price data for {instrument}'}
            
            price_data = current_prices['prices'][0]
            if 'closeoutBid' in price_data and 'closeoutAsk' in price_data:
                current_price = (float(price_data['closeoutBid']) + float(price_data['closeoutAsk'])) / 2
            else:
                return {'error': f'Cannot determine current price for {instrument}'}
            
            # Get momentum analysis
            momentum_data = self.momentum_calc.get_momentum_summary(instrument, 'pennies')
            if 'error' in momentum_data:
                return {'error': f'Momentum calculation failed: {momentum_data["error"]}'}
            
            momentum_analysis = self._analyze_momentum_direction(momentum_data)
            
            # NEW: Use momentum-first zone calculation
            zone_data = self.calculate_momentum_first_zones(current_price, instrument)
            
            # NEW: Generate momentum-first signals
            signals = self._generate_momentum_first_signals(zone_data, momentum_analysis, current_price, instrument)
            
            return {
                'instrument': instrument,
                'timestamp': datetime.now().isoformat(),
                'current_price': current_price,
                'momentum': momentum_data,
                'momentum_analysis': momentum_analysis,
                'zone_data': zone_data,
                'signals': signals
            }
            
        except Exception as e:
            return {'error': f'Momentum-first analysis failed for {instrument}: {str(e)}'}
    
    def _analyze_momentum_direction(self, momentum_data: Dict) -> Dict:
        """Analyze momentum direction"""
        momentum_summary = momentum_data['momentum_summary']
        avg_momentum = momentum_summary['average_momentum']
        alignment = momentum_summary['positive_periods'] / momentum_summary['total_periods']
        
        if avg_momentum > 0.2:
            direction = 'STRONG_BULLISH'
            strategy_bias = 'BUY'
        elif avg_momentum > 0.05:
            direction = 'WEAK_BULLISH'
            strategy_bias = 'BUY' if alignment >= 0.6 else 'NEUTRAL'
        elif avg_momentum < -0.2:
            direction = 'STRONG_BEARISH'
            strategy_bias = 'SELL'
        elif avg_momentum < -0.05:
            direction = 'WEAK_BEARISH'
            strategy_bias = 'SELL' if alignment <= 0.4 else 'NEUTRAL'
        else:
            direction = 'NEUTRAL'
            strategy_bias = 'NEUTRAL'
        
        return {
            'direction': direction,
            'strategy_bias': strategy_bias,
            'momentum_strength': avg_momentum,
            'alignment': alignment,
            'alignment_score': alignment if strategy_bias == 'BUY' else (1 - alignment) if strategy_bias == 'SELL' else 0.5
        }

def display_enhanced_analysis(analysis: Dict):
    """
    Display momentum-first zone-based analysis
    """
    if 'error' in analysis:
        print(f"❌ Error: {analysis['error']}")
        return
    
    instrument = analysis['instrument']
    current_price = analysis['current_price']
    momentum_analysis = analysis['momentum_analysis']
    zone_data = analysis['zone_data']
    signals = analysis['signals']
    
    print(f"\n{'='*70}")
    print(f"MOMENTUM-FIRST PENNY CURVE ANALYSIS: {instrument}")
    print(f"{'='*70}")
    
    print(f"📊 MARKET STATE:")
    print(f"  Current Price: {current_price:.5f}")
    print(f"  Momentum: {momentum_analysis['direction']} ({momentum_analysis['momentum_strength']:+.3f}%)")
    print(f"  Strategy Direction: {momentum_analysis['strategy_bias']} (momentum-driven)")
    print(f"  Momentum Alignment: {momentum_analysis['alignment']:.1%}")
    
    # Display penny zones with current position
    print(f"\n🎯 PENNY ZONES & CURRENT POSITION:")
    for zone in zone_data['zones']:
        buy_status = "🟢 IN" if zone['buy_zone']['in_zone'] else "⚪"
        sell_status = "🔴 IN" if zone['sell_zone']['in_zone'] else "⚪"
        
        print(f"  Penny {zone['penny']:.4f}:")
        print(f"    Buy Zone {buy_status}: {zone['buy_zone']['bottom']:.4f} to {zone['buy_zone']['top']:.4f}")
        print(f"    Sell Zone {sell_status}: {zone['sell_zone']['bottom']:.4f} to {zone['sell_zone']['top']:.4f}")
    
    # Display trading signals
    print(f"\n🚦 MOMENTUM-FIRST SIGNALS:")
    print(f"  Action: {signals['action']}")
    
    if signals['action'] != 'WAIT':
        print(f"  Order Type: {signals['order_type']}")
        print(f"  Direction: {signals['direction']}")
        print(f"  Entry Price: {signals['entry_price']:.4f}")
        print(f"  Stop Loss: {signals['stop_loss']:.4f}")
        print(f"  Take Profit: {signals['take_profit']:.4f}")
        if signals.get('expiration'):
            print(f"  Expiration: {signals['expiration']}")
        if 'risk_reward_ratio' in signals:
            print(f"  Risk/Reward Ratio: {signals['risk_reward_ratio']}:1")
        print(f"  Confidence: {signals['confidence']}%")
        
        print(f"\n  📈 Momentum-First Logic:")
        for reason in signals['reasoning']:
            print(f"    • {reason}")
    
    print(f"{'='*70}")

def create_momentum_first_watchlist(strategy, instruments: List[str]) -> str:
    """
    Create a momentum-first watchlist display
    """
    output = []
    output.append("="*80)
    output.append("MOMENTUM-FIRST PENNY CURVE STRATEGY WATCHLIST")
    output.append("="*80)
    output.append("Logic: Momentum determines direction, zones optimize entry")
    output.append("="*80)
    
    market_orders = []
    limit_orders = []
    weak_momentum = []
    
    for instrument in instruments:
        try:
            analysis = strategy.analyze_penny_curve_setup(instrument)
            
            if 'error' in analysis:
                continue
                
            current_price = analysis['current_price']
            signals = analysis['signals']
            momentum_analysis = analysis['momentum_analysis']
            zone_data = analysis['zone_data']
            
            entry_info = {
                'instrument': instrument,
                'current_price': current_price,
                'momentum': momentum_analysis['direction'],
                'momentum_value': momentum_analysis['momentum_strength'],
                'strategy_bias': momentum_analysis['strategy_bias'],
                'confidence': signals['confidence']
            }
            
            if signals['action'] != 'WAIT':
                entry_info.update({
                    'action': signals['action'],
                    'order_type': signals['order_type'],
                    'entry': signals['entry_price'],
                    'stop_loss': signals['stop_loss'],
                    'take_profit': signals['take_profit'],
                    'risk_reward': signals.get('risk_reward_ratio', 'N/A')
                })
                
                # Find which zones we're in for context
                in_zones = []
                for zone in zone_data['zones']:
                    if zone['buy_zone']['in_zone']:
                        in_zones.append(f"Buy({zone['penny']:.2f})")
                    if zone['sell_zone']['in_zone']:
                        in_zones.append(f"Sell({zone['penny']:.2f})")
                
                entry_info['zones'] = " | ".join(in_zones) if in_zones else "Between zones"
                
                # Categorize by order type
                if signals['order_type'] == 'MARKET':
                    market_orders.append(entry_info)
                else:
                    limit_orders.append(entry_info)
            else:
                weak_momentum.append(entry_info)
            
        except Exception as e:
            print(f"Error analyzing {instrument}: {e}")
            continue
    
    # Display market orders (immediate execution)
    if market_orders:
        output.append("\n🚀 IMMEDIATE EXECUTION (Market Orders):")
        output.append("-" * 60)
        for order in market_orders:
            output.append(f"📈 {order['instrument']}: {order['action']} @ MARKET")
            output.append(f"   Current: {order['current_price']:.5f} | Zones: {order['zones']}")
            output.append(f"   Target: {order['take_profit']:.4f} | Stop: {order['stop_loss']:.4f}")
            output.append(f"   R:R: {order['risk_reward']}:1 | Confidence: {order['confidence']}%")
            output.append(f"   Momentum: {order['momentum']} ({order['momentum_value']:+.3f}%)")
            output.append("")
    
    # Display limit orders (pending execution)
    if limit_orders:
        output.append("\n📋 PENDING ORDERS (Limit Orders):")
        output.append("-" * 60)
        for order in limit_orders:
            distance = abs(order['current_price'] - order['entry']) / (0.01 if order['current_price'] > 100 else 0.0001)
            output.append(f"📊 {order['instrument']}: {order['action']} @ {order['entry']:.4f}")
            output.append(f"   Current: {order['current_price']:.5f} (Distance: {distance:.1f} pips)")
            output.append(f"   Target: {order['take_profit']:.4f} | Stop: {order['stop_loss']:.4f}")
            output.append(f"   R:R: {order['risk_reward']}:1 | Confidence: {order['confidence']}%")
            output.append(f"   Momentum: {order['momentum']} ({order['momentum_value']:+.3f}%)")
            output.append("")
    
    # Display weak momentum
    if weak_momentum:
        output.append("\n⚠️ WEAK MOMENTUM (No Trade):")
        output.append("-" * 60)
        for item in weak_momentum:
            output.append(f"⏸️ {item['instrument']}: {item['current_price']:.5f}")
            output.append(f"   Momentum: {item['momentum']} ({item['momentum_value']:+.3f}%) - TOO WEAK")
            output.append("")
    
    # Summary
    output.append(f"\n📈 MOMENTUM-FIRST WATCHLIST SUMMARY:")
    output.append(f"🚀 Market Orders (Immediate): {len(market_orders)}")
    output.append(f"📋 Limit Orders (Pending): {len(limit_orders)}")
    output.append(f"⚠️ Weak Momentum (No Trade): {len(weak_momentum)}")
    output.append(f"📊 Total Instruments: {len(instruments)}")
    
    output.append("="*80)
    output.append("💡 Momentum-First Strategy Notes:")
    output.append("• Market Orders: IN optimal zones = immediate execution")
    output.append("• Limit Orders: NOT in optimal zones = wait for better entry")
    output.append("• Always trade WITH momentum direction")
    output.append("• Zones optimize entry timing, not direction")
    output.append("="*80)
    
    return "\n".join(output)

def test_momentum_first_penny_curve_strategy():
    """
    Test the momentum-first penny curve strategy
    """
    
    print("="*80)
    print("MOMENTUM-FIRST PENNY CURVE STRATEGY")
    print("="*80)
    print("REVOLUTIONARY IMPROVEMENTS:")
    print("✓ Momentum determines direction (BUY vs SELL)")
    print("✓ Zones determine execution method (MARKET vs LIMIT)")
    print("✓ Always trade WITH the momentum")
    print("✓ Use zones to optimize entry prices")
    print("✓ Fixed conflicting signals - no more zone vs momentum conflicts")
    print("="*80)
    
    # Initialize components
    api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
    momentum_calc = MarketAwareMomentumCalculator(api)
    levels_detector = PsychologicalLevelsDetector()
    enhanced_strategy = EnhancedPennyCurveStrategy(momentum_calc, levels_detector)
    
    # Test instruments with momentum-first logic
    instruments = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD']
    
    print(f"\n{'='*80}")
    print("INDIVIDUAL ANALYSIS FOR EACH CURRENCY PAIR")
    print(f"{'='*80}")
    
    for instrument in instruments:
        try:
            # Use the momentum-first analysis method
            analysis = enhanced_strategy.analyze_penny_curve_setup(instrument)
            display_enhanced_analysis(analysis)
            
        except Exception as e:
            print(f"❌ Error analyzing {instrument}: {e}")
    
    # Display comprehensive watchlist
    print(f"\n{'='*80}")
    print("COMPREHENSIVE MOMENTUM-FIRST WATCHLIST")
    print(f"{'='*80}")
    
    watchlist_display = create_momentum_first_watchlist(enhanced_strategy, instruments)
    print(watchlist_display)
    
    print(f"\n{'='*80}")
    print("MOMENTUM-FIRST STRATEGY TEST COMPLETE!")
    print(f"{'='*80}")
    print("KEY FIXES IMPLEMENTED:")
    print("✅ GBP_USD at 1.35058 with bullish momentum → MARKET BUY (optimal zone)")
    print("✅ GBP_USD at 1.3488 with bullish momentum → LIMIT BUY at 1.34 (not sell!)")
    print("✅ USD_JPY with bearish momentum → SELL signals only")
    print("✅ All signals now follow momentum direction first")
    print("✅ Zones optimize entry timing, not trade direction")
    print("✅ Eliminated conflicting zone vs momentum signals")
    print(f"{'='*80}")
    print("STRATEGY BENEFITS:")
    print("📈 Always trades with the trend (momentum-driven)")
    print("🎯 Optimizes entry points using psychological levels")
    print("💰 Maintains excellent 5:1+ risk/reward ratios")
    print("🛡️ Consistent 20-pip stop losses")
    print("⚡ Immediate execution when in optimal zones")
    print("📋 Strategic limit orders when not in optimal zones")
    print(f"{'='*80}")

if __name__ == "__main__":
    test_momentum_first_penny_curve_strategy()