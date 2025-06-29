"""
Enhanced Sync All - Comprehensive trade data synchronization with Airtable
Fixes metadata classification issues and ensures all trades are properly logged
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

# Import configurations
from config.oanda_config import API_KEY, ACCOUNT_ID
from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME

# Import enhanced trade logger
from enhanced_trade_logger import get_trade_logger, ComprehensiveTradeLog

# Import existing modules
from oandapyV20 import API
from oandapyV20.endpoints.transactions import TransactionIDRange
from oandapyV20.endpoints.trades import OpenTrades
from oandapyV20.endpoints.pricing import PricingInfo
from pyairtable import Api

# Logging setup
logger = logging.getLogger(__name__)


class EnhancedTradeSync:
    """Enhanced synchronization between trade logs and Airtable"""
    
    def __init__(self):
        """Initialize the enhanced sync system"""
        # Get trade logger instance
        self.trade_logger = get_trade_logger()
        
        # Airtable connection
        self.airtable_api = Api(AIRTABLE_API_TOKEN)
        self.table = self.airtable_api.table(BASE_ID, TABLE_NAME)
        
        # Oanda connection
        self.oanda_client = API(access_token=API_KEY, environment="practice")
        
        # Field mapping corrections for Airtable
        self.momentum_direction_mapping = {
            'strong_bullish': 'Strong Bullish',
            'bullish': 'Weak Bullish',
            'neutral': 'Neutral',
            'bearish': 'Weak Bearish',
            'strong_bearish': 'Strong Bearish',
            'very_bullish': 'Strong Bullish',
            'very_bearish': 'Strong Bearish'
        }
        
        self.strategy_bias_mapping = {
            'BUY': 'BUY',
            'SELL': 'SELL',
            'BULLISH': 'BUY',
            'BEARISH': 'SELL',
            'NEUTRAL': 'NEUTRAL'
        }
        
        logger.info("Enhanced Trade Sync initialized")
    
    def map_momentum_direction(self, direction: str) -> str:
        """Map momentum direction to Airtable select options"""
        if not direction:
            return 'Neutral'
        
        direction_lower = str(direction).lower().replace(' ', '_')
        return self.momentum_direction_mapping.get(direction_lower, 'Neutral')
    
    def map_strategy_bias(self, bias: str) -> str:
        """Map strategy bias to Airtable select options"""
        if not bias:
            return 'NEUTRAL'
        
        bias_upper = str(bias).upper()
        return self.strategy_bias_mapping.get(bias_upper, 'NEUTRAL')
    
    def sync_comprehensive_logs(self) -> Dict[str, int]:
        """Sync all unsynced comprehensive trade logs to Airtable"""
        logger.info("Starting comprehensive log sync...")
        
        # Get unsynced logs
        unsynced_logs = self.trade_logger.get_unsyced_logs()
        logger.info(f"Found {len(unsynced_logs)} unsynced trade logs")
        
        results = {
            'synced': 0,
            'errors': 0,
            'skipped': 0
        }
        
        synced_keys = []
        
        for log in unsynced_logs:
            try:
                # Check if record already exists
                existing = self._find_existing_record(log)
                
                if existing:
                    # Update existing record
                    success = self._update_airtable_record(existing, log)
                    if success:
                        results['synced'] += 1
                        synced_keys.append(f"{log.instrument}_{log.order_id}")
                    else:
                        results['errors'] += 1
                else:
                    # Create new record
                    success = self._create_airtable_record(log)
                    if success:
                        results['synced'] += 1
                        synced_keys.append(f"{log.instrument}_{log.order_id}")
                    else:
                        results['errors'] += 1
                        
            except Exception as e:
                logger.error(f"Error syncing log {log.order_id}: {e}")
                results['errors'] += 1
        
        # Mark successfully synced logs
        if synced_keys:
            self.trade_logger.mark_as_synced(synced_keys)
            logger.info(f"Marked {len(synced_keys)} logs as synced")
        
        logger.info(f"Sync complete: {results}")
        return results
    
    def _find_existing_record(self, log: ComprehensiveTradeLog) -> Optional[Dict]:
        """Find existing Airtable record for a trade log"""
        try:
            # First try by order ID
            formula = f"{{OANDA Order ID}} = '{log.order_id}'"
            records = self.table.all(formula=formula)
            if records:
                return records[0]
            
            # Then try by trade ID if available
            if log.trade_id:
                formula = f"{{Fill ID}} = '{log.trade_id}'"
                records = self.table.all(formula=formula)
                if records:
                    return records[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding existing record: {e}")
            return None
    
    def _prepare_airtable_fields(self, log: ComprehensiveTradeLog) -> Dict:
        """Prepare fields for Airtable with proper mapping"""
        # Get base fields from log
        fields = log.to_airtable_record()
        
        # Apply mapping corrections
        if 'Momentum Direction' in fields:
            fields['Momentum Direction'] = self.map_momentum_direction(
                log.momentum_direction or log.momentum_direction_str
            )
        
        if 'Strategy Bias' in fields:
            fields['Strategy Bias'] = self.map_strategy_bias(
                log.strategy_bias or log.strategy_bias_str
            )
        
        # Ensure numeric fields are properly formatted
        numeric_fields = [
            'Momentum Strength', 'Signal Confidence', 'Momentum Alignment',
            'Distance to Entry (Pips)', 'Stop Loss', 'Target Price',
            'Entry Price', 'Current Price', 'Risk Amount (USD)',
            'Risk Percentage', 'R:R Ratio Calculated'
        ]
        
        for field in numeric_fields:
            if field in fields and fields[field] is not None:
                try:
                    # Convert to float and handle None/empty values
                    val = fields[field]
                    if isinstance(val, str) and val.upper() in ['N/A', 'NA', 'NULL', '']:
                        fields[field] = None
                    else:
                        fields[field] = float(val) if val is not None else None
                except (ValueError, TypeError):
                    fields[field] = None
        
        # Remove None values for cleaner records
        fields = {k: v for k, v in fields.items() if v is not None}
        
        return fields
    
    def _create_airtable_record(self, log: ComprehensiveTradeLog) -> bool:
        """Create new Airtable record from trade log"""
        try:
            fields = self._prepare_airtable_fields(log)
            
            logger.info(f"Creating Airtable record for {log.order_id}")
            logger.debug(f"Fields: {json.dumps(fields, indent=2)}")
            
            result = self.table.create(fields)
            
            logger.info(f"✅ Created record for {log.setup_name} - {log.order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating Airtable record: {e}")
            return False
    
    def _update_airtable_record(self, existing: Dict, log: ComprehensiveTradeLog) -> bool:
        """Update existing Airtable record with latest data"""
        try:
            fields = self._prepare_airtable_fields(log)
            record_id = existing['id']
            
            logger.info(f"Updating Airtable record {record_id} for {log.order_id}")
            
            result = self.table.update(record_id, fields)
            
            logger.info(f"✅ Updated record for {log.setup_name} - {log.order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating Airtable record: {e}")
            return False
    
    def sync_oanda_transactions(self, from_id: Optional[str] = None) -> Dict[str, int]:
        """Sync recent Oanda transactions and match with comprehensive logs"""
        logger.info("Starting Oanda transaction sync...")
        
        results = {
            'processed': 0,
            'matched': 0,
            'errors': 0
        }
        
        try:
            # Get recent transactions
            if not from_id:
                # Get last 100 transactions if no starting point
                from_id = "1"
            
            params = {"from": from_id, "to": "99999999"}
            r = TransactionIDRange(accountID=ACCOUNT_ID, params=params)
            self.oanda_client.request(r)
            
            transactions = r.response.get("transactions", [])
            logger.info(f"Retrieved {len(transactions)} transactions from Oanda")
            
            for tx in transactions:
                tx_type = tx.get("type")
                
                if tx_type == "ORDER_FILL":
                    results['processed'] += 1
                    if self._process_order_fill(tx):
                        results['matched'] += 1
                elif tx_type in ["LIMIT_ORDER", "MARKET_ORDER"]:
                    results['processed'] += 1
                    if self._process_order_creation(tx):
                        results['matched'] += 1
                        
        except Exception as e:
            logger.error(f"Error syncing Oanda transactions: {e}")
            results['errors'] += 1
        
        logger.info(f"Oanda sync complete: {results}")
        return results
    
    def _process_order_fill(self, tx: Dict) -> bool:
        """Process ORDER_FILL transaction and match with logs"""
        try:
            order_id = tx.get("orderID")
            trade_id = tx.get("tradeOpened", {}).get("tradeID")
            
            if not order_id:
                return False
            
            # Update the comprehensive log
            fill_data = {
                'trade_id': trade_id,
                'execution_time': tx.get("time"),
                'filled_price': float(tx.get("price", 0))
            }
            
            self.trade_logger.update_order_filled(order_id, fill_data)
            return True
            
        except Exception as e:
            logger.error(f"Error processing order fill: {e}")
            return False
    
    def _process_order_creation(self, tx: Dict) -> bool:
        """Process order creation and ensure it's logged"""
        try:
            # Extract order data
            order_data = {
                'order_id': tx.get('id'),
                'instrument': tx.get('instrument'),
                'order_type': tx.get('type'),
                'direction': 'BUY' if float(tx.get('units', 0)) > 0 else 'SELL',
                'units': abs(int(float(tx.get('units', 0)))),
                'entry_price': float(tx.get('price', 0)),
                'order_time': tx.get('time')
            }
            
            # Check if already logged
            existing_log = None
            for key, log in self.trade_logger.comprehensive_log.items():
                if log.order_id == order_data['order_id']:
                    existing_log = log
                    break
            
            if existing_log:
                logger.debug(f"Order {order_data['order_id']} already logged")
                return True
            
            # If not logged, create minimal log entry
            # (This handles orders placed outside our system)
            metadata = {
                'setup_name': f"External_{order_data['instrument']}_{order_data['direction']}",
                'strategy_tag': 'EXTERNAL',
                'notes': 'Order placed outside tracking system'
            }
            
            strategy_context = {
                'market_time_et': datetime.now().isoformat()
            }
            
            self.trade_logger.log_order_placement(order_data, metadata, strategy_context)
            return True
            
        except Exception as e:
            logger.error(f"Error processing order creation: {e}")
            return False
    
    def update_open_trades_prices(self) -> int:
        """Update current prices for all open trades"""
        logger.info("Updating prices for open trades...")
        
        updated = 0
        
        try:
            # Get open trades from Oanda
            r = OpenTrades(accountID=ACCOUNT_ID)
            self.oanda_client.request(r)
            open_trades = r.response.get("trades", [])
            
            logger.info(f"Found {len(open_trades)} open trades")
            
            for trade in open_trades:
                trade_id = trade.get("id")
                instrument = trade.get("instrument")
                
                # Get current price
                current_price = self._get_current_price(instrument)
                if not current_price:
                    continue
                
                # Find Airtable record
                formula = f"{{Fill ID}} = '{trade_id}'"
                records = self.table.all(formula=formula)
                
                if records:
                    record = records[0]
                    fields = {
                        'Current Price': current_price,
                        'Unrealized PL': float(trade.get('unrealizedPL', 0)),
                        'Trade State': 'Open'
                    }
                    
                    self.table.update(record['id'], fields)
                    updated += 1
                    logger.info(f"Updated price for {instrument}: {current_price}")
                    
        except Exception as e:
            logger.error(f"Error updating open trade prices: {e}")
        
        logger.info(f"Updated {updated} open trade prices")
        return updated
    
    def _get_current_price(self, instrument: str) -> Optional[float]:
        """Get current market price for instrument"""
        try:
            params = {"instruments": instrument}
            r = PricingInfo(accountID=ACCOUNT_ID, params=params)
            self.oanda_client.request(r)
            
            prices = r.response.get("prices", [])
            if prices:
                price_data = prices[0]
                bid = float(price_data["bids"][0]["price"])
                ask = float(price_data["asks"][0]["price"])
                return (bid + ask) / 2
                
        except Exception as e:
            logger.error(f"Error getting price for {instrument}: {e}")
        
        return None
    
    def generate_sync_report(self) -> str:
        """Generate comprehensive sync report"""
        stats = self.trade_logger.get_trade_statistics()
        
        report = []
        report.append("=" * 60)
        report.append("ENHANCED TRADE SYNC REPORT")
        report.append("=" * 60)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        report.append("📊 TRADE LOG STATISTICS:")
        report.append(f"  Total Logs: {stats['total_logs']}")
        report.append(f"  Pending Orders: {stats['pending_orders']}")
        report.append(f"  Filled Trades: {stats['filled_trades']}")
        report.append(f"  Cancelled Orders: {stats['cancelled_orders']}")
        report.append(f"  Unsynced Logs: {stats['unsynced_logs']}")
        report.append("")
        
        report.append("📈 STRATEGY BREAKDOWN:")
        for strategy, count in stats['strategy_breakdown'].items():
            report.append(f"  {strategy}: {count} trades")
        report.append("")
        
        report.append(f"📁 Log File: {stats['log_file']}")
        report.append("=" * 60)
        
        return "\n".join(report)


def main():
    """Main function to run enhanced sync"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('enhanced_sync.log')
        ]
    )
    
    logger.info("Starting Enhanced Trade Sync...")
    
    try:
        # Initialize sync system
        sync = EnhancedTradeSync()
        
        # Run comprehensive log sync
        log_results = sync.sync_comprehensive_logs()
        logger.info(f"Log sync results: {log_results}")
        
        # Sync recent Oanda transactions
        oanda_results = sync.sync_oanda_transactions()
        logger.info(f"Oanda sync results: {oanda_results}")
        
        # Update open trade prices
        updated_prices = sync.update_open_trades_prices()
        logger.info(f"Updated {updated_prices} open trade prices")
        
        # Generate and print report
        report = sync.generate_sync_report()
        print("\n" + report)
        
        logger.info("Enhanced sync completed successfully!")
        
    except Exception as e:
        logger.error(f"Error in main sync: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()