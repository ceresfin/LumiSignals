import os
import sys
import json
import logging
from datetime import datetime
from oandapyV20 import API
from oandapyV20.endpoints.transactions import TransactionIDRange
from oandapyV20.endpoints.trades import OpenTrades
from oandapyV20.endpoints.accounts import AccountSummary
from oandapyV20.endpoints.pricing import PricingInfo
from oandapyV20.exceptions import V20Error
from pyairtable import Api

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print("Starting Enhanced Oanda to Airtable sync with comprehensive price tracking...")
print(f"Current directory: {current_dir}")
print(f"Parent directory: {parent_dir}")

# Config imports with error handling
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    print("SUCCESS: Imported Oanda config")
except ImportError as e:
    print(f"ERROR: Failed to import Oanda config: {e}")
    sys.exit(1)

try:
    from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
    print("SUCCESS: Imported Airtable config")
except ImportError as e:
    print(f"ERROR: Failed to import Airtable config: {e}")
    sys.exit(1)

# ENHANCED: Import enhanced metadata storage
try:
    from metadata_storage import EnhancedTradeMetadataStore, EnhancedTradeMetadata, MarketContextData
    print("SUCCESS: Imported enhanced metadata storage")
    # Initialize enhanced metadata store
    metadata_store = EnhancedTradeMetadataStore()
    print(f"SUCCESS: Initialized enhanced metadata store with {len(metadata_store._metadata_cache)} entries")
except ImportError as e:
    print(f"WARNING: Could not import enhanced metadata storage: {e}")
    print("Falling back to original metadata parsing only")
    metadata_store = None

# Airtable setup with error handling
try:
    airtable_api = Api(AIRTABLE_API_TOKEN)
    table = airtable_api.table(BASE_ID, TABLE_NAME)
    print("SUCCESS: Airtable connection established")
except Exception as e:
    print(f"ERROR: Failed to connect to Airtable: {e}")
    sys.exit(1)

