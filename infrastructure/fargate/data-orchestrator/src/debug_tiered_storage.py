"""
Debug utilities for tiered storage system
Can be used in production to monitor and debug tier health
"""

import asyncio
from typing import Dict, List, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class TieredStorageDebugger:
    """Debug utilities for monitoring tiered storage health"""
    
    def __init__(self, data_orchestrator):
        self.orchestrator = data_orchestrator
        self.settings = data_orchestrator.settings
    
    async def get_full_tier_report(self) -> Dict[str, Any]:
        """Get comprehensive tier report for all currency pairs and timeframes"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'tier_configuration': {
                'hot_capacity': self.settings.hot_tier_candles,
                'warm_capacity': self.settings.warm_tier_candles,
                'total_capacity': self.settings.get_total_tier_capacity(),
                'hot_ttl': self.settings.hot_tier_ttl,
                'warm_ttl': self.settings.warm_tier_ttl,
                'cold_ttl': self.settings.cold_tier_ttl
            },
            'pairs': {}
        }
        
        # Check all currency pairs
        for pair in self.settings.currency_pairs[:3]:  # Sample first 3 pairs
            report['pairs'][pair] = {}
            
            for timeframe in ['M5', 'H1']:  # Check main timeframes
                try:
                    tier_stats = await self.orchestrator.get_tier_stats(pair, timeframe)
                    report['pairs'][pair][timeframe] = tier_stats
                except Exception as e:
                    report['pairs'][pair][timeframe] = {'error': str(e)}
        
        return report
    
    async def check_tier_health(self, currency_pair: str, timeframe: str) -> Dict[str, Any]:
        """Check health of tiered storage for a specific pair/timeframe"""
        health_report = {
            'currency_pair': currency_pair,
            'timeframe': timeframe,
            'timestamp': datetime.now().isoformat(),
            'checks': {},
            'issues': []
        }
        
        try:
            # Get tier statistics
            stats = await self.orchestrator.get_tier_stats(currency_pair, timeframe)
            
            # Check 1: Tier capacity utilization
            hot_util = stats['tiers']['hot']['utilization']
            warm_util = stats['tiers']['warm']['utilization']
            
            health_report['checks']['capacity'] = {
                'hot_utilization': f"{hot_util:.1%}",
                'warm_utilization': f"{warm_util:.1%}",
                'status': 'OK' if hot_util <= 1.0 and warm_util <= 1.0 else 'WARNING'
            }
            
            if hot_util > 1.0:
                health_report['issues'].append(f"Hot tier over capacity: {hot_util:.1%}")
            
            # Check 2: TTL health
            hot_ttl = stats['tiers']['hot']['ttl_seconds']
            warm_ttl = stats['tiers']['warm']['ttl_seconds']
            
            health_report['checks']['ttl'] = {
                'hot_ttl_remaining': hot_ttl,
                'warm_ttl_remaining': warm_ttl,
                'status': 'OK' if hot_ttl > 0 and warm_ttl > 0 else 'WARNING'
            }
            
            if hot_ttl <= 0:
                health_report['issues'].append("Hot tier TTL expired")
            if warm_ttl <= 0:
                health_report['issues'].append("Warm tier TTL expired")
            
            # Check 3: Data retrieval test
            test_result = await self.orchestrator.get_tiered_candlestick_data(
                currency_pair, timeframe, requested_count=50
            )
            
            health_report['checks']['retrieval'] = {
                'requested': 50,
                'retrieved': test_result['metadata']['actual_count'],
                'sources': test_result['metadata']['sources_used'],
                'status': 'OK' if test_result['metadata']['actual_count'] >= 50 else 'WARNING'
            }
            
            if test_result['metadata']['actual_count'] < 50:
                health_report['issues'].append(
                    f"Insufficient data: only {test_result['metadata']['actual_count']}/50 candles available"
                )
            
            # Check 4: Rotation health
            if stats['last_rotation']:
                rotation_age = (datetime.now() - datetime.fromisoformat(
                    stats['last_rotation']['timestamp'].replace('Z', '+00:00')
                )).total_seconds()
                
                health_report['checks']['rotation'] = {
                    'last_rotation_age_seconds': rotation_age,
                    'moved_candles': stats['last_rotation']['moved_candles'],
                    'status': 'OK'
                }
            
            # Overall health status
            health_report['overall_status'] = 'HEALTHY' if not health_report['issues'] else 'UNHEALTHY'
            
        except Exception as e:
            health_report['overall_status'] = 'ERROR'
            health_report['error'] = str(e)
            health_report['issues'].append(f"Health check failed: {e}")
        
        return health_report
    
    async def simulate_tier_operations(self, currency_pair: str = "EUR_USD", timeframe: str = "M5"):
        """Simulate tier operations to verify functionality"""
        logger.info(f"🧪 Simulating tier operations for {currency_pair} {timeframe}")
        
        results = {
            'simulation_start': datetime.now().isoformat(),
            'operations': []
        }
        
        # 1. Check initial state
        initial_stats = await self.orchestrator.get_tier_stats(currency_pair, timeframe)
        results['operations'].append({
            'operation': 'initial_state',
            'hot_count': initial_stats['tiers']['hot']['count'],
            'warm_count': initial_stats['tiers']['warm']['count'],
            'total': initial_stats['total_candles']
        })
        
        # 2. Retrieve data from tiers
        retrieval_test = await self.orchestrator.get_tiered_candlestick_data(
            currency_pair, timeframe, requested_count=100
        )
        results['operations'].append({
            'operation': 'data_retrieval',
            'requested': 100,
            'retrieved': retrieval_test['metadata']['actual_count'],
            'sources': retrieval_test['metadata']['sources_used']
        })
        
        # 3. Get hot tier only
        hot_only = await self.orchestrator.get_hot_tier_data_only(currency_pair, timeframe)
        results['operations'].append({
            'operation': 'hot_tier_only',
            'count': len(hot_only),
            'oldest_candle': hot_only[0]['time'] if hot_only else None,
            'newest_candle': hot_only[-1]['time'] if hot_only else None
        })
        
        results['simulation_end'] = datetime.now().isoformat()
        results['status'] = 'SUCCESS'
        
        return results


async def run_production_debug(data_orchestrator):
    """Run debug checks that can be used in production"""
    debugger = TieredStorageDebugger(data_orchestrator)
    
    # 1. Quick health check
    logger.info("🔍 Running tier health check for EUR_USD M5")
    health = await debugger.check_tier_health("EUR_USD", "M5")
    
    logger.info(f"Overall Status: {health['overall_status']}")
    if health['issues']:
        logger.warning(f"Issues found: {health['issues']}")
    
    # 2. Simulate operations
    logger.info("\n🧪 Running tier operation simulation")
    simulation = await debugger.simulate_tier_operations()
    
    for op in simulation['operations']:
        logger.info(f"Operation: {op['operation']} - {op}")
    
    return health, simulation