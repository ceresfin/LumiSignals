"""
Closed Trade Enhancer - DISABLED
=================================

This module has been disabled to prevent 403 errors from OANDA transaction API.
SL/TP extraction is now handled by enhanced_database_manager.py using direct field access.
"""

import structlog
from typing import Dict, Any, List

logger = structlog.get_logger()

class ClosedTradeEnhancer:
    """Disabled enhancer - no longer makes API calls"""
    
    def __init__(self, oanda_client):
        self.oanda_client = oanda_client
        logger.info("🚫 ClosedTradeEnhancer initialized but DISABLED (prevents 403 errors)")
        
    async def enhance_closed_trade(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """Return trade as-is - no enhancement to prevent 403 errors"""
        logger.debug(f"🚫 Enhancement skipped for trade {trade.get('id')} (prevents 403 errors)")
        return trade
        
    async def enhance_multiple_trades(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return trades as-is - no enhancement to prevent 403 errors"""
        logger.debug(f"🚫 Bulk enhancement skipped for {len(trades)} trades (prevents 403 errors)")
        return trades
