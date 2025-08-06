#!/usr/bin/env python3
"""
Field Mappings Configuration
Defines the mapping between OANDA API fields and Airtable fields
"""

# Active Trades field mapping
ACTIVE_TRADES_MAPPING = {
    'oanda_to_airtable': {
        'id': 'Trade ID',
        'instrument': 'Instrument',
        'price': 'Entry Price',
        'openTime': 'Open Time',
        'initialUnits': 'Units',
        'currentUnits': 'Current Units',
        'realizedPL': 'Realized P&L',
        'unrealizedPL': 'Unrealized P&L',
        'marginUsed': 'Margin Used',
        'averageClosePrice': 'Average Close Price',
        'closingTransactionIDs': 'Closing Transaction IDs',
        'financing': 'Financing',
        'closeTime': 'Close Time',
        'clientExtensions': 'Client Extensions',
        'takeProfitOrder': 'Take Profit Order',
        'stopLossOrder': 'Stop Loss Order',
        'trailingStopLossOrder': 'Trailing Stop Loss Order'
    },
    'calculated_fields': {
        'Direction': lambda trade: 'Long' if float(trade.get('initialUnits', 0)) > 0 else 'Short',
        'Current Price': lambda trade, current_price: current_price,
        'Distance to Entry': lambda trade, current_price: abs(current_price - float(trade.get('price', 0))),
        'Stop Loss': lambda trade: float(trade.get('stopLossOrder', {}).get('price', 0)) if trade.get('stopLossOrder') else None,
        'Take Profit': lambda trade: float(trade.get('takeProfitOrder', {}).get('price', 0)) if trade.get('takeProfitOrder') else None,
        'Potential Risk Amount': lambda trade: abs(float(trade.get('marginUsed', 0))),
        'Potential Profit ($)': lambda trade: float(trade.get('unrealizedPL', 0)),
        'Last Updated': lambda trade: 'current_timestamp'
    }
}

# Closed Trades field mapping
CLOSED_TRADES_MAPPING = {
    'oanda_to_airtable': {
        'id': 'Trade ID',
        'instrument': 'Instrument',
        'price': 'Entry Price',
        'openTime': 'Open Time',
        'closeTime': 'Close Time',
        'initialUnits': 'Units',
        'realizedPL': 'Gross PnL',
        'financing': 'Financing',
        'dividendAdjustment': 'Dividend Adjustment',
        'closePrice': 'Exit Price'
    },
    'calculated_fields': {
        'OANDA Order ID': lambda trade: trade.get('id'),
        'Direction': lambda trade: 'Long' if float(trade.get('initialUnits', 0)) > 0 else 'Short',
        'Duration Hours': lambda open_time, close_time: (close_time - open_time).total_seconds() / 3600,
        'Net PnL': lambda trade: float(trade.get('realizedPL', 0)) + float(trade.get('financing', 0)),
        'Gain/Loss': lambda trade: 'Gain' if float(trade.get('realizedPL', 0)) > 0 else 'Loss',
        'Close Reason': lambda trade: 'Determined by transaction type',
        'Pips': lambda instrument, entry, exit, direction: 'Calculated',
        'Strategy': lambda trade: 'Auto Trading',
        'Max Favorable': lambda trade: 0,
        'Max Adverse': lambda trade: 0,
        'Status': lambda trade: 'Closed',
        'Return:Risk Ratio': lambda trade: 'Calculated',
        'Stop Loss': lambda trade: 'Extracted from trade data',
        'Take Profit': lambda trade: 'Extracted from trade data'
    }
}

# Pending Orders field mapping
PENDING_ORDERS_MAPPING = {
    'oanda_to_airtable': {
        'id': 'Oanda Order ID',
        'instrument': 'Instrument',
        'units': 'Units',
        'price': 'Entry Price',
        'createTime': 'Created Time',
        'type': 'Order Type',
        'timeInForce': 'Time in Force',
        'gtdTime': 'GTD Time',
        'positionFill': 'Position Fill',
        'triggerCondition': 'Trigger Condition',
        'clientExtensions': 'Client Extensions'
    },
    'calculated_fields': {
        'Direction': lambda order: 'Long' if float(order.get('units', 0)) > 0 else 'Short',
        'Current Price': lambda order, current_price: current_price,
        'Distance to Market': lambda order, current_price: abs(float(order.get('price', 0)) - current_price),
        'Stop Loss': lambda order: float(order.get('stopLossOnFill', {}).get('price', 0)) if order.get('stopLossOnFill') else None,
        'Take Profit': lambda order: float(order.get('takeProfitOnFill', {}).get('price', 0)) if order.get('takeProfitOnFill') else None,
        'Last Updated': lambda order: 'current_timestamp'
    }
}

# Exposure table field mapping
EXPOSURE_MAPPING = {
    'calculated_fields': {
        'Currency': lambda currency: currency,
        'Long Exposure': lambda long_exp: long_exp,
        'Short Exposure': lambda short_exp: short_exp,
        'Net Exposure': lambda long_exp, short_exp: long_exp + short_exp,
        'Exposure': lambda net_exp_usd: net_exp_usd,  # USD exposure
        'Last Updated': lambda: 'current_timestamp'
    }
}

# Positions table field mapping
POSITIONS_MAPPING = {
    'oanda_to_airtable': {
        'instrument': 'Currency Pair',
        'marginUsed': 'Margin Used'
    },
    'calculated_fields': {
        'Long Units': lambda position: int(float(position.get('long', {}).get('units', 0))),
        'Short Units': lambda position: abs(int(float(position.get('short', {}).get('units', 0)))),
        'Net Units': lambda long_units, short_units: long_units - short_units,
        'Average Entry': lambda position: 'Calculated from position data',
        'Unrealized P&L': lambda position: float(position.get('long', {}).get('unrealizedPL', 0)) + float(position.get('short', {}).get('unrealizedPL', 0)),
        'Exposure': lambda position: 'Calculated USD exposure',
        'Last Updated': lambda: 'current_timestamp'
    }
}

# Close reason mappings
CLOSE_REASON_MAPPING = {
    'STOP_LOSS_ORDER': 'Stop Loss Hit',
    'TAKE_PROFIT_ORDER': 'Take Profit',
    'MARKET_ORDER': 'Sell Market',
    'MARKET_IF_TOUCHED_ORDER': 'Sell Market',
    'CLIENT_REQUEST': 'Sell Market',
    'MIGRATION': 'Migration',
    'MARGIN_CLOSEOUT': 'Margin Call',
    'DEFAULT': 'Sell Market'
}

# Allowed close reasons for filtering
ALLOWED_CLOSE_REASONS = ['Stop Loss Hit', 'Take Profit', 'Sell Market']