# Logging setup
log_dir = os.path.join(parent_dir, "logs")
os.makedirs(log_dir, exist_ok=True)
LOG_FILE = os.path.join(log_dir, "enhanced_sync.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- ENHANCED: Price Tracking Functions ---
def get_current_price(instrument):
    """
    Get current market price for an instrument from Oanda
    
    Args:
        instrument: Instrument pair (e.g., 'EUR_USD')
        
    Returns:
        dict: {'bid': float, 'ask': float, 'mid': float} or None if error
    """
    try:
        client = API(access_token=API_KEY, environment="practice")
        r = PricingInfo(accountID=ACCOUNT_ID, params={"instruments": instrument})
        client.request(r)
        
        prices = r.response.get("prices", [])
        if prices:
            price_data = prices[0]
            bid = float(price_data["bids"][0]["price"])
            ask = float(price_data["asks"][0]["price"])
            mid = (bid + ask) / 2
            
            logger.debug(f"💰 Current price for {instrument}: bid={bid}, ask={ask}, mid={mid}")
            return {
                'bid': bid,
                'ask': ask,
                'mid': mid
            }
    except Exception as e:
        logger.error(f"Error getting current price for {instrument}: {e}")
    
    return None

def extract_price_levels_from_transaction(tx):
    """
    Extract Stop Loss, Target Price, and Current Price from any transaction type
    
    Args:
        tx: Oanda transaction object
        
    Returns:
        dict: Price levels found in the transaction
    """
    price_levels = {
        'stop_loss_price': None,
        'target_price': None,
        'current_price': None,
        'entry_price': None
    }
    
    try:
        instrument = tx.get('instrument')
        
        # Get current market price
        if instrument:
            current_prices = get_current_price(instrument)
            if current_prices:
                price_levels['current_price'] = current_prices['mid']
                logger.info(f"💰 Current price for {instrument}: {current_prices['mid']}")
        
        # Extract entry price based on transaction type
        if tx.get('type') == 'ORDER_FILL':
            price_levels['entry_price'] = float(tx.get('price', 0))
        elif tx.get('type') in ['LIMIT_ORDER', 'MARKET_ORDER']:
            price_levels['entry_price'] = float(tx.get('price', 0))
        
        # Method 1: Direct fields in transaction
        if 'stopLossOnFill' in tx and tx['stopLossOnFill']:
            price_levels['stop_loss_price'] = float(tx['stopLossOnFill'].get('price', 0))
            logger.info(f"💰 Found stopLossOnFill: {price_levels['stop_loss_price']}")
        
        if 'takeProfitOnFill' in tx and tx['takeProfitOnFill']:
            price_levels['target_price'] = float(tx['takeProfitOnFill'].get('price', 0))
            logger.info(f"💰 Found takeProfitOnFill: {price_levels['target_price']}")
        
        # Method 2: In clientExtensions comment
        if 'clientExtensions' in tx and 'comment' in tx['clientExtensions']:
            comment = tx['clientExtensions']['comment']
            parts = comment.split('|')
            
            for part in parts:
                if ':' in part:
                    key, value = part.split(':', 1)
                    if key.strip() == 'StopLoss':
                        try:
                            price_levels['stop_loss_price'] = float(value.strip())
                            logger.info(f"💰 Found StopLoss in comment: {value.strip()}")
                        except ValueError:
                            pass
                    elif key.strip() == 'Target':
                        try:
                            price_levels['target_price'] = float(value.strip())
                            logger.info(f"💰 Found Target in comment: {value.strip()}")
                        except ValueError:
                            pass
        
        # Method 3: For ORDER_FILL, check tradeOpened for attached orders
        if tx.get('type') == 'ORDER_FILL' and 'tradeOpened' in tx:
            trade_opened = tx['tradeOpened']
            
            # Check for attached stop loss
            if 'stopLossOrder' in trade_opened:
                price_levels['stop_loss_price'] = float(trade_opened['stopLossOrder'].get('price', 0))
                logger.info(f"💰 Found stopLossOrder in tradeOpened: {price_levels['stop_loss_price']}")
            
            # Check for attached take profit
            if 'takeProfitOrder' in trade_opened:
                price_levels['target_price'] = float(trade_opened['takeProfitOrder'].get('price', 0))
                logger.info(f"💰 Found takeProfitOrder in tradeOpened: {price_levels['target_price']}")
        
        # Method 4: Check order details for limit orders
        if tx.get('type') == 'LIMIT_ORDER':
            # Look for stopLoss and takeProfit in order details
            if 'stopLoss' in tx:
                price_levels['stop_loss_price'] = float(tx['stopLoss'].get('price', 0))
                logger.info(f"💰 Found stopLoss in LIMIT_ORDER: {price_levels['stop_loss_price']}")
            
            if 'takeProfit' in tx:
                price_levels['target_price'] = float(tx['takeProfit'].get('price', 0))
                logger.info(f"💰 Found takeProfit in LIMIT_ORDER: {price_levels['target_price']}")
        
        # Method 5: Check for standalone STOP_LOSS_ORDER or TAKE_PROFIT_ORDER references
        if 'tradeID' in tx:
            trade_id = tx['tradeID']
            if tx.get('type') == 'STOP_LOSS_ORDER':
                price_levels['stop_loss_price'] = float(tx.get('price', 0))
                logger.info(f"💰 Found STOP_LOSS_ORDER price: {price_levels['stop_loss_price']}")
            elif tx.get('type') == 'TAKE_PROFIT_ORDER':
                price_levels['target_price'] = float(tx.get('price', 0))
                logger.info(f"💰 Found TAKE_PROFIT_ORDER price: {price_levels['target_price']}")
        
        logger.info(f"💰 Final extracted price levels for {instrument}: {price_levels}")
        return price_levels
        
    except Exception as e:
        logger.error(f"Error extracting price levels: {e}")
        return price_levels

def calculate_risk_metrics(entry_price, stop_loss_price, target_price, units, account_balance=None):
    """
    Calculate comprehensive risk metrics from price levels
    
    Args:
        entry_price: Entry price level
        stop_loss_price: Stop loss price level
        target_price: Target price level
        units: Trade size in units
        account_balance: Account balance for risk percentage calculation
        
    Returns:
        dict: Calculated risk metrics
    """
    metrics = {
        'risk_pips': None,
        'reward_pips': None,
        'rr_ratio': None,
        'risk_amount': None,
        'reward_amount': None,
        'risk_percent': None
    }
    
    try:
        if not all([entry_price, stop_loss_price, target_price]):
            return metrics
        
        # Determine direction based on stop loss position
        is_long = stop_loss_price < entry_price
        
        if is_long:
            risk_pips = abs(entry_price - stop_loss_price) * 10000
            reward_pips = abs(target_price - entry_price) * 10000
        else:
            risk_pips = abs(stop_loss_price - entry_price) * 10000
            reward_pips = abs(entry_price - target_price) * 10000
        
        metrics['risk_pips'] = risk_pips
        metrics['reward_pips'] = reward_pips
        
        # Calculate R:R ratio
        if risk_pips > 0:
            metrics['rr_ratio'] = reward_pips / risk_pips
        
        # Calculate monetary amounts
        if units > 0:
            pip_value = 0.0001  # Standard pip value for most pairs
            metrics['risk_amount'] = risk_pips * pip_value * units
            metrics['reward_amount'] = reward_pips * pip_value * units
            
            # Calculate risk percentage
            if account_balance and account_balance > 0:
                metrics['risk_percent'] = (metrics['risk_amount'] / account_balance) * 100
        
        logger.info(f"📊 Risk metrics: Risk={risk_pips:.1f}pips, Reward={reward_pips:.1f}pips, R:R={metrics['rr_ratio']:.2f if metrics['rr_ratio'] else 'N/A'}")
        return metrics
        
    except Exception as e:
        logger.error(f"Error calculating risk metrics: {e}")
        return metrics

# --- Quarter Curve Zone Position Mapping ---
def map_quarter_curve_zone_position(zone_position, strategy_tag, candlestick_strength=None, breach_direction=None):
    """
    Map Quarter Curve strategy zone positions to Airtable zone options
    """
    
    # Valid Airtable zone position options
    AIRTABLE_ZONES = {
        "Below_Sell_Zone",
        "In_Sell_Zone", 
        "In_Buy_Zone",
        "Above_Buy_Zone",
        "QUARTER_750_CROSS_SELL_VERY_BEARISH",
        "QUARTER_750_CROSS_SELL_BEARISH", 
        "QUARTER_250_CROSS_BUY_VERY_BULLISH",
        "QUARTER_250_CROSS_BUY_BULLISH"
    }
    
    # Check if it's a Quarter Curve strategy
    is_quarter_curve = strategy_tag and "QuarterCurve" in strategy_tag
    
    if is_quarter_curve:
        logger.info(f"🎯 Mapping Quarter Curve zone: {zone_position}, breach: {breach_direction}, strength: {candlestick_strength}")
        
        # Map based on breach direction and candlestick strength
        if breach_direction and candlestick_strength:
            
            # Upper bodyguard breaches (bearish signals - price broke above upper bodyguard)
            if "above_upper_bodyguard" in breach_direction:
                if candlestick_strength in ["strong_bearish"]:
                    return "QUARTER_750_CROSS_SELL_VERY_BEARISH"
                elif candlestick_strength in ["bearish"]:
                    return "QUARTER_750_CROSS_SELL_BEARISH"
                else:
                    return "In_Sell_Zone"
            
            # Lower bodyguard breaches (bullish signals - price broke below lower bodyguard)
            elif "below_lower_bodyguard" in breach_direction:
                if candlestick_strength in ["strong_bullish"]:
                    return "QUARTER_250_CROSS_BUY_VERY_BULLISH"
                elif candlestick_strength in ["bullish"]:
                    return "QUARTER_250_CROSS_BUY_BULLISH"
                else:
                    return "In_Buy_Zone"
        
        # Fallback based on original zone_position if available
        if zone_position:
            zone_lower = zone_position.lower()
            
            if "sell" in zone_lower or "bearish" in zone_lower:
                return "In_Sell_Zone"
            elif "buy" in zone_lower or "bullish" in zone_lower:
                return "In_Buy_Zone"
            elif "above" in zone_lower:
                return "Above_Buy_Zone"
            elif "below" in zone_lower:
                return "Below_Sell_Zone"
        
        # Default for Quarter Curve if no specific mapping found
        logger.info("🎯 Quarter Curve: Using default 'Below_Sell_Zone' zone position")
        return "Below_Sell_Zone"
    
    # For non-Quarter Curve strategies, use original logic
    if zone_position and zone_position in AIRTABLE_ZONES:
        return zone_position
    
    # Original zone position mapping for other strategies
    if zone_position:
        zone_lower = zone_position.lower()
        
        if "sell" in zone_lower and "very" in zone_lower:
            return "QUARTER_750_CROSS_SELL_VERY_BEARISH"
        elif "sell" in zone_lower:
            return "QUARTER_750_CROSS_SELL_BEARISH"
        elif "buy" in zone_lower and "very" in zone_lower:
            return "QUARTER_250_CROSS_BUY_VERY_BULLISH"
        elif "buy" in zone_lower:
            return "QUARTER_250_CROSS_BUY_BULLISH"
        elif "above" in zone_lower:
            return "Above_Buy_Zone"
        elif "below" in zone_lower:
            return "Below_Sell_Zone"
        elif zone_lower in ["in_sell_zone", "sell_zone"]:
            return "In_Sell_Zone"
        elif zone_lower in ["in_buy_zone", "buy_zone"]:
            return "In_Buy_Zone"
    
    # Ultimate fallback
    return "Below_Sell_Zone"

# --- ENHANCED: Airtable Metadata Handling Functions ---
def clean_metadata_for_airtable(metadata_dict):
    """
    Clean metadata dictionary to handle N/A values properly for Airtable
    """
    
    # Define which fields are numbers/percentages vs text in Airtable
    NUMERIC_FIELDS = {
        'momentum_strength',      # Number field (0-1 or percentage)
        'signal_confidence',      # Number field (0-100)
        'momentum_alignment',     # Number field (0-1 or percentage) 
        'distance_to_entry_pips', # Number field (pips)
        'stop_loss_price',        # Number field
        'target_price',           # Number field
        'entry_price',            # Number field
        'risk_amount',            # Number field
        'rr_ratio',               # Number field
        'current_price'           # Currency field (now numeric)
    }
    
    cleaned = {}
    
    for key, value in metadata_dict.items():
        if value is None:
            # None is always acceptable
            cleaned[key] = None
        elif isinstance(value, str) and value.upper() in ['N/A', 'NA', 'NULL', 'NONE', '']:
            # Handle various forms of N/A - convert to None for all fields
            cleaned[key] = None
        elif key == 'distance_to_entry_pips':
            # Ensure distance is a proper number
            try:
                if isinstance(value, str):
                    cleaned[key] = float(value) if value.strip() else 0.0
                else:
                    cleaned[key] = float(value) if value is not None else 0.0
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Could not convert distance '{value}' to float. Using 0.0")
                cleaned[key] = 0.0
        else:
            # Keep the original value
            cleaned[key] = value
    
    return cleaned

def create_airtable_fields_with_enhanced_prices(base_fields, metadata, price_levels, risk_metrics=None):
    """
    Create Airtable fields dictionary with enhanced price tracking and risk metrics
    
    Args:
        base_fields: Base fields dictionary (prices, times, etc.)
        metadata: Metadata dictionary from TradeMetadata or analysis
        price_levels: Price levels from extract_price_levels_from_transaction
        risk_metrics: Optional pre-calculated risk metrics
        
    Returns:
        dict: Complete fields dictionary ready for Airtable
    """
    
    # Clean metadata first
    cleaned_metadata = clean_metadata_for_airtable(metadata)
    
    # Map metadata keys to Airtable field names
    metadata_field_mapping = {
        'setup_name': 'Setup Name',
        'strategy_tag': 'Strategy Tag', 
        'momentum_strength': 'Momentum Strength',
        'momentum_direction': 'Momentum Direction',
        'strategy_bias': 'Strategy Bias',
        'zone_position': 'Zone Position',
        'distance_to_entry_pips': 'Distance to Entry (Pips)',
        'signal_confidence': 'Signal Confidence',
        'momentum_alignment': 'Momentum Alignment'
    }
    
    # Start with base fields
    fields = base_fields.copy()
    
    # Add cleaned metadata fields
    for metadata_key, airtable_field in metadata_field_mapping.items():
        value = cleaned_metadata.get(metadata_key)
        
        # Special handling for zone position - use Quarter Curve mapping
        if metadata_key == 'zone_position':
            mapped_zone = map_quarter_curve_zone_position(
                value, 
                cleaned_metadata.get('strategy_tag'),
                None,  # candlestick_strength - could be added if available
                None   # breach_direction - could be added if available
            )
            fields[airtable_field] = mapped_zone
            logger.info(f"🎯 Zone Position mapped: '{value}' -> '{mapped_zone}'")
        else:
            fields[airtable_field] = value
    
    # ENHANCED: Add price levels
    if price_levels.get('stop_loss_price'):
        fields['Stop Loss'] = price_levels['stop_loss_price']
        logger.info(f"💰 Added Stop Loss: {price_levels['stop_loss_price']}")
    
    if price_levels.get('target_price'):
        fields['Target Price'] = price_levels['target_price']
        logger.info(f"💰 Added Target Price: {price_levels['target_price']}")
    
    if price_levels.get('current_price'):
        # Current Price is now a currency field - send as number
        fields['Current Price'] = float(price_levels['current_price'])
        logger.info(f"💰 Added Current Price: {price_levels['current_price']}")
    
    # ENHANCED: Add risk metrics if available
    if risk_metrics:
        if risk_metrics.get('rr_ratio'):
            fields['R:R Ratio Calculated'] = risk_metrics['rr_ratio']
            logger.info(f"📊 Added R:R Ratio: {risk_metrics['rr_ratio']:.2f}")
        
        if risk_metrics.get('risk_amount'):
            fields['Risk Amount Calculated'] = risk_metrics['risk_amount']
            logger.info(f"📊 Added Risk Amount: {risk_metrics['risk_amount']:.2f}")
        
        if risk_metrics.get('risk_percent'):
            fields['Risk Per Trade % Calculated'] = risk_metrics['risk_percent']
            logger.info(f"📊 Added Risk Percent: {risk_metrics['risk_percent']:.2f}%")
    
    return fields

# --- Enhanced Metadata Parsing ---
def parse_setup_metadata(transaction):
    """
    Original metadata parsing with detailed debugging
    """
    metadata = {
        'setup_name': None,
        'momentum_strength': None,
        'momentum_direction': None,
        'strategy_bias': None,
        'zone_position': None,
        'distance_pips': None,
        'confidence': None,
        'alignment_score': None,
        'strategy_tag': None
    }
    
    try:
        logger.info(f"🔍 DEBUG: Full transaction keys: {list(transaction.keys())}")
        
        # Look for client extensions in multiple places
        client_extensions = None
        
        # Method 1: Direct clientExtensions
        if 'clientExtensions' in transaction:
            client_extensions = transaction['clientExtensions']
            logger.info(f"🔍 Found clientExtensions in transaction: {client_extensions}")
        
        # Method 2: In nested order
        elif 'order' in transaction and 'clientExtensions' in transaction['order']:
            client_extensions = transaction['order']['clientExtensions']
            logger.info(f"🔍 Found clientExtensions in order: {client_extensions}")
        
        # Method 3: In orderCreateTransaction (for limit orders)
        elif 'orderCreateTransaction' in transaction:
            order_create = transaction['orderCreateTransaction']
            if 'clientExtensions' in order_create:
                client_extensions = order_create['clientExtensions']
                logger.info(f"🔍 Found clientExtensions in orderCreateTransaction: {client_extensions}")
        
        # Method 4: In orderFillTransaction (for market orders)
        elif 'orderFillTransaction' in transaction:
            order_fill = transaction['orderFillTransaction']
            if 'clientExtensions' in order_fill:
                client_extensions = order_fill['clientExtensions']
                logger.info(f"🔍 Found clientExtensions in orderFillTransaction: {client_extensions}")
        
        if not client_extensions:
            logger.warning(f"🔍 No clientExtensions found in transaction {transaction.get('id', 'unknown')}")
            return metadata
        
        # Parse setup name from client ID
        if 'id' in client_extensions:
            client_id = client_extensions['id']
            # Convert back from safe format to readable format
            setup_name = client_id.replace('_', ' ').replace('/', '_')
            metadata['setup_name'] = setup_name
            logger.info(f"🔍 Parsed setup name from ID: {setup_name}")
        
        # Parse strategy tag
        if 'tag' in client_extensions:
            metadata['strategy_tag'] = client_extensions['tag']
            logger.info(f"🔍 Parsed strategy tag: {client_extensions['tag']}")
        
        # Parse detailed metadata from comment
        if 'comment' in client_extensions:
            comment = client_extensions['comment']
            logger.info(f"🔍 Parsing comment: {comment}")
            
            # Split by | delimiter and parse key:value pairs
            parts = comment.split('|')
            for part in parts:
                if ':' in part:
                    key, value = part.split(':', 1)
                    logger.info(f"🔍 Parsing {key}:{value}")
                    
                    if key == 'Setup':
                        metadata['setup_name'] = value
                    elif key == 'Momentum':
                        try:
                            metadata['momentum_strength'] = float(value)
                        except ValueError:
                            logger.warning(f"🔍 Could not parse momentum strength: {value}")
                    elif key == 'Direction':
                        metadata['momentum_direction'] = value
                    elif key == 'Bias':
                        metadata['strategy_bias'] = value
                    elif key == 'Zone':
                        metadata['zone_position'] = value
                    elif key == 'DistancePips':
                        try:
                            metadata['distance_pips'] = float(value)
                        except ValueError:
                            logger.warning(f"🔍 Could not parse distance pips: {value}")
                    elif key == 'Confidence':
                        try:
                            metadata['confidence'] = int(value)
                        except ValueError:
                            logger.warning(f"🔍 Could not parse confidence: {value}")
                    elif key == 'Alignment':
                        try:
                            metadata['alignment_score'] = float(value)
                        except ValueError:
                            logger.warning(f"🔍 Could not parse alignment score: {value}")
        
        logger.info(f"🔍 Final parsed metadata: {metadata}")
        return metadata
        
    except Exception as e:
        logger.error(f"🔍 Error parsing setup metadata: {e}")
        return metadata

def enhanced_parse_setup_metadata(transaction):
    """
    Enhanced metadata parsing that combines Oanda clientExtensions with local storage
    """
    metadata = {
        'setup_name': None,
        'momentum_strength': None,
        'momentum_direction': None,
        'strategy_bias': None,
        'zone_position': None,
        'distance_pips': None,
        'confidence': None,
        'alignment_score': None,
        'strategy_tag': None,
        'candlestick_strength': None,
        'breach_direction': None
    }
    
    try:
        # First, try the original clientExtensions parsing
        original_metadata = parse_setup_metadata(transaction)
        
        # If we found clientExtensions data, use it
        if any(original_metadata.values()):
            logger.info("🔍 Found clientExtensions metadata from Oanda")
            return original_metadata
        
        # If no clientExtensions and we have metadata store, try local lookup
        if metadata_store is None:
            logger.warning("🔍 No clientExtensions found and metadata store not available")
            return metadata
        
        logger.info("🔍 No clientExtensions found, checking local metadata store...")
        
        # Method 1: Direct order ID lookup
        order_id = transaction.get('orderID') or transaction.get('id')
        if order_id:
            local_metadata = metadata_store.get_order_metadata(order_id)
            if local_metadata:
                logger.info(f"🔍 Found local metadata for order {order_id}")
                return convert_local_to_metadata_dict(local_metadata)
        
        # Method 2: For fills without order ID, try time-based matching
        if 'instrument' in transaction and 'time' in transaction:
            instrument = transaction['instrument']
            trade_time = transaction['time']
            
            # This method would need to be implemented in metadata store
            # local_metadata = metadata_store.get_trade_metadata_by_instrument_and_time(
            #     instrument, trade_time, tolerance_minutes=10
            # )
            # if local_metadata:
            #     logger.info(f"🔍 Found local metadata for {instrument} by time matching")
            #     return convert_local_to_metadata_dict(local_metadata)
        
        logger.warning(f"🔍 No metadata found for transaction {transaction.get('id', 'unknown')}")
        return metadata
        
    except Exception as e:
        logger.error(f"🔍 Error in enhanced metadata parsing: {e}")
        return metadata

def convert_local_to_metadata_dict(local_metadata):
    """Convert local metadata format to the expected dictionary format"""
    try:
        converted = {
            'setup_name': local_metadata.get('setup_name'),
            'momentum_strength': local_metadata.get('momentum_strength'),
            'momentum_direction': local_metadata.get('momentum_direction'),
            'strategy_bias': local_metadata.get('strategy_bias'),
            'zone_position': local_metadata.get('zone_position'),
            'distance_pips': local_metadata.get('distance_to_entry_pips'),
            'confidence': local_metadata.get('signal_confidence'),
            'alignment_score': local_metadata.get('momentum_alignment'),
            'strategy_tag': local_metadata.get('strategy_tag')
        }
        
        # Extract Quarter Curve specific fields from setup_name
        setup_name = converted.get('setup_name', '')
        if setup_name and 'QCButterMiddle' in setup_name:
            # Parse candlestick strength and breach direction from setup name
            parts = setup_name.split('_')
            if len(parts) >= 5:
                if 'bullish' in parts[-1] or 'bearish' in parts[-1]:
                    converted['candlestick_strength'] = parts[-1]
                if 'strong' in parts[-2]:
                    converted['candlestick_strength'] = f"{parts[-2]}_{parts[-1]}"
        
        return converted
        
    except Exception as e:
        logger.error(f"Error converting local metadata: {e}")
        return {}

def create_fallback_setup_name(transaction):
    """
    Create a fallback setup name when metadata is not available
    """
    try:
        instrument = transaction.get('instrument', 'UNKNOWN').replace('_', '/')
        reason = transaction.get('reason', 'MARKET_ORDER')
        units = int(transaction.get('units', 0))
        direction = 'BUY' if units > 0 else 'SELL'
        
        # Determine order type
        if 'LIMIT' in reason:
            order_type = 'LIMIT'
        else:
            order_type = 'MARKET'
        
        return f"Manual_{instrument}_{order_type}_{direction}"
        
    except Exception as e:
        logger.warning(f"Error creating fallback setup name: {e}")
        return "Unknown_Setup"

# --- Helper Functions ---
def load_last_transaction_id():
    """Load the last processed transaction ID from file"""
    sync_file = os.path.join(current_dir, "last_sync.json")
    try:
        with open(sync_file, "r") as f:
            data = json.load(f)
            return data.get("last_transaction_id", "0")
    except FileNotFoundError:
        logger.info("No last_sync.json found, starting from transaction ID 0")
        return "0"
    except json.JSONDecodeError:
        logger.warning("Corrupted last_sync.json, starting from transaction ID 0")
        return "0"

def save_last_transaction_id(tx_id):
    """Save the last processed transaction ID to file"""
    sync_file = os.path.join(current_dir, "last_sync.json")
    try:
        with open(sync_file, "w") as f:
            json.dump({
                "last_transaction_id": tx_id,
                "last_sync_time": datetime.now().isoformat()
            }, f, indent=2)
        logger.info(f"Saved last transaction ID: {tx_id}")
    except Exception as e:
        logger.error(f"Failed to save transaction ID: {e}")

def test_oanda_connection():
    """Test connection to Oanda API"""
    try:
        client = API(access_token=API_KEY, environment="practice")
        r = AccountSummary(accountID=ACCOUNT_ID)
        client.request(r)
        account_data = r.response.get("account", {})
        balance = account_data.get("balance", "N/A")
        logger.info(f"Oanda connection successful. Account balance: {balance}")
        return True
    except Exception as e:
        logger.error(f"Oanda connection failed: {e}")
        return False

def test_airtable_connection():
    """Test connection to Airtable"""
    try:
        records = table.all(max_records=1)
        logger.info(f"Airtable connection successful. Table has records: {len(records) > 0}")
        return True
    except Exception as e:
        logger.error(f"Airtable connection failed: {e}")
        return False

def calculate_days_between(start_time, end_time):
    """Calculate days between two ISO timestamps"""
    try:
        if not start_time or not end_time:
            return 0
        
        from datetime import datetime
        start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        return (end - start).days
    except:
        return 0

# --- ENHANCED: Trade Processing Functions ---
def enhanced_process_order_fill_with_prices(tx):
    """Enhanced ORDER_FILL processing with comprehensive price tracking"""
    try:
        logger.info(f"💰 Processing ORDER_FILL with enhanced price tracking: {tx.get('id', 'unknown')}")
        
        # Extract price levels first
        price_levels = extract_price_levels_from_transaction(tx)
        
        # Use enhanced metadata parsing
        metadata = enhanced_parse_setup_metadata(tx)
        
        # OPEN TRADE
        if "tradeOpened" in tx:
            trade_id = tx["tradeOpened"]["tradeID"]
            order_id = tx["orderID"]
            
            logger.info(f"💰 Trade opened with prices: {trade_id}, Order: {order_id}")
            
            # Check for existing records
            try:
                existing_order = table.first(formula=f"{{OANDA Order ID}} = '{order_id}'")
            except Exception as e:
                logger.warning(f"Error checking for existing order: {e}")
                existing_order = None
            
            try:
                existing_fill = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
            except Exception as e:
                logger.warning(f"Error checking for existing fill record: {e}")
                existing_fill = None

            # Calculate days pending
            order_time = tx.get("time")
            fill_time = tx.get("time")
            days_pending = 0
            
            if existing_order:
                order_placement_time = existing_order['fields'].get('Order Time', '')
                days_pending = calculate_days_between(order_placement_time, fill_time)

            # Map order type
            order_type_mapping = {
                "ORDER_FILL": "MARKET_ORDER",
                "LIMIT_ORDER": "LIMIT_ORDER", 
                "MARKET_ORDER": "MARKET_ORDER",
                "STOP_ORDER": "STOP_LOSS_ORDER",
            }
            
            raw_order_type = tx.get("reason", "ORDER_FILL")
            mapped_order_type = order_type_mapping.get(raw_order_type, "MARKET_ORDER")

            # Create setup name
            setup_name = metadata.get('setup_name') or create_fallback_setup_name(tx)

            # Base fields for Airtable
            base_fields = {
                "Fill ID": trade_id,
                "OANDA Order ID": order_id,
                "Instrument": tx["instrument"],
                "Order Type": mapped_order_type,
                "Direction": "Long" if int(tx["units"]) > 0 else "Short",
                "Units": abs(int(tx["units"])),
                "Entry Price": float(tx["price"]),
                "Filled Price": float(tx["price"]),
                "Execution Time": tx.get("time"),
                "Order Time": existing_order['fields'].get('Order Time', tx.get("time")) if existing_order else tx.get("time"),
                "Order Status": "Filled",
                "Realized PL": float(tx.get("pl", 0.0)),
                "Account Balance After": float(tx.get("accountBalance", 0.0)),
                "Account Balance Before": float(tx.get("accountBalance", 0.0)) - float(tx.get("pl", 0.0)),
                "Spread Cost": float(tx.get("halfSpreadCost", 0.0)),
                "Reason": tx.get("reason", "ORDER_FILL"),
                "Initial Margin Required": float(tx.get("tradeOpened", {}).get("initialMarginRequired", 0.0)),
                "Financing": float(tx.get("financing", 0.0)),
                "Margin Used": float(tx.get("tradeOpened", {}).get("initialMarginRequired", 0.0)),
                "Trade State": "Open",
                "Days Pending": days_pending,
            }
            
            # Calculate risk metrics
            risk_metrics = None
            if all([price_levels.get('entry_price'), price_levels.get('stop_loss_price'), price_levels.get('target_price')]):
                risk_metrics = calculate_risk_metrics(
                    price_levels['entry_price'],
                    price_levels['stop_loss_price'],
                    price_levels['target_price'],
                    abs(int(tx["units"])),
                    base_fields.get("Account Balance Before")
                )
            
            # Convert metadata for Airtable
            metadata_for_airtable = {
                'setup_name': setup_name,
                'strategy_tag': metadata.get('strategy_tag') or 'PennyCurveMomentum',
                'momentum_strength': metadata.get('momentum_strength'),
                'momentum_direction': metadata.get('momentum_direction'),
                'strategy_bias': metadata.get('strategy_bias'),
                'zone_position': metadata.get('zone_position'),
                'distance_to_entry_pips': metadata.get('distance_pips'),
                'signal_confidence': metadata.get('confidence'),
                'momentum_alignment': metadata.get('alignment_score')
            }
            
            # Create complete fields with enhanced price tracking
            fields = create_airtable_fields_with_enhanced_prices(
                base_fields, 
                metadata_for_airtable,
                price_levels,
                risk_metrics
            )
            
            # Store enhanced metadata locally if available
            if metadata_store:
                enhanced_metadata = EnhancedTradeMetadata(
                    setup_name=setup_name,
                    strategy_tag=metadata.get('strategy_tag', 'PennyCurveMomentum'),
                    stop_loss_price=price_levels.get('stop_loss_price'),
                    target_price=price_levels.get('target_price'),
                    current_price_at_order=price_levels.get('current_price'),
                    entry_price=price_levels.get('entry_price'),
                    momentum_strength=metadata.get('momentum_strength'),
                    momentum_direction=metadata.get('momentum_direction'),
                    strategy_bias=metadata.get('strategy_bias'),
                    zone_position=metadata.get('zone_position'),
                    signal_confidence=metadata.get('confidence'),
                    distance_to_entry_pips=metadata.get('distance_pips'),
                    momentum_alignment=metadata.get('alignment_score')
                )
                
                metadata_store.store_enhanced_metadata(order_id, enhanced_metadata)

            logger.info(f"💰 Creating/updating record with enhanced prices for trade: {trade_id}")
            logger.info(f"   Setup: {setup_name}")
            logger.info(f"   Stop Loss: {fields.get('Stop Loss')}")
            logger.info(f"   Target Price: {fields.get('Target Price')}")
            logger.info(f"   Current Price: {fields.get('Current Price')}")
            
            # Create or update record
            if existing_order and not existing_fill:
                try:
                    table.update(existing_order["id"], fields)
                    logger.info(f"✅ Updated pending order {order_id} with fill and price data")
                except Exception as e:
                    logger.error(f"Failed to update pending order: {e}")
                    return False
            elif not existing_fill:
                try:
                    result = table.create(fields)
                    logger.info(f"✅ Created new record for trade {trade_id} with enhanced prices")
                except Exception as e:
                    logger.error(f"Failed to create record: {e}")
                    return False
            else:
                try:
                    table.update(existing_fill["id"], fields)
                    logger.info(f"✅ Updated existing record for trade {trade_id} with enhanced prices")
                except Exception as e:
                    logger.error(f"Failed to update record: {e}")
                    return False
            
            return True

        # CLOSE TRADE
        elif "tradesClosed" in tx and tx["tradesClosed"]:
            for closed_trade in tx["tradesClosed"]:
                trade_id = closed_trade["tradeID"]
                
                try:
                    existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
                except Exception as e:
                    logger.warning(f"Error finding record for closed trade: {e}")
                    continue

                if not existing:
                    logger.warning(f"No matching open trade found for closed trade {trade_id}")
                    continue

                # Get current price for exit
                instrument = tx.get('instrument')
                current_prices = get_current_price(instrument) if instrument else None
                
                fields = {
                    "Exit Price": float(tx["price"]),
                    "Realized PL": float(closed_trade.get("realizedPL", tx.get("pl", 0.0))),
                    "Account Balance After": float(tx.get("accountBalance", 0.0)),
                    "Reason": "MARKET_ORDER",
                    "Trade State": "Closed",
                    "Financing": float(tx.get("financing", 0.0))
                }
                
                # Add current price at close
                if current_prices:
                    fields["Current Price"] = float(current_prices['mid'])
                    logger.info(f"💰 Added current price at close: {current_prices['mid']}")

                logger.info(f"💰 Updating record for trade close: {trade_id}")
                try:
                    table.update(existing["id"], fields)
                    logger.info(f"✅ Updated record for closed trade {trade_id}")
                except Exception as e:
                    logger.error(f"Failed to update closed trade: {e}")
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error in enhanced_process_order_fill_with_prices: {e}")
        return False

def enhanced_process_limit_order_with_prices(tx):
    """Enhanced LIMIT_ORDER processing with comprehensive price tracking"""
    try:
        order_id = tx.get("id")
        instrument = tx.get("instrument")
        units = int(tx.get("units", 0))
        price = float(tx.get("price", 0))
        order_time = tx.get("time")
        
        logger.info(f"💰 Processing LIMIT_ORDER with enhanced price tracking: {order_id}")
        
        # Extract price levels
        price_levels = extract_price_levels_from_transaction(tx)
        price_levels['entry_price'] = price  # Set entry price for limit orders
        
        # Use enhanced metadata parsing
        metadata = enhanced_parse_setup_metadata(tx)
        
        # Check if record already exists
        try:
            existing = table.first(formula=f"{{OANDA Order ID}} = '{order_id}'")
        except Exception as e:
            logger.warning(f"Error checking for existing order record: {e}")
            existing = None
        
        if existing:
            logger.info(f"Order {order_id} already exists in Airtable")
            return False
        
        # Create setup name
        setup_name = metadata.get('setup_name') or create_fallback_setup_name(tx)
        
        # Create base fields for pending limit order
        base_fields = {
            "OANDA Order ID": order_id,
            "Instrument": instrument,
            "Order Type": "LIMIT_ORDER",
            "Direction": "Long" if units > 0 else "Short",
            "Units": abs(units),
            "Entry Price": price,
            "Order Time": order_time,
            "Order Status": "Pending",
            "Trade State": "Open",
            "Reason": "LIMIT_ORDER",
            "Account Balance After": float(tx.get("accountBalance", 0.0)),
            "Days Pending": 0,
        }
        
        # Calculate risk metrics
        risk_metrics = None
        if all([price_levels.get('entry_price'), price_levels.get('stop_loss_price'), price_levels.get('target_price')]):
            risk_metrics = calculate_risk_metrics(
                price_levels['entry_price'],
                price_levels['stop_loss_price'],
                price_levels['target_price'],
                abs(units),
                base_fields.get("Account Balance After")
            )
        
        # Convert metadata for Airtable
        metadata_for_airtable = {
            'setup_name': setup_name,
            'strategy_tag': metadata.get('strategy_tag') or 'PennyCurveMomentum',
            'momentum_strength': metadata.get('momentum_strength'),
            'momentum_direction': metadata.get('momentum_direction'),
            'strategy_bias': metadata.get('strategy_bias'),
            'zone_position': metadata.get('zone_position'),
            'distance_to_entry_pips': metadata.get('distance_pips'),
            'signal_confidence': metadata.get('confidence'),
            'momentum_alignment': metadata.get('alignment_score')
        }
        
        # Create complete fields with enhanced price tracking
        fields = create_airtable_fields_with_enhanced_prices(
            base_fields, 
            metadata_for_airtable,
            price_levels,
            risk_metrics
        )
        
        # Store enhanced metadata locally if available
        if metadata_store:
            enhanced_metadata = EnhancedTradeMetadata(
                setup_name=setup_name,
                strategy_tag=metadata.get('strategy_tag', 'PennyCurveMomentum'),
                stop_loss_price=price_levels.get('stop_loss_price'),
                target_price=price_levels.get('target_price'),
                current_price_at_order=price_levels.get('current_price'),
                entry_price=price_levels.get('entry_price'),
                momentum_strength=metadata.get('momentum_strength'),
                momentum_direction=metadata.get('momentum_direction'),
                strategy_bias=metadata.get('strategy_bias'),
                zone_position=metadata.get('zone_position'),
                signal_confidence=metadata.get('confidence'),
                distance_to_entry_pips=metadata.get('distance_pips'),
                momentum_alignment=metadata.get('alignment_score')
            )
            
            metadata_store.store_enhanced_metadata(order_id, enhanced_metadata)
        
        logger.info(f"💰 Creating pending order with enhanced prices: {order_id}")
        logger.info(f"   Setup: {setup_name}")
        logger.info(f"   Entry Price: {fields.get('Entry Price')}")
        logger.info(f"   Stop Loss: {fields.get('Stop Loss')}")
        logger.info(f"   Target Price: {fields.get('Target Price')}")
        logger.info(f"   Current Price: {fields.get('Current Price')}")
        
        result = table.create(fields)
        logger.info(f"✅ Created pending order record with enhanced prices: {result['id']}")
        return True
        
    except Exception as e:
        logger.error(f"Error in enhanced_process_limit_order_with_prices: {e}")
        return False

def process_take_profit_order(tx):
    """Process a TAKE_PROFIT_ORDER transaction"""
    try:
        trade_id = tx.get("tradeID")
        if not trade_id:
            logger.warning("No trade ID found in take profit order")
            return False
        
        # Find the existing trade record
        try:
            existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
        except Exception as e:
            logger.warning(f"Error finding record for take profit order: {e}")
            return False
        
        if not existing:
            logger.warning(f"No matching trade found for take profit order on trade {trade_id}")
            return False
        
        # Update with take profit price
        fields = {
            "Target Price": float(tx.get("price", 0.0))
        }
        
        # Add current price
        instrument = tx.get("instrument")
        if instrument:
            current_prices = get_current_price(instrument)
            if current_prices:
                fields["Current Price"] = float(current_prices['mid'])
        
        logger.info(f"💰 TAKE_PROFIT fields: {fields}")
        table.update(existing["id"], fields)
        logger.info(f"✅ Updated trade {trade_id} with take profit: {tx.get('price')}")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_take_profit_order: {e}")
        return False

def process_stop_loss_order(tx):
    """Process a STOP_LOSS_ORDER transaction"""
    try:
        trade_id = tx.get("tradeID")
        if not trade_id:
            logger.warning("No trade ID found in stop loss order")
            return False
        
        # Find the existing trade record
        try:
            existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
        except Exception as e:
            logger.warning(f"Error finding record for stop loss order: {e}")
            return False
        
        if not existing:
            logger.warning(f"No matching trade found for stop loss order on trade {trade_id}")
            return False
        
        # Update with stop loss price
        fields = {
            "Stop Loss": float(tx.get("price", 0.0))
        }
        
        # Add current price
        instrument = tx.get("instrument")
        if instrument:
            current_prices = get_current_price(instrument)
            if current_prices:
                fields["Current Price"] = float(current_prices['mid'])
        
        logger.info(f"💰 STOP_LOSS fields: {fields}")
        table.update(existing["id"], fields)
        logger.info(f"✅ Updated trade {trade_id} with stop loss: {tx.get('price')}")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_stop_loss_order: {e}")
        return False

def process_order_cancel(tx):
    """Process an ORDER_CANCEL transaction"""
    try:
        # Try different field names for cancelled order ID
        cancelled_order_id = tx.get("cancelledOrderID") or tx.get("orderID") or tx.get("id")
        
        if not cancelled_order_id:
            logger.warning(f"No cancelled order ID found in cancel transaction: {list(tx.keys())}")
            return False
        
        # Find the existing order record
        try:
            existing = table.first(formula=f"{{OANDA Order ID}} = '{cancelled_order_id}'")
        except Exception as e:
            logger.warning(f"Error finding record for cancelled order: {e}")
            return False
        
        if not existing:
            logger.warning(f"No matching order found for cancelled order {cancelled_order_id}")
            return False
        
        # Calculate days pending
        order_time = existing['fields'].get('Order Time', '')
        cancel_time = tx.get('time', '')
        days_pending = calculate_days_between(order_time, cancel_time)
        
        # Update with cancellation info
        fields = {
            "Order Status": "Cancelled",
            "Trade State": "Closed",
            "Reason": tx.get("reason", "CANCELLED"),
            "Days Pending": days_pending,
        }
        
        # Add current price at cancellation
        instrument = existing['fields'].get('Instrument')
        if instrument:
            # Convert Airtable format back to Oanda format
            oanda_instrument = instrument.replace('/', '_')
            current_prices = get_current_price(oanda_instrument)
            if current_prices:
                fields["Current Price"] = float(current_prices['mid'])
        
        table.update(existing["id"], fields)
        logger.info(f"✅ Updated order {cancelled_order_id} status to Cancelled (pending {days_pending} days)")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_order_cancel: {e}")
        return False

# --- Enhanced Sync Functions ---
def enhanced_sync_new_fills():
    """Enhanced sync with comprehensive price tracking and Quarter Curve zone mapping"""
    logger.info("💰 Starting enhanced sync with comprehensive price tracking...")
    
    if not test_oanda_connection():
        return False
    
    client = API(access_token=API_KEY, environment="practice")
    last_id = load_last_transaction_id()
    
    logger.info(f"Looking for transactions after ID: {last_id}")

    try:
        from_id = str(int(last_id) + 1)
        r = TransactionIDRange(
            accountID=ACCOUNT_ID, 
            params={"from": from_id, "to": "99999999"}
        )
        client.request(r)
        
        transactions = r.response.get("transactions", [])
        logger.info(f"Retrieved {len(transactions)} transactions")
        
        if not transactions:
            logger.info("No new transactions to sync.")
            return True
            
    except V20Error as e:
        if "INVALID_RANGE" in str(e) or "Invalid value" in str(e):
            logger.info("No new transactions to sync (invalid range).")
            return True
        else:
            logger.error(f"V20Error: {e}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error getting transactions: {e}")
        return False

    # Process each transaction with enhanced methods
    fills_processed = 0
    orders_processed = 0
    
    for tx in transactions:
        tx_type = tx.get("type")
        tx_id = tx.get("id")
        logger.info(f"Processing transaction {tx_id}: {tx_type}")
        
        if tx_type == "ORDER_FILL":
            try:
                if enhanced_process_order_fill_with_prices(tx):
                    fills_processed += 1
            except Exception as e:
                logger.error(f"Error processing fill {tx.get('id')}: {e}")
                continue
        elif tx_type == "LIMIT_ORDER":
            try:
                if enhanced_process_limit_order_with_prices(tx):
                    orders_processed += 1
            except Exception as e:
                logger.error(f"Error processing limit order {tx.get('id')}: {e}")
                continue
        elif tx_type == "ORDER_CANCEL":
            try:
                process_order_cancel(tx)
            except Exception as e:
                logger.error(f"Error processing order cancel {tx.get('id')}: {e}")
                continue
        elif tx_type == "TAKE_PROFIT_ORDER":
            try:
                process_take_profit_order(tx)
            except Exception as e:
                logger.error(f"Error processing take profit order {tx.get('id')}: {e}")
                continue
        elif tx_type == "STOP_LOSS_ORDER":
            try:
                process_stop_loss_order(tx)
            except Exception as e:
                logger.error(f"Error processing stop loss order {tx.get('id')}: {e}")
                continue

    # Save the latest transaction ID
    latest_id = r.response.get("lastTransactionID", last_id)
    save_last_transaction_id(latest_id)
    
    # Clean up old metadata periodically
    if metadata_store:
        try:
            metadata_store.cleanup_old_metadata()
        except AttributeError:
            pass  # cleanup_old_metadata might not exist in all versions
    
    logger.info(f"💰 Enhanced sync completed with comprehensive price tracking. Processed {fills_processed} fills and {orders_processed} orders. Latest transaction ID: {latest_id}")
    return True

def sync_open_trades():
    """Update open trades with current P/L, margin info, and current prices"""
    logger.info("💰 Starting sync of open trades with current prices...")
    
    if not test_oanda_connection():
        return False
    
    try:
        client = API(access_token=API_KEY, environment="practice")
        r = OpenTrades(accountID=ACCOUNT_ID)
        client.request(r)
        open_trades = r.response.get("trades", [])
        logger.info(f"Retrieved {len(open_trades)} open trades")

        if not open_trades:
            logger.info("No open trades to sync")
            return True

        updated_count = 0
        for trade in open_trades:
            try:
                trade_id = trade["id"]
                
                # Find existing record
                existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
                if not existing:
                    logger.warning(f"No Airtable record found for open trade {trade_id}")
                    continue

                # Get current price for the instrument
                instrument = trade.get("instrument")
                current_prices = get_current_price(instrument) if instrument else None

                # Update fields
                fields = {
                    "Trade State": "Open",
                    "Unrealized PL": float(trade.get("unrealizedPL", 0.0)),
                    "Initial Margin Required": float(trade.get("initialMarginRequired", 0.0)),
                    "Margin Used": float(trade.get("marginUsed", 0.0)),
                    "Financing": float(trade.get("financing", 0.0)),
                }

                # Add current price
                if current_prices:
                    fields["Current Price"] = float(current_prices['mid'])
                    logger.info(f"💰 Updated current price for {instrument}: {current_prices['mid']}")

                # Add stop loss and take profit if present
                if "takeProfitOrder" in trade:
                    fields["Target Price"] = float(trade["takeProfitOrder"].get("price", 0.0))
                if "stopLossOrder" in trade:
                    fields["Stop Loss"] = float(trade["stopLossOrder"].get("price", 0.0))

                logger.info(f"💰 OPEN_TRADES fields for {trade_id}: {fields}")
                table.update(existing["id"], fields)
                updated_count += 1
                logger.info(f"✅ Updated open trade {trade_id}")
                
            except Exception as e:
                logger.error(f"Error updating trade {trade.get('id', 'unknown')}: {e}")
                continue

        logger.info(f"💰 Updated {updated_count} open trades with current prices")
        return True
        
    except Exception as e:
        logger.error(f"Error in sync_open_trades: {e}")
        return False

# --- Enhanced Main Function ---
def enhanced_main():
    """Enhanced main execution function with comprehensive price tracking"""
    logger.info("💰 Starting Enhanced Oanda to Airtable sync with comprehensive price tracking...")
    
    # Test connections first
    logger.info("Testing connections...")
    if not test_airtable_connection():
        logger.error("Cannot proceed without Airtable connection")
        return False
    
    # Show metadata store status
    if metadata_store:
        try:
            stats = metadata_store.get_metadata_stats()
            logger.info(f"📊 Enhanced metadata store loaded: {stats.get('total_entries', 0)} entries")
            if stats.get('instruments'):
                logger.info(f"   Instruments: {stats['instruments']}")
        except AttributeError:
            logger.info(f"📊 Enhanced metadata store loaded: {len(metadata_store._metadata_cache)} entries")
    else:
        logger.warning("⚠️ Enhanced metadata store not available - using original parsing only")
    
    # Run enhanced syncs
    success = True
    
    try:
        # Use enhanced sync method with comprehensive price tracking
        if not enhanced_sync_new_fills():
            success = False
            logger.error("Failed to sync new fills")
        
        # Enhanced open trades sync with current prices
        if not sync_open_trades():
            success = False
            logger.error("Failed to sync open trades")
            
    except Exception as e:
        logger.error(f"Unexpected error in enhanced main: {e}")
        success = False
    
    if success:
        logger.info("✅ Enhanced sync with comprehensive price tracking completed successfully!")
        # Show final metadata store stats
        if metadata_store:
            try:
                final_stats = metadata_store.get_metadata_stats()
                logger.info(f"📊 Final enhanced metadata store: {final_stats.get('total_entries', 0)} entries")
            except AttributeError:
                logger.info(f"📊 Final enhanced metadata store: {len(metadata_store._metadata_cache)} entries")
    else:
        logger.error("❌ Enhanced sync completed with errors")
    
    return success

# --- ADDITIONAL ENHANCED FEATURES ---

def update_existing_records_with_prices():
    """
    Backfill existing records in Airtable with Stop Loss, Target Price, and Current Price
    """
    logger.info("💰 Starting backfill of existing records with price data...")
    
    try:
        # Get all records that might be missing price data
        records = table.all(
            formula="AND({Trade State} = 'Open', OR({Stop Loss} = BLANK(), {Target Price} = BLANK(), {Current Price} = BLANK()))"
        )
        
        logger.info(f"Found {len(records)} records potentially missing price data")
        
        updated_count = 0
        for record in records:
            try:
                fields = record['fields']
                order_id = fields.get('OANDA Order ID')
                fill_id = fields.get('Fill ID')
                instrument = fields.get('Instrument')
                
                if not instrument:
                    continue
                
                # Convert instrument format for Oanda API
                oanda_instrument = instrument.replace('/', '_')
                
                # Get current price
                current_prices = get_current_price(oanda_instrument)
                update_fields = {}
                
                if current_prices and not fields.get('Current Price'):
                    update_fields['Current Price'] = float(current_prices['mid'])
                    logger.info(f"💰 Adding current price to {order_id or fill_id}: {current_prices['mid']}")
                
                # Try to get price levels from local metadata if available
                if metadata_store and order_id:
                    try:
                        local_metadata = metadata_store.get_order_metadata(order_id)
                        if local_metadata:
                            if not fields.get('Stop Loss') and local_metadata.get('stop_loss_price'):
                                update_fields['Stop Loss'] = local_metadata['stop_loss_price']
                                logger.info(f"💰 Adding stop loss from metadata: {local_metadata['stop_loss_price']}")
                            
                            if not fields.get('Target Price') and local_metadata.get('target_price'):
                                update_fields['Target Price'] = local_metadata['target_price']
                                logger.info(f"💰 Adding target price from metadata: {local_metadata['target_price']}")
                    except:
                        pass  # Continue if metadata lookup fails
                
                # Update record if we have new fields
                if update_fields:
                    table.update(record['id'], update_fields)
                    updated_count += 1
                    logger.info(f"✅ Updated record {order_id or fill_id} with price data")
                
            except Exception as e:
                logger.error(f"Error updating record {record.get('id')}: {e}")
                continue
        
        logger.info(f"💰 Backfill completed. Updated {updated_count} records with price data")
        return True
        
    except Exception as e:
        logger.error(f"Error in update_existing_records_with_prices: {e}")
        return False

def validate_price_data_integrity():
    """
    Validate that all records have complete price data and calculate missing metrics
    """
    logger.info("📊 Starting price data integrity validation...")
    
    try:
        # Get all open trades
        records = table.all(formula="{Trade State} = 'Open'")
        
        missing_stop_loss = 0
        missing_target = 0
        missing_current_price = 0
        missing_rr_ratio = 0
        
        for record in records:
            fields = record['fields']
            
            # Check for missing price fields
            if not fields.get('Stop Loss'):
                missing_stop_loss += 1
            if not fields.get('Target Price'):
                missing_target += 1
            if not fields.get('Current Price'):
                missing_current_price += 1
            if not fields.get('R:R Ratio Calculated'):
                missing_rr_ratio += 1
                
                # Try to calculate R:R ratio if we have all prices
                entry_price = fields.get('Entry Price')
                stop_loss = fields.get('Stop Loss')
                target_price = fields.get('Target Price')
                
                if all([entry_price, stop_loss, target_price]):
                    try:
                        direction = fields.get('Direction', 'Long')
                        is_long = direction == 'Long'
                        
                        if is_long:
                            risk_pips = abs(entry_price - stop_loss) * 10000
                            reward_pips = abs(target_price - entry_price) * 10000
                        else:
                            risk_pips = abs(stop_loss - entry_price) * 10000
                            reward_pips = abs(entry_price - target_price) * 10000
                        
                        if risk_pips > 0:
                            rr_ratio = reward_pips / risk_pips
                            table.update(record['id'], {'R:R Ratio Calculated': rr_ratio})
                            logger.info(f"📊 Calculated R:R ratio for {fields.get('OANDA Order ID', fields.get('Fill ID'))}: {rr_ratio:.2f}")
                    except Exception as e:
                        logger.error(f"Error calculating R:R ratio: {e}")
        
        # Log validation results
        logger.info(f"📊 Price Data Integrity Report:")
        logger.info(f"   Total open trades: {len(records)}")
        logger.info(f"   Missing Stop Loss: {missing_stop_loss}")
        logger.info(f"   Missing Target Price: {missing_target}")
        logger.info(f"   Missing Current Price: {missing_current_price}")
        logger.info(f"   Missing R:R Ratio: {missing_rr_ratio}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error in validate_price_data_integrity: {e}")
        return False

def sync_price_updates_for_open_trades():
    """
    Continuously update current prices for open trades
    """
    logger.info("💰 Syncing current price updates for open trades...")
    
    try:
        # Get all open trades
        records = table.all(formula="{Trade State} = 'Open'")
        
        updated_count = 0
        for record in records:
            try:
                fields = record['fields']
                instrument = fields.get('Instrument')
                
                if not instrument:
                    continue
                
                # Convert instrument format for Oanda API
                oanda_instrument = instrument.replace('/', '_')
                
                # Get current price
                current_prices = get_current_price(oanda_instrument)
                if current_prices:
                    update_fields = {
                        'Current Price': float(current_prices['mid'])
                    }
                    
                    table.update(record['id'], update_fields)
                    updated_count += 1
                    
                    logger.info(f"💰 Updated current price for {fields.get('OANDA Order ID', fields.get('Fill ID'))}: {current_prices['mid']}")
                
            except Exception as e:
                logger.error(f"Error updating current price for record {record.get('id')}: {e}")
                continue
        
        logger.info(f"💰 Updated current prices for {updated_count} open trades")
        return True
        
    except Exception as e:
        logger.error(f"Error in sync_price_updates_for_open_trades: {e}")
        return False

def export_enhanced_trading_report():
    """
    Export enhanced trading report with all price data and risk metrics
    """
    logger.info("📊 Generating enhanced trading report...")
    
    try:
        import csv
        from datetime import datetime
        
        # Get all records
        records = table.all()
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"enhanced_trading_report_{timestamp}.csv"
        
        # Enhanced headers including all price and risk fields
        headers = [
            'Order_ID', 'Fill_ID', 'Instrument', 'Direction', 'Order_Type',
            'Setup_Name', 'Strategy_Tag', 'Entry_Price', 'Stop_Loss', 'Target_Price',
            'Current_Price', 'Exit_Price', 'Units', 'Risk_Amount_Calculated',
            'RR_Ratio_Calculated', 'Risk_Per_Trade_Percent', 'Realized_PL',
            'Unrealized_PL', 'Trade_State', 'Order_Status', 'Momentum_Strength',
            'Signal_Confidence', 'Zone_Position', 'Order_Time', 'Execution_Time',
            'Days_Held', 'Days_Pending', 'Account_Balance_After'
        ]
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            
            for record in records:
                fields = record['fields']
                row = [
                    fields.get('OANDA Order ID', ''),
                    fields.get('Fill ID', ''),
                    fields.get('Instrument', ''),
                    fields.get('Direction', ''),
                    fields.get('Order Type', ''),
                    fields.get('Setup Name', ''),
                    fields.get('Strategy Tag', ''),
                    fields.get('Entry Price', ''),
                    fields.get('Stop Loss', ''),
                    fields.get('Target Price', ''),
                    fields.get('Current Price', ''),
                    fields.get('Exit Price', ''),
                    fields.get('Units', ''),
                    fields.get('Risk Amount Calculated', ''),
                    fields.get('R:R Ratio Calculated', ''),
                    fields.get('Risk Per Trade % Calculated', ''),
                    fields.get('Realized PL', ''),
                    fields.get('Unrealized PL', ''),
                    fields.get('Trade State', ''),
                    fields.get('Order Status', ''),
                    fields.get('Momentum Strength', ''),
                    fields.get('Signal Confidence', ''),
                    fields.get('Zone Position', ''),
                    fields.get('Order Time', ''),
                    fields.get('Execution Time', ''),
                    fields.get('Days Held Calculated', ''),
                    fields.get('Days Pending', ''),
                    fields.get('Account Balance After', '')
                ]
                writer.writerow(row)
        
        logger.info(f"📊 Enhanced trading report exported to {filename}")
        return filename
        
    except Exception as e:
        logger.error(f"Error exporting enhanced trading report: {e}")
        return None

if __name__ == "__main__":
    import sys
    
    # Check command line arguments for specific operations
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "backfill":
            logger.info("💰 Running backfill operation...")
            update_existing_records_with_prices()
        elif command == "validate":
            logger.info("📊 Running validation operation...")
            validate_price_data_integrity()
        elif command == "prices":
            logger.info("💰 Running price update operation...")
            sync_price_updates_for_open_trades()
        elif command == "report":
            logger.info("📊 Running report generation...")
            export_enhanced_trading_report()
        elif command == "full":
            logger.info("💰 Running full enhanced sync...")
            enhanced_main()
            update_existing_records_with_prices()
            validate_price_data_integrity()
        else:
            print("Available commands:")
            print("  python sync_all.py backfill  - Backfill existing records with price data")
            print("  python sync_all.py validate  - Validate price data integrity")
            print("  python sync_all.py prices    - Update current prices for open trades")
            print("  python sync_all.py report    - Generate enhanced trading report")
            print("  python sync_all.py full      - Run full sync with all enhancements")
            print("  python sync_all.py           - Run standard enhanced sync")
    else:
        # Use enhanced main with comprehensive price tracking
        enhanced_main()