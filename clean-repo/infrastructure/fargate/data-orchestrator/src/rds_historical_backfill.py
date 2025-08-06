#!/usr/bin/env python3
"""
RDS Historical Backfill using EXACT GitHub methods
Copy-paste from infrastructure/lambda/trade-sync/sync/closed_trades.py
Just changing target from Airtable to RDS
"""

import json
import urllib.request
import logging
import asyncpg
import boto3
from datetime import datetime, timedelta
from dateutil import parser

logger = logging.getLogger(__name__)

class RDSHistoricalBackfill:
    """Copy-paste GitHub methods but target RDS instead of Airtable"""
    
    def __init__(self):
        self.db_pool = None
        
    async def initialize_db(self):
        """Initialize RDS connection"""
        # Get database credentials
        secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
        secret_response = secrets_client.get_secret_value(
            SecretId='lumisignals/rds/postgresql/credentials'
        )
        db_creds = json.loads(secret_response['SecretString'])
        
        # Initialize database connection pool
        self.db_pool = await asyncpg.create_pool(
            host=db_creds['host'],
            port=db_creds['port'],
            user=db_creds['username'],
            password=db_creds['password'],
            database=db_creds['dbname'],
            min_size=1,
            max_size=3
        )
        
    async def sync_closed_trades_to_rds(self, api_key, account_id, base_url):
        """EXACT COPY of sync_closed_trades_enhanced but targeting RDS"""
        
        logger.info(f"💼 Syncing ALL closed trades from June 2025 to current - TO RDS")
        
        # Get closed trades from OANDA - from June 1, 2025 to current
        import urllib.parse
        
        end_date = datetime.now()
        start_date = datetime(2025, 6, 1)  # June 1, 2025
        from_time = start_date.strftime('%Y-%m-%dT%H:%M:%S.000000000Z')
        to_time = end_date.strftime('%Y-%m-%dT%H:%M:%S.000000000Z')
        
        # Build URL with parameters
        params = {
            'state': 'CLOSED',
            'fromTime': from_time,
            'toTime': to_time,
            'count': 500
        }
        
        url = f"{base_url}/v3/accounts/{account_id}/trades?" + urllib.parse.urlencode(params)
        
        try:
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {api_key}')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            
            closed_trades = data.get('trades', [])
            logger.info(f"📋 Found {len(closed_trades)} closed trades from OANDA")
            
        except Exception as e:
            logger.error(f"❌ Error fetching closed trades: {str(e)}")
            return {'operations': 0, 'created': 0, 'updated': 0, 'deleted': 0}
        
        if not closed_trades:
            logger.info("ℹ️  No closed trades found")
            return {'operations': 0, 'created': 0, 'updated': 0, 'deleted': 0}
        
        operations = {'created': 0, 'updated': 0, 'deleted': 0, 'skipped': 0}
        
        logger.info(f"🔄 Processing {len(closed_trades)} closed trades from OANDA API...")
        
        # Process each closed trade
        for i, trade in enumerate(closed_trades, 1):
            trade_id = trade.get('id')
            if not trade_id:
                continue
            
            # Parse trade data
            instrument = trade.get('instrument', '').replace('_', '/')
            current_units = float(trade.get('currentUnits', 0))
            initial_units = float(trade.get('initialUnits', 0))
            direction = 'Long' if initial_units > 0 else 'Short'
            
            # Parse times
            open_time = parser.parse(trade.get('openTime', ''))
            close_time = parser.parse(trade.get('closeTime', ''))
            
            # Get prices
            entry_price = float(trade.get('price', 0))
            
            # Get closing transactions to determine proper close reason
            closing_transactions = trade.get('closingTransactionIDs', [])
            
            # EXACT COPY: Determine close reason based on trade state and closing transactions
            close_reason = self.determine_close_reason(trade, api_key, account_id, base_url)
            
            # EXACT COPY: Filter trades - only include Stop Loss, Take Profit, or Sell Market
            if close_reason not in ['Stop Loss', 'Take Profit', 'Sell Market']:
                operations['skipped'] += 1
                logger.info(f"⏭️  Skipping trade {i}/{len(closed_trades)} {trade_id} - Close reason '{close_reason}' not in allowed types")
                continue
            
            logger.info(f"✅ Processing trade {i}/{len(closed_trades)} {trade_id} - Close reason: '{close_reason}'")
            
            # Calculate realized P&L
            realized_pl = float(trade.get('realizedPL', 0))
            
            # EXACT COPY: Calculate additional fields using GitHub methods
            exit_price = self.get_exit_price(trade, closing_transactions, api_key, account_id, base_url)
            pips = self.calculate_pips(instrument, entry_price, exit_price, direction)
            
            # EXACT COPY: Get stop loss and take profit levels (if available)
            stop_loss_price = self.get_stop_loss_price(trade)
            take_profit_price = self.get_take_profit_price(trade)
            
            # EXACT COPY: Calculate risk/reward ratio
            risk_reward_ratio = self.calculate_risk_reward_ratio(entry_price, exit_price, stop_loss_price, take_profit_price, direction)
            
            # Debug logging for field values
            logger.info(f"📊 Trade {trade_id}: Close reason='{close_reason}', Pips={pips}, Entry={entry_price}, Exit={exit_price}")
            logger.info(f"📊 Trade {trade_id}: SL={stop_loss_price}, TP={take_profit_price}, RR={risk_reward_ratio}")
            
            # UPDATE RDS instead of Airtable
            async with self.db_pool.acquire() as conn:
                try:
                    result = await conn.execute("""
                        UPDATE closed_trades 
                        SET 
                            stop_loss_price = $1,
                            take_profit_price = $2,
                            risk_reward_ratio = $3,
                            exit_price = $4,
                            last_updated = NOW()
                        WHERE trade_id = $5
                    """, stop_loss_price, take_profit_price, risk_reward_ratio, exit_price, trade_id)
                    
                    if 'UPDATE 1' in str(result):
                        operations['updated'] += 1
                        logger.info(f"✅ Updated RDS trade {trade_id}")
                    else:
                        operations['skipped'] += 1
                        logger.info(f"⏭️  Trade {trade_id} not found in RDS")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to update RDS trade {trade_id}: {e}")
        
        logger.info(f"💼 RDS Update Complete: {operations['updated']} updated, {operations['skipped']} skipped")
        
        return operations

    # EXACT COPY-PASTE of GitHub methods below - NO CHANGES
    
    def determine_close_reason(self, trade, api_key, account_id, base_url):
        """EXACT COPY: Determine the proper close reason based on trade closing transactions"""
        
        trade_id = trade.get('id', 'unknown')
        closing_transaction_ids = trade.get('closingTransactionIDs', [])
        
        logger.info(f"🔍 Determining close reason for trade {trade_id}, transactions: {closing_transaction_ids}")
        
        if not closing_transaction_ids:
            logger.info(f"📋 No closing transactions for trade {trade_id}, defaulting to Sell Market")
            return 'Sell Market'
        
        # Get the closing transaction details
        for transaction_id in closing_transaction_ids:
            try:
                url = f"{base_url}/v3/accounts/{account_id}/transactions/{transaction_id}"
                req = urllib.request.Request(url)
                req.add_header('Authorization', f'Bearer {api_key}')
                
                with urllib.request.urlopen(req) as response:
                    transaction_data = json.loads(response.read().decode())
                    transaction = transaction_data.get('transaction', {})
                    
                    transaction_type = transaction.get('type', '')
                    reason = transaction.get('reason', '')
                    
                    logger.info(f"📋 Transaction {transaction_id}: type='{transaction_type}', reason='{reason}'")
                    
                    # Map transaction types to close reasons (match exact Airtable values)
                    if 'STOP_LOSS' in transaction_type or 'STOP_LOSS' in reason:
                        logger.info(f"✅ Trade {trade_id} closed by Stop Loss")
                        return 'Stop Loss'  # Changed from 'Stop Loss Hit'
                    elif 'TAKE_PROFIT' in transaction_type or 'TAKE_PROFIT' in reason:
                        logger.info(f"✅ Trade {trade_id} closed by Take Profit")
                        return 'Take Profit'
                    elif 'MARKET_ORDER' in transaction_type or 'CLIENT_REQUEST' in reason:
                        logger.info(f"✅ Trade {trade_id} closed by Market Order")
                        return 'Sell Market'
                    else:
                        logger.info(f"⚠️  Trade {trade_id} unknown close type: {transaction_type}/{reason}")
                        
            except Exception as e:
                logger.warning(f"❌ Could not fetch transaction {transaction_id} for trade {trade_id}: {e}")
                continue
        
        logger.info(f"📋 Trade {trade_id} defaulting to Sell Market after checking all transactions")
        return 'Sell Market'

    def get_exit_price(self, trade, closing_transactions, api_key, account_id, base_url):
        """EXACT COPY: Get the actual exit price from closing transactions"""
        
        if not closing_transactions:
            return float(trade.get('price', 0))  # Fallback to entry price
        
        # Try to get actual close price from first closing transaction
        try:
            transaction_id = closing_transactions[0]
            url = f"{base_url}/v3/accounts/{account_id}/transactions/{transaction_id}"
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {api_key}')
            
            with urllib.request.urlopen(req) as response:
                transaction_data = json.loads(response.read().decode())
                transaction = transaction_data.get('transaction', {})
                
                close_price = transaction.get('price')
                if close_price:
                    return float(close_price)
                    
        except Exception as e:
            logger.warning(f"Could not fetch close price: {e}")
        
        return float(trade.get('price', 0))  # Fallback to entry price

    def calculate_pips(self, instrument, entry_price, exit_price, direction):
        """EXACT COPY: Calculate pips gained/lost"""
        
        if not entry_price or not exit_price or entry_price == 0 or exit_price == 0:
            logger.warning(f"⚠️  Invalid prices for pips calculation: entry={entry_price}, exit={exit_price}")
            return None
        
        # Determine pip value based on instrument
        if 'JPY' in instrument:
            pip_multiplier = 100  # JPY pairs: 1 pip = 0.01
        else:
            pip_multiplier = 10000  # Other pairs: 1 pip = 0.0001
        
        price_diff = exit_price - entry_price
        
        # Adjust for direction
        if direction == 'Short':
            price_diff = -price_diff
        
        pips = price_diff * pip_multiplier
        
        logger.info(f"📊 Pips calculation: {instrument} {direction} entry={entry_price} exit={exit_price} diff={price_diff} pips={pips}")
        
        return pips

    def get_stop_loss_price(self, trade):
        """EXACT COPY: Extract stop loss price from trade data"""
        
        trade_id = trade.get('id', 'unknown')
        
        # Check if trade has stop loss order info
        stop_loss_order = trade.get('stopLossOrder', {})
        if stop_loss_order and stop_loss_order.get('price'):
            price = float(stop_loss_order.get('price', 0))
            logger.info(f"📊 Trade {trade_id}: Found SL price {price} from stopLossOrder")
            return price
        
        # Check trade fills for stop loss info
        trade_fills = trade.get('tradeOpened', {}).get('tradeOpened', {})
        if trade_fills:
            stop_loss = trade_fills.get('stopLossOnFill', {})
            if stop_loss and stop_loss.get('price'):
                price = float(stop_loss.get('price', 0))
                logger.info(f"📊 Trade {trade_id}: Found SL price {price} from stopLossOnFill")
                return price
        
        # Check alternative locations in trade data
        client_extensions = trade.get('clientExtensions', {})
        if client_extensions:
            logger.info(f"📊 Trade {trade_id}: clientExtensions found: {client_extensions}")
        
        logger.info(f"📊 Trade {trade_id}: No stop loss price found")
        return None

    def get_take_profit_price(self, trade):
        """EXACT COPY: Extract take profit price from trade data"""
        
        trade_id = trade.get('id', 'unknown')
        
        # Check if trade has take profit order info
        take_profit_order = trade.get('takeProfitOrder', {})
        if take_profit_order and take_profit_order.get('price'):
            price = float(take_profit_order.get('price', 0))
            logger.info(f"📊 Trade {trade_id}: Found TP price {price} from takeProfitOrder")
            return price
        
        # Check trade fills for take profit info
        trade_fills = trade.get('tradeOpened', {}).get('tradeOpened', {})
        if trade_fills:
            take_profit = trade_fills.get('takeProfitOnFill', {})
            if take_profit and take_profit.get('price'):
                price = float(take_profit.get('price', 0))
                logger.info(f"📊 Trade {trade_id}: Found TP price {price} from takeProfitOnFill")
                return price
        
        logger.info(f"📊 Trade {trade_id}: No take profit price found")
        return None

    def calculate_risk_reward_ratio(self, entry_price, exit_price, stop_loss_price, take_profit_price, direction):
        """EXACT COPY: Calculate the risk to reward ratio"""
        
        if not entry_price or not exit_price or entry_price == 0 or exit_price == 0:
            logger.info(f"📊 RR Ratio: Missing entry/exit prices: entry={entry_price}, exit={exit_price}")
            return None
        
        # Calculate actual return (profit/loss from the trade)
        if direction == 'Long':
            actual_return = exit_price - entry_price
        else:  # Short
            actual_return = entry_price - exit_price
        
        # Calculate potential risk (distance to stop loss)
        if stop_loss_price:
            if direction == 'Long':
                risk_amount = entry_price - stop_loss_price  # Risk if price falls to SL
            else:  # Short
                risk_amount = stop_loss_price - entry_price  # Risk if price rises to SL
            
            if risk_amount != 0:
                ratio = actual_return / risk_amount
                logger.info(f"📊 RR Ratio: {direction} actual_return={actual_return}, risk_amount={risk_amount}, ratio={ratio}")
                return ratio
            else:
                logger.info(f"📊 RR Ratio: Risk amount is zero")
        else:
            logger.info(f"📊 RR Ratio: No stop loss price available")
        
        return None

async def run_rds_backfill():
    """Run the RDS backfill using copied GitHub methods"""
    
    logger.info("🚀 STARTING RDS BACKFILL USING GITHUB METHODS")
    logger.info("=" * 60)
    
    # Get OANDA credentials
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    oanda_secret = secrets_client.get_secret_value(SecretId='lumisignals/oanda/api')
    oanda_creds = json.loads(oanda_secret['SecretString'])
    
    # Initialize backfill class
    backfill = RDSHistoricalBackfill()
    await backfill.initialize_db()
    
    try:
        # Run the backfill using exact GitHub methods
        results = await backfill.sync_closed_trades_to_rds(
            api_key=oanda_creds['api_key'],
            account_id=oanda_creds['account_id'], 
            base_url=oanda_creds['base_url']
        )
        
        logger.info("🎉 RDS BACKFILL COMPLETE!")
        logger.info(f"📊 Results: {results}")
        
    finally:
        if backfill.db_pool:
            await backfill.db_pool.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_rds_backfill())