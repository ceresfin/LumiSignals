"""
Configuration management for Fargate Data Orchestrator

ARCHITECTURE COMPLIANCE:
- Single OANDA API connection configuration
- 4-node Redis cluster endpoints
- Currency pair sharding configuration
- Rate limiting and performance settings
"""

import os
import json
import boto3
from typing import List, Dict, Any
from pydantic import Field, validator

# Handle pydantic_settings import with fallback for compatibility
try:
    from pydantic_settings import BaseSettings
    print("DEBUG: Successfully imported pydantic_settings.BaseSettings")
except ImportError as e:
    print(f"WARNING: Failed to import pydantic_settings: {e}")
    try:
        from pydantic import BaseSettings
        print("DEBUG: Fallback - using pydantic.BaseSettings (legacy)")
    except ImportError as fallback_e:
        print(f"CRITICAL: Cannot import BaseSettings from either pydantic_settings or pydantic: {fallback_e}")
        raise RuntimeError("Cannot import BaseSettings - check pydantic installation")


class Settings(BaseSettings):
    """Configuration settings for Fargate Data Orchestrator"""
    
    # OANDA API Configuration (Single Connection Point)
    oanda_api_key: str = Field(default="", env="OANDA_API_KEY")
    oanda_account_id: str = Field(default="", env="OANDA_ACCOUNT_ID")
    oanda_environment: str = Field("practice", env="OANDA_ENVIRONMENT")  # practice or live
    
    # Redis Cluster Configuration - NEW: True Cluster Mode
    # Single configuration endpoint for Redis Cluster Mode
    redis_cluster_endpoint: str = Field(
        default="lumisignals-trading-cluster.wo9apa.clustercfg.use1.cache.amazonaws.com",
        env="REDIS_CLUSTER_ENDPOINT"
    )
    
    # LEGACY: Manual sharding nodes (will be deprecated)  
    redis_cluster_nodes: List[str] = Field(
        default=[
            "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
        ],
        env="REDIS_CLUSTER_NODES"
    )
    
    # Redis Authentication
    redis_auth_token: str = Field(default="")
    redis_ssl: bool = Field(False, env="REDIS_SSL")
    redis_connection_timeout: int = Field(5, env="REDIS_CONNECTION_TIMEOUT")
    redis_socket_timeout: int = Field(5, env="REDIS_SOCKET_TIMEOUT")
    
    # Database Configuration
    database_host: str = Field(default="")
    database_port: int = Field(default=5432)
    database_name: str = Field(default="")
    database_username: str = Field(default="")
    database_password: str = Field(default="")
    database_ssl_mode: str = Field("require", env="DATABASE_SSL_MODE")
    
    # Data Collection Configuration
    collection_interval_seconds: int = Field(300, env="COLLECTION_INTERVAL_SECONDS")  # 5 minutes
    
    # Multi-timeframe candlestick collection
    timeframes: List[str] = Field(
        default=["M5", "H1"]  # Collect M5 every 5 minutes, H1 every hour
    )
    
    # Primary timeframe for frequent collection
    primary_timeframe: str = Field("M5", env="PRIMARY_TIMEFRAME")
    
    # Aggregated timeframes (created from M5 data)
    aggregated_timeframes: List[str] = Field(
        default=["M15", "M30"]  # These are computed from M5 candles
    )
    
    # Bootstrap configuration
    bootstrap_candles: int = Field(500, env="BOOTSTRAP_CANDLES")  # Historical depth for lazy loading
    
    # Tiered Redis Storage Configuration for 500 candlestick lazy loading
    hot_tier_candles: int = Field(50, env="HOT_TIER_CANDLES")      # Most recent candles for immediate access
    warm_tier_candles: int = Field(450, env="WARM_TIER_CANDLES")   # Older candles for chart scrollback
    
    # Tiered storage TTL settings
    hot_tier_ttl: int = Field(86400, env="HOT_TIER_TTL")           # 1 day for hot data
    warm_tier_ttl: int = Field(432000, env="WARM_TIER_TTL")        # 5 days for warm data
    cold_tier_ttl: int = Field(604800, env="COLD_TIER_TTL")        # 7 days for bootstrap/cold data
    
    # Collection intervals for different timeframes (in seconds)
    timeframe_intervals: Dict[str, int] = Field(
        default={
            "M5": 300,    # 5 minutes
            "M15": 900,   # 15 minutes
            "M30": 1800,  # 30 minutes
            "H1": 3600,   # 1 hour
            "H4": 14400,  # 4 hours
            "D": 86400,   # 1 day
            "W": 604800   # 1 week
        }
    )
    
    # Currency Pairs Configuration (28 pairs for comprehensive coverage)
    currency_pairs: List[str] = Field(
        default=[
            # Major USD pairs (7)
            "EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "NZD_USD", "USD_CHF",
            # EUR cross pairs (6)
            "EUR_GBP", "EUR_JPY", "EUR_CAD", "EUR_AUD", "EUR_NZD", "EUR_CHF",
            # GBP cross pairs (5)
            "GBP_JPY", "GBP_CAD", "GBP_AUD", "GBP_NZD", "GBP_CHF",
            # AUD cross pairs (4)  
            "AUD_JPY", "AUD_CAD", "AUD_NZD", "AUD_CHF",
            # NZD cross pairs (3)
            "NZD_JPY", "NZD_CAD", "NZD_CHF",
            # Additional cross pairs (3)
            "CAD_JPY", "CAD_CHF", "CHF_JPY"
        ],
        env="CURRENCY_PAIRS"
    )
    
    # Currency Pair Sharding Configuration (28 pairs across 4 shards)
    shard_configuration: Dict[str, List[str]] = Field(
        default={
            "shard_0": ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "NZD_USD", "USD_CHF"],
            "shard_1": ["EUR_GBP", "EUR_JPY", "EUR_CAD", "EUR_AUD", "EUR_NZD", "EUR_CHF", "GBP_JPY"],
            "shard_2": ["GBP_CAD", "GBP_AUD", "GBP_NZD", "GBP_CHF", "AUD_JPY", "AUD_CAD", "AUD_NZD"], 
            "shard_3": ["AUD_CHF", "NZD_JPY", "NZD_CAD", "NZD_CHF", "CAD_JPY", "CAD_CHF", "CHF_JPY"]
        }
    )
    
    # OANDA API Rate Limiting
    max_requests_per_second: int = Field(10, env="MAX_REQUESTS_PER_SECOND")
    burst_limit: int = Field(20, env="BURST_LIMIT")
    
    # Performance Configuration
    batch_size: int = Field(5, env="BATCH_SIZE")  # Process 5 pairs at once
    concurrent_requests: int = Field(3, env="CONCURRENT_REQUESTS")
    retry_attempts: int = Field(3, env="RETRY_ATTEMPTS")
    retry_delay_seconds: int = Field(1, env="RETRY_DELAY_SECONDS")
    
    # Data Retention Configuration
    redis_ttl_seconds: int = Field(432000, env="REDIS_TTL_SECONDS")  # 5 days (120 hours)
    historical_data_points: int = Field(1200, env="HISTORICAL_DATA_POINTS")
    
    # H1 Backfill Configuration - Enhanced for trader scrollback experience
    h1_backfill_days: int = Field(30, env="H1_BACKFILL_DAYS")  # Days of H1 data to collect
    h1_max_candles: int = Field(500, env="H1_MAX_CANDLES")  # Max candles to store in Redis
    
    # Health Monitoring
    health_check_interval: int = Field(30, env="HEALTH_CHECK_INTERVAL")  # 30 seconds
    oanda_health_check_interval: int = Field(60, env="OANDA_HEALTH_CHECK_INTERVAL")  # 1 minute
    
    # AWS Configuration
    aws_region: str = Field("us-east-1", env="AWS_REGION")
    secrets_manager_enabled: bool = Field(True, env="SECRETS_MANAGER_ENABLED")
    
    # Logging Configuration
    log_level: str = Field("INFO", env="LOG_LEVEL")
    structured_logging: bool = Field(True, env="STRUCTURED_LOGGING")
    
    @validator("redis_cluster_nodes", pre=True)
    def parse_redis_nodes(cls, v):
        """Parse Redis nodes from environment variable if string"""
        if isinstance(v, str):
            return [node.strip() for node in v.split(",")]
        return v
    
    @validator("currency_pairs", pre=True)
    def parse_currency_pairs(cls, v):
        """Parse currency pairs from environment variable if string"""
        if isinstance(v, str):
            return [pair.strip() for pair in v.split(",")]
        return v
    
    @validator("oanda_environment")
    def validate_oanda_environment(cls, v):
        """Validate OANDA environment"""
        if v not in ["practice", "live"]:
            raise ValueError("OANDA environment must be 'practice' or 'live'")
        return v
    
    @validator("collection_interval_seconds")
    def validate_collection_interval(cls, v):
        """Validate collection interval (must be 300 seconds for 5-minute architecture)"""
        if v < 300:
            raise ValueError("Collection interval must be at least 300 seconds for multi-timeframe architecture")
        return v
    
    @validator("timeframes", pre=True)
    def parse_timeframes(cls, v):
        """Parse timeframes from environment variable if string"""
        print(f"DEBUG: parse_timeframes called with value: {repr(v)} (type: {type(v)})")
        if isinstance(v, str):
            result = [tf.strip() for tf in v.split(",")]
            print(f"DEBUG: parse_timeframes returning: {result}")
            return result
        print(f"DEBUG: parse_timeframes returning unchanged: {v}")
        return v
    
    @validator("aggregated_timeframes", pre=True)
    def parse_aggregated_timeframes(cls, v):
        """Parse aggregated timeframes from environment variable if string"""
        if isinstance(v, str):
            return [tf.strip() for tf in v.split(",")]
        return v
    
    def should_collect_timeframe(self, timeframe: str, current_time: int) -> bool:
        """Check if a timeframe should be collected based on time interval"""
        if timeframe not in self.timeframe_intervals:
            return False
        
        # Use proper interval logic for each timeframe
        # M5: every 5 minutes, H1: every hour, etc.
        interval = self.timeframe_intervals[timeframe]
        return current_time % interval == 0
    
    def get_timeframes_to_collect(self, current_time: int) -> List[str]:
        """Get list of timeframes that should be collected at current time"""
        # Always collect M5 (primary timeframe)
        timeframes_to_collect = [self.primary_timeframe]
        
        # ARCHITECTURE COMPLIANCE: Always collect H1 for dashboard compatibility
        # The Architecture Bible specifies H1 data for pipstop.org dashboard
        # Fix: Explicitly ensure H1 is always collected when configured
        if "H1" in self.timeframes:
            if "H1" not in timeframes_to_collect:
                timeframes_to_collect.append("H1")
                print(f"DEBUG: ✅ H1 added for architecture compliance - dashboard needs H1 data")
            else:
                print(f"DEBUG: ℹ️ H1 already in collection list")
        
        # Add other timeframes based on their intervals (excluding H1 which is always collected)
        for timeframe in self.timeframes:
            if (timeframe != self.primary_timeframe and 
                timeframe != "H1" and 
                self.should_collect_timeframe(timeframe, current_time)):
                timeframes_to_collect.append(timeframe)
        
        return timeframes_to_collect
    
    def should_aggregate_timeframe(self, timeframe: str, current_time: int) -> bool:
        """Check if an aggregated timeframe should be computed at current time"""
        if timeframe not in self.aggregated_timeframes:
            return False
        
        # Check if we're at the boundary for this aggregated timeframe
        interval = self.timeframe_intervals[timeframe]
        return current_time % interval == 0
    
    def get_aggregation_ratio(self, timeframe: str) -> int:
        """Get how many M5 candles are needed to create one aggregated candle"""
        aggregation_map = {
            "M15": 3,   # 15 min / 5 min = 3 M5 candles
            "M30": 6,   # 30 min / 5 min = 6 M5 candles
            "H1": 12,   # 60 min / 5 min = 12 M5 candles (but H1 is native, not aggregated)
        }
        return aggregation_map.get(timeframe, 1)
    
    def get_all_supported_timeframes(self) -> List[str]:
        """Get all timeframes supported (native + aggregated)"""
        return self.timeframes + self.aggregated_timeframes
    
    def get_candle_count_for_collection(self, timeframe: str, is_bootstrap: bool) -> int:
        """Get number of candles to collect - 500 for bootstrap, 1 for incremental"""
        if is_bootstrap:
            return self.bootstrap_candles
        else:
            return 1  # Only collect latest candle for ongoing updates
    
    def get_total_tier_capacity(self) -> int:
        """Get total capacity across all tiers (should equal bootstrap_candles)"""
        return self.hot_tier_candles + self.warm_tier_candles
    
    def get_tier_config_for_timeframe(self, timeframe: str) -> Dict[str, Any]:
        """Get tiered storage configuration for a specific timeframe"""
        return {
            'hot': {
                'capacity': self.hot_tier_candles,
                'ttl': self.hot_tier_ttl,
                'key_suffix': ':hot'
            },
            'warm': {
                'capacity': self.warm_tier_candles, 
                'ttl': self.warm_tier_ttl,
                'key_suffix': ':warm'
            },
            'cold': {
                'capacity': self.bootstrap_candles,
                'ttl': self.cold_tier_ttl,
                'key_suffix': ':historical'  # Bootstrap data
            }
        }
    
    def should_rotate_to_warm_tier(self, hot_count: int) -> bool:
        """Check if hot tier needs rotation to warm tier"""
        return hot_count > self.hot_tier_candles
    
    def get_redis_keys_for_pair_timeframe(self, currency_pair: str, timeframe: str) -> Dict[str, str]:
        """Get all Redis keys for a currency pair and timeframe"""
        base = f"market_data:{currency_pair}:{timeframe}"
        return {
            'current': f"{base}:current",
            'hot': f"{base}:hot", 
            'warm': f"{base}:warm",
            'cold': f"{base}:historical",  # Bootstrap/historical data
            'last_update': f"{base}:last_update",
            'rotation_meta': f"{base}:rotation:meta"
        }
    
    def get_redis_node_for_pair(self, currency_pair: str) -> int:
        """Get Redis node index for currency pair based on sharding"""
        for shard_name, pairs in self.shard_configuration.items():
            if currency_pair in pairs:
                # Extract shard number (shard_0 -> 0, shard_1 -> 1, etc.)
                return int(shard_name.split("_")[1])
        
        # Fallback: hash-based sharding
        return hash(currency_pair) % len(self.redis_cluster_nodes)
    
    def get_oanda_base_url(self) -> str:
        """Get OANDA base URL based on environment"""
        if self.oanda_environment == "practice":
            return "https://api-fxpractice.oanda.com"
        else:
            return "https://api-fxtrade.oanda.com"
    
    def get_architecture_info(self) -> Dict[str, Any]:
        """Get architecture compliance information"""
        return {
            "architecture_type": "Fargate Data Orchestrator",
            "oanda_connections": 1,  # Single connection point
            "redis_nodes": len(self.redis_cluster_nodes),
            "currency_pairs": len(self.currency_pairs),
            "collection_interval": f"{self.collection_interval_seconds}s",
            "timeframes": self.timeframes,
            "primary_timeframe": self.primary_timeframe,
            "data_flow": "OANDA → Fargate → Redis → Lambda Strategies",
            "cost_per_month": "$21",
            "cost_per_strategy_100_plus": "$0.21"
        }
    
    def __init__(self, **kwargs):
        print("DEBUG: Config initialization starting...")
        try:
            # Fix timeframes environment variables before pydantic processes them
            timeframes_env = os.getenv('TIMEFRAMES')
            if timeframes_env:
                print(f"DEBUG: Pre-processing TIMEFRAMES env: {timeframes_env}")
                try:
                    # Remove the env var to prevent pydantic from trying to parse it as JSON
                    del os.environ['TIMEFRAMES']
                    # Parse and set via kwargs instead
                    kwargs['timeframes'] = [tf.strip() for tf in timeframes_env.split(",")]
                    print(f"DEBUG: Set kwargs timeframes to: {kwargs['timeframes']}")
                except Exception as e:
                    print(f"ERROR: Failed to process TIMEFRAMES env var: {e}")
                    # Use default if parsing fails
                    kwargs['timeframes'] = ["M5", "H1"]
            
            aggregated_timeframes_env = os.getenv('AGGREGATED_TIMEFRAMES')
            if aggregated_timeframes_env:
                print(f"DEBUG: Pre-processing AGGREGATED_TIMEFRAMES env: {aggregated_timeframes_env}")
                try:
                    # Remove the env var to prevent pydantic from trying to parse it as JSON
                    del os.environ['AGGREGATED_TIMEFRAMES']
                    # Parse and set via kwargs instead
                    kwargs['aggregated_timeframes'] = [tf.strip() for tf in aggregated_timeframes_env.split(",")]
                    print(f"DEBUG: Set kwargs aggregated_timeframes to: {kwargs['aggregated_timeframes']}")
                except Exception as e:
                    print(f"ERROR: Failed to process AGGREGATED_TIMEFRAMES env var: {e}")
                    # Use default if parsing fails
                    kwargs['aggregated_timeframes'] = ["M15", "M30"]
            
            # Parse JSON secrets from environment variables
            print("DEBUG: About to parse JSON secrets...")
            self._parse_json_secrets()
            print("DEBUG: JSON secrets parsed successfully")
            
            print("DEBUG: About to call super().__init__...")
            super().__init__(**kwargs)
            print("DEBUG: Config initialization completed successfully")
            
        except Exception as e:
            print(f"CRITICAL: Config initialization failed: {e}")
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"Failed to initialize Settings: {e}")
    
    def _parse_json_secrets(self):
        """Parse JSON secrets from AWS Secrets Manager environment variables"""
        try:
            # Parse OANDA credentials from JSON secret
            oanda_credentials_json = os.getenv('OANDA_CREDENTIALS')
            if oanda_credentials_json and oanda_credentials_json.strip():
                oanda_creds = json.loads(oanda_credentials_json)
                os.environ['OANDA_API_KEY'] = oanda_creds.get('api_key', '')
                os.environ['OANDA_ACCOUNT_ID'] = oanda_creds.get('account_id', '')
                # Set oanda_environment from secret if available
                if 'environment' in oanda_creds:
                    os.environ['OANDA_ENVIRONMENT'] = oanda_creds['environment']
            
            # Parse Redis credentials from JSON secret
            redis_credentials_json = os.getenv('REDIS_CREDENTIALS')
            if redis_credentials_json and redis_credentials_json.strip():
                redis_creds = json.loads(redis_credentials_json)
                os.environ['REDIS_AUTH_TOKEN'] = redis_creds.get('auth_token', '')
                
                # Check if this is a 4-shard cluster configuration
                if 'shard_0' in redis_creds or 'shard_1' in redis_creds:
                    # Multi-shard configuration
                    redis_nodes = []
                    for i in range(0, 4):  # shards 0-3
                        shard_key = f'shard_{i}'
                        if shard_key in redis_creds:
                            redis_nodes.append(redis_creds[shard_key])
                    if redis_nodes:
                        os.environ['REDIS_CLUSTER_NODES'] = json.dumps(redis_nodes)
                else:
                    # Single node configuration (backward compatibility)
                    endpoint = redis_creds.get('endpoint', '')
                    port = redis_creds.get('port', 6379)
                    if endpoint:
                        # Set the Redis cluster nodes from the secret as JSON array for Pydantic List[str]
                        os.environ['REDIS_CLUSTER_NODES'] = json.dumps([f"{endpoint}:{port}"])
            
            # Parse Database credentials - prioritize DATABASE_CREDENTIALS JSON format
            # Method 1: JSON secret (Architecture Bible format - preferred)
            database_credentials_json = os.getenv('DATABASE_CREDENTIALS')
            if database_credentials_json and database_credentials_json.strip():
                db_creds = json.loads(database_credentials_json)
                os.environ['DATABASE_HOST'] = db_creds.get('host', '')
                os.environ['DATABASE_PORT'] = str(db_creds.get('port', 5432))
                os.environ['DATABASE_NAME'] = db_creds.get('dbname', '')
                os.environ['DATABASE_USERNAME'] = db_creds.get('username', '')
                os.environ['DATABASE_PASSWORD'] = db_creds.get('password', '')
                # Database credentials parsed successfully
            elif os.getenv('DATABASE_HOST'):
                # Method 2: Individual environment variables (fallback)
                # Using individual database environment variables (fallback)
                # Individual variables already set by AWS Secrets Manager
                pass
            else:
                # No database credentials found
                pass
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON secrets - invalid JSON format: {e}")
            import traceback
            traceback.print_exc()
            # Don't raise here - allow system to continue with defaults
        except Exception as e:
            print(f"ERROR: Error processing secrets: {e}")
            import traceback
            traceback.print_exc()
            # Don't raise here - allow system to continue with defaults
    
    @property
    def parsed_oanda_api_key(self) -> str:
        """Get OANDA API key from parsed credentials"""
        api_key = os.getenv('OANDA_API_KEY', self.oanda_api_key)
        return api_key
    
    @property
    def parsed_oanda_account_id(self) -> str:
        """Get OANDA account ID from parsed credentials"""
        account_id = os.getenv('OANDA_ACCOUNT_ID', self.oanda_account_id)
        return account_id
    
    @property
    def parsed_redis_auth_token(self) -> str:
        """Get Redis auth token from parsed credentials"""
        return os.getenv('REDIS_AUTH_TOKEN', self.redis_auth_token)
    
    @property
    def parsed_database_host(self) -> str:
        """Get database host from parsed credentials"""
        host = os.getenv('DATABASE_HOST', self.database_host)
        return host
    
    @property
    def parsed_database_port(self) -> int:
        """Get database port from parsed credentials"""
        return int(os.getenv('DATABASE_PORT', self.database_port))
    
    @property
    def parsed_database_name(self) -> str:
        """Get database name from parsed credentials"""
        return os.getenv('DATABASE_NAME', self.database_name)
    
    @property
    def parsed_database_username(self) -> str:
        """Get database username from parsed credentials"""
        return os.getenv('DATABASE_USERNAME', self.database_username)
    
    @property
    def parsed_database_password(self) -> str:
        """Get database password from parsed credentials"""
        return os.getenv('DATABASE_PASSWORD', self.database_password)
    
    def get_database_connection_string(self) -> str:
        """Get PostgreSQL connection string with SSL"""
        return f"postgresql://{self.parsed_database_username}:{self.parsed_database_password}@{self.parsed_database_host}:{self.parsed_database_port}/{self.parsed_database_name}?sslmode={self.database_ssl_mode}"
    
    class Config:
        env_file = ".env"
        case_sensitive = False