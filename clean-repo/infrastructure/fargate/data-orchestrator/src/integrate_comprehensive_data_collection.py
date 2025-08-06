#!/usr/bin/env python3
"""
Integration Script: Comprehensive OANDA Data Collection for Fargate
This script integrates the enhanced data collection into the existing Fargate Data Orchestrator
"""

import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from .enhanced_oanda_data_collection import EnhancedOandaDataCollector
from .enhanced_database_manager import EnhancedDatabaseManager

logger = logging.getLogger(__name__)

class ComprehensiveDataOrchestrator:
    """
    Main orchestrator that combines enhanced OANDA data collection with database storage
    
    This replaces the basic data collection with comprehensive 31-field collection
    """
    
    def __init__(self, oanda_client, database_config: Dict[str, Any]):
        self.oanda_client = oanda_client
        self.data_collector = EnhancedOandaDataCollector(oanda_client)
        self.db_manager = EnhancedDatabaseManager(database_config)
        self.is_initialized = False
    
    async def initialize(self) -> bool:
        """Initialize the comprehensive data orchestrator"""
        try:
            logger.info("🚀 Initializing Comprehensive Data Orchestrator...")
            
            # Initialize database connection pool
            db_initialized = await self.db_manager.initialize_connection_pool()
            if not db_initialized:
                logger.error("Failed to initialize database connection")
                return False
            
            # Test OANDA connectivity
            if not self.oanda_client.is_connected:
                logger.error("OANDA client not connected")
                return False
            
            self.is_initialized = True
            logger.info("✅ Comprehensive Data Orchestrator initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize orchestrator: {str(e)}")
            return False
    
    async def collect_and_store_comprehensive_data(self) -> bool:
        """
        Main method: Collect comprehensive OANDA data and store in RDS
        
        This is the method that should be called by the main Fargate task
        """
        if not self.is_initialized:
            logger.error("Orchestrator not initialized")
            return False
        
        try:
            start_time = datetime.now(timezone.utc)
            logger.info("🔄 Starting comprehensive data collection cycle...")
            
            # Step 1: Collect comprehensive trade data from OANDA
            comprehensive_data = await self.data_collector.collect_comprehensive_trade_data()
            if not comprehensive_data:
                logger.warning("No comprehensive trade data collected")
                return False
            
            trades = comprehensive_data.get('trades', [])
            current_trade_ids = [str(trade.get('trade_id', '')) for trade in trades if trade.get('trade_id')]
            
            logger.info(f"📊 Collected comprehensive data for {len(trades)} active trades")
            
            # Step 2: Store comprehensive data in RDS (if any trades exist)
            if trades:
                storage_success = await self.db_manager.store_comprehensive_active_trades(trades)
                if not storage_success:
                    logger.error("Failed to store comprehensive trade data")
                    return False
            else:
                logger.info("No active trades found in OANDA")
            
            # Step 3: Cleanup inactive trades (OANDA-based cleanup)
            # This removes trades from RDS that are no longer active in OANDA
            cleanup_success = await self.db_manager.cleanup_inactive_trades(current_trade_ids)
            if not cleanup_success:
                logger.warning("Failed to cleanup inactive trades")
            
            # Step 4: Get and log storage summary
            summary = await self.db_manager.get_active_trades_summary()
            if summary:
                self._log_collection_summary(summary, start_time)
            
            # Step 5: Optional time-based cleanup for very old trades (keep as backup)
            await self.db_manager.cleanup_stale_trades(hours_threshold=168)  # 7 days instead of 24 hours
            
            logger.info("✅ Comprehensive data collection cycle completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Comprehensive data collection failed: {str(e)}", exc_info=True)
            return False
    
    def _log_collection_summary(self, summary: Dict[str, Any], start_time: datetime):
        """Log comprehensive collection summary"""
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        logger.info("📊 Comprehensive Data Collection Summary:")
        logger.info(f"  ⏱️  Collection Duration: {duration:.2f} seconds")
        logger.info(f"  📈 Total Active Trades: {summary['total_active_trades']}")
        logger.info(f"  🛡️  Trades with Stop Loss: {summary['trades_with_stop_loss']}")
        logger.info(f"  🎯 Trades with Take Profit: {summary['trades_with_take_profit']}")
        logger.info(f"  ⚖️  Trades with Risk:Reward: {summary['trades_with_risk_reward']}")
        logger.info(f"  📏 Average Pips Moved: {summary['average_pips_moved']:.1f}")
        logger.info(f"  💰 Total Unrealized P&L: ${summary['total_unrealized_pnl']:.2f}")
        logger.info(f"  🏦 Total Margin Used: ${summary['total_margin_used']:.2f}")
        logger.info(f"  🎯 Unique Strategies: {summary['unique_strategies']}")
        logger.info(f"  🌍 Active Sessions: {summary['active_sessions']}")
        
        # Calculate completion percentage
        completion_percentage = 0
        if summary['total_active_trades'] > 0:
            fields_completed = (
                summary['trades_with_stop_loss'] + 
                summary['trades_with_take_profit'] + 
                summary['trades_with_risk_reward']
            )
            max_possible = summary['total_active_trades'] * 3  # 3 key enhanced fields
            completion_percentage = (fields_completed / max_possible) * 100 if max_possible > 0 else 0
        
        logger.info(f"  ✅ Enhancement Completion: {completion_percentage:.1f}%")
    
    async def get_data_quality_report(self) -> Optional[Dict[str, Any]]:
        """Generate a data quality report for monitoring"""
        try:
            summary = await self.db_manager.get_active_trades_summary()
            if not summary:
                return None
            
            total_trades = summary['total_active_trades']
            if total_trades == 0:
                return {
                    'status': 'NO_TRADES',
                    'message': 'No active trades found',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            
            # Calculate data quality metrics
            sl_coverage = (summary['trades_with_stop_loss'] / total_trades) * 100
            tp_coverage = (summary['trades_with_take_profit'] / total_trades) * 100
            rr_coverage = (summary['trades_with_risk_reward'] / total_trades) * 100
            
            # Determine overall quality status
            avg_coverage = (sl_coverage + tp_coverage + rr_coverage) / 3
            
            if avg_coverage >= 80:
                status = 'EXCELLENT'
            elif avg_coverage >= 60:
                status = 'GOOD'
            elif avg_coverage >= 40:
                status = 'FAIR'
            else:
                status = 'POOR'
            
            return {
                'status': status,
                'overall_coverage': round(avg_coverage, 1),
                'metrics': {
                    'total_active_trades': total_trades,
                    'stop_loss_coverage': round(sl_coverage, 1),
                    'take_profit_coverage': round(tp_coverage, 1),
                    'risk_reward_coverage': round(rr_coverage, 1),
                    'average_pips_moved': round(summary['average_pips_moved'], 1),
                    'total_unrealized_pnl': round(summary['total_unrealized_pnl'], 2)
                },
                'recommendations': self._generate_recommendations(sl_coverage, tp_coverage, rr_coverage),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to generate data quality report: {str(e)}")
            return None
    
    def _generate_recommendations(self, sl_coverage: float, tp_coverage: float, rr_coverage: float) -> list:
        """Generate recommendations based on data quality metrics"""
        recommendations = []
        
        if sl_coverage < 50:
            recommendations.append("Consider reviewing stop loss order placement in trading strategies")
        
        if tp_coverage < 50:
            recommendations.append("Consider reviewing take profit order placement in trading strategies")
        
        if rr_coverage < 80:
            recommendations.append("Ensure both stop loss and take profit orders are set for risk:reward calculations")
        
        if not recommendations:
            recommendations.append("Data quality is excellent - all key fields are well populated")
        
        return recommendations
    
    async def shutdown(self):
        """Gracefully shutdown the orchestrator"""
        try:
            logger.info("🔄 Shutting down Comprehensive Data Orchestrator...")
            await self.db_manager.close_connection_pool()
            logger.info("✅ Orchestrator shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")


# Integration function for existing Fargate main loop
async def integrate_comprehensive_collection(oanda_client, database_config: Dict[str, Any]) -> bool:
    """
    Integration function that can be called from the existing Fargate main loop
    
    Usage in main.py:
    
    from .integrate_comprehensive_data_collection import integrate_comprehensive_collection
    
    # In your main loop:
    success = await integrate_comprehensive_collection(oanda_client, db_config)
    if success:
        logger.info("Comprehensive data collection completed")
    else:
        logger.error("Comprehensive data collection failed")
    """
    
    orchestrator = ComprehensiveDataOrchestrator(oanda_client, database_config)
    
    try:
        # Initialize
        if not await orchestrator.initialize():
            return False
        
        # Collect and store data
        success = await orchestrator.collect_and_store_comprehensive_data()
        
        # Generate quality report
        quality_report = await orchestrator.get_data_quality_report()
        if quality_report:
            logger.info(f"Data Quality: {quality_report['status']} ({quality_report['overall_coverage']}% coverage)")
        
        return success
        
    finally:
        await orchestrator.shutdown()


# Example usage for testing
async def test_comprehensive_collection():
    """Test function for comprehensive data collection"""
    # This would be used for testing the integration
    
    # Mock config (replace with actual config in production)
    db_config = {
        'host': 'your-rds-host',
        'port': 5432,
        'username': 'your-username', 
        'password': 'your-password',
        'dbname': 'your-database'
    }
    
    # Mock OANDA client (replace with actual client in production)
    # oanda_client = YourOandaClient()
    
    # success = await integrate_comprehensive_collection(oanda_client, db_config)
    # print(f"Comprehensive collection test result: {success}")
    
    logger.info("Test function - replace with actual implementation")


if __name__ == "__main__":
    # Run test
    asyncio.run(test_comprehensive_collection())