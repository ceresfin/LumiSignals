"""
Trade Logger Integration - Wrapper to integrate enhanced logging with existing strategies
Ensures all trades are properly logged regardless of which strategy is used
"""

import logging
from typing import Dict, Optional, Any
from datetime import datetime

# Import the enhanced trade logger
from enhanced_trade_logger import get_trade_logger

# Import metadata storage for backward compatibility
from metadata_storage import TradeMetadataStore, TradeMetadata

logger = logging.getLogger(__name__)


class TradeLoggerWrapper:
    """
    Wrapper class that intercepts trade operations to ensure comprehensive logging
    Works with existing strategy implementations
    """
    
    def __init__(self, oanda_api):
        """Initialize the trade logger wrapper"""
        self.oanda_api = oanda_api
        self.trade_logger = get_trade_logger()
        self.metadata_store = TradeMetadataStore()  # Keep for backward compatibility
        
        logger.info("Trade Logger Wrapper initialized")
    
    def log_and_execute_order(self, order_request: Dict, metadata: Dict = None, 
                            strategy_context: Dict = None) -> Dict:
        """
        Log order details comprehensively before executing
        This method should be called instead of direct oanda_api.place_order
        """
        try:
            # Extract order data
            order_data = {
                'instrument': order_request.get('instrument'),
                'order_type': order_request.get('type', 'MARKET'),
                'direction': 'BUY' if float(order_request.get('units', 0)) > 0 else 'SELL',
                'units': abs(int(float(order_request.get('units', 0)))),
                'entry_price': float(order_request.get('price', 0)),
                'order_time': datetime.now().isoformat()
            }
            
            # Extract stop loss and take profit
            if 'stopLossOnFill' in order_request:
                order_data['stop_loss'] = float(order_request['stopLossOnFill'].get('price', 0))
            if 'takeProfitOnFill' in order_request:
                order_data['take_profit'] = float(order_request['takeProfitOnFill'].get('price', 0))
            
            # Get current market price
            try:
                current_price = self._get_current_price(order_data['instrument'])
                order_data['current_price'] = current_price
            except:
                pass
            
            # Ensure metadata has all required fields
            if metadata is None:
                metadata = {}
            
            # Extract from clientExtensions if available
            client_ext = order_request.get('clientExtensions', {})
            if 'id' in client_ext and not metadata.get('setup_name'):
                metadata['setup_name'] = client_ext['id'].replace('_', ' ')
            if 'tag' in client_ext and not metadata.get('strategy_tag'):
                metadata['strategy_tag'] = client_ext['tag']
            
            # Parse comment for additional metadata
            if 'comment' in client_ext:
                self._parse_comment_metadata(client_ext['comment'], metadata)
            
            # Ensure strategy context
            if strategy_context is None:
                strategy_context = self._get_default_strategy_context()
            
            # Calculate risk metrics
            if all([order_data.get('entry_price'), order_data.get('stop_loss'), order_data.get('units')]):
                risk_metrics = self._calculate_risk_metrics(order_data)
                order_data.update(risk_metrics)
            
            # Log the order BEFORE execution
            log_key = self.trade_logger.log_order_placement(
                order_data, metadata, strategy_context
            )
            
            # Execute the order
            result = self.oanda_api.place_order(order_request)
            
            # Update log with actual order ID if successful
            if result and 'orderCreateTransaction' in result:
                actual_order_id = result['orderCreateTransaction'].get('id')
                if actual_order_id and log_key:
                    # Update the log entry with actual order ID
                    for key, log in self.trade_logger.comprehensive_log.items():
                        if key == log_key:
                            log.order_id = actual_order_id
                            self.trade_logger._save_comprehensive_log()
                            break
                
                # Also store in metadata store for backward compatibility
                if metadata:
                    try:
                        # Convert to TradeMetadata object
                        trade_metadata = TradeMetadata(
                            setup_name=metadata.get('setup_name', ''),
                            strategy_tag=metadata.get('strategy_tag', ''),
                            momentum_strength=metadata.get('momentum_strength'),
                            momentum_direction=metadata.get('momentum_direction'),
                            strategy_bias=metadata.get('strategy_bias'),
                            zone_position=metadata.get('zone_position'),
                            signal_confidence=metadata.get('signal_confidence', 0),
                            momentum_strength_str=metadata.get('momentum_strength_str'),
                            momentum_direction_str=metadata.get('momentum_direction_str'),
                            strategy_bias_str=metadata.get('strategy_bias_str')
                        )
                        self.metadata_store.store_order_metadata(actual_order_id, trade_metadata)
                    except Exception as e:
                        logger.warning(f"Could not store in metadata store: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in log_and_execute_order: {e}")
            # Still try to execute the order even if logging fails
            return self.oanda_api.place_order(order_request)
    
    def _parse_comment_metadata(self, comment: str, metadata: Dict):
        """Parse metadata from order comment"""
        try:
            parts = comment.split('|')
            for part in parts:
                if ':' in part:
                    key, value = part.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == 'Setup' and not metadata.get('setup_name'):
                        metadata['setup_name'] = value
                    elif key == 'Momentum':
                        try:
                            metadata['momentum_strength'] = float(value)
                        except:
                            pass
                    elif key == 'Direction':
                        metadata['momentum_direction'] = value
                    elif key == 'Bias':
                        metadata['strategy_bias'] = value
                    elif key == 'Zone':
                        metadata['zone_position'] = value
                    elif key == 'Confidence':
                        try:
                            metadata['signal_confidence'] = int(value)
                        except:
                            pass
        except Exception as e:
            logger.debug(f"Error parsing comment metadata: {e}")
    
    def _get_current_price(self, instrument: str) -> Optional[float]:
        """Get current market price"""
        try:
            prices = self.oanda_api.get_current_prices([instrument])
            if prices and 'prices' in prices:
                price_data = prices['prices'][0]
                if 'closeoutBid' in price_data and 'closeoutAsk' in price_data:
                    bid = float(price_data['closeoutBid'])
                    ask = float(price_data['closeoutAsk'])
                    return (bid + ask) / 2
        except:
            pass
        return None
    
    def _get_default_strategy_context(self) -> Dict:
        """Get default strategy context when not provided"""
        from datetime import datetime
        import pytz
        
        try:
            # Get current ET time
            et_tz = pytz.timezone('US/Eastern')
            current_et = datetime.now(et_tz)
            
            # Determine session
            hour = current_et.hour
            if 3 <= hour < 12:
                session = "London"
                if 8 <= hour < 12:
                    overlap = "London-NY"
                else:
                    overlap = None
            elif 8 <= hour < 17:
                session = "New York"
                overlap = "London-NY" if hour < 12 else None
            elif 19 <= hour or hour < 4:
                session = "Tokyo"
                overlap = None
            else:
                session = "Low Liquidity"
                overlap = None
            
            return {
                'trading_session': session,
                'session_overlap': overlap,
                'liquidity_level': 'High' if overlap else 'Medium',
                'market_time_et': current_et.strftime('%Y-%m-%d %H:%M:%S ET')
            }
        except:
            return {
                'trading_session': 'Unknown',
                'market_time_et': datetime.now().isoformat()
            }
    
    def _calculate_risk_metrics(self, order_data: Dict) -> Dict:
        """Calculate risk metrics for the order"""
        try:
            entry = order_data['entry_price']
            stop_loss = order_data['stop_loss']
            units = order_data['units']
            
            # Calculate risk in pips
            pip_risk = abs(entry - stop_loss)
            
            # Estimate risk amount (simplified - would need pip values for accuracy)
            if 'JPY' in order_data['instrument']:
                pip_value = 0.01
            else:
                pip_value = 0.0001
            
            risk_pips = pip_risk / pip_value
            
            # Calculate R:R ratio if take profit available
            rr_ratio = None
            if order_data.get('take_profit'):
                profit_pips = abs(order_data['take_profit'] - entry) / pip_value
                if risk_pips > 0:
                    rr_ratio = profit_pips / risk_pips
            
            return {
                'risk_amount_usd': None,  # Would need account info for accurate calculation
                'risk_percentage': None,
                'rr_ratio': rr_ratio
            }
        except:
            return {}
    
    def update_order_status(self, order_id: str, status: str, details: Dict = None):
        """Update order status in comprehensive log"""
        try:
            if status == 'FILLED' and details:
                self.trade_logger.update_order_filled(order_id, details)
            elif status == 'CANCELLED':
                reason = details.get('reason') if details else None
                self.trade_logger.update_order_cancelled(order_id, reason)
        except Exception as e:
            logger.error(f"Error updating order status: {e}")


# Factory function to create wrapped OANDA API
def create_logged_oanda_api(api_key: str, account_id: str):
    """
    Create an OANDA API instance with comprehensive trade logging
    
    Usage:
        from trade_logger_integration import create_logged_oanda_api
        api = create_logged_oanda_api(API_KEY, ACCOUNT_ID)
        
        # Use wrapper method for orders
        result = api.wrapper.log_and_execute_order(order_request, metadata, context)
    """
    from oanda_api import OandaAPI
    
    # Create base API
    oanda_api = OandaAPI(api_key, account_id)
    
    # Create wrapper
    wrapper = TradeLoggerWrapper(oanda_api)
    
    # Attach wrapper to API instance for easy access
    oanda_api.wrapper = wrapper
    
    return oanda_api