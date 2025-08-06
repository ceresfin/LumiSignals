// Core momentum analysis types for LumiSignals dashboard

export type MomentumDirection = 'bullish' | 'bearish';
export type MomentumStrength = 'weak' | 'strong';
export type MomentumSignal = 'STRONG_BULLISH' | 'WEAK_BULLISH' | 'NEUTRAL' | 'WEAK_BEARISH' | 'STRONG_BEARISH';

export interface TimeframeMomentum {
  direction: MomentumDirection;
  strength: MomentumStrength;
  change_percent: number;
  volume_factor: number;
}

export interface MomentumData {
  composite_score: number;      // Weighted momentum score (-100 to +100)
  rank: number;                // 1-28 ranking position
  signal: MomentumSignal;      // Overall momentum signal
  confidence: number;          // 0-1 confidence in signal
  last_updated: string;        // ISO timestamp
  timeframes: {
    '48h': TimeframeMomentum;
    '24h': TimeframeMomentum;
    '4h': TimeframeMomentum;
    '1h': TimeframeMomentum;
    '15m': TimeframeMomentum;
  };
}

export interface PriceData {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ActiveTrade {
  id: string;
  strategy: string;           // "Q-Curve Breakout", "Dime-Curve Reversal", etc.
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  position_size: number;      // Positive for long, negative for short
  entry_time: string;
  unrealized_pnl: number;
  risk_reward_ratio: number;
}

export interface CurrencyPair {
  pair: string;               // "EUR_USD"
  display_name: string;       // "EUR/USD"
  current_price: number;
  bid: number;
  ask: number;
  spread: number;
  momentum: MomentumData;
  chart_data: PriceData[];
  active_trades: ActiveTrade[];
  is_major: boolean;          // Major vs cross pair
  session_high: number;
  session_low: number;
  daily_change: number;
  daily_change_percent: number;
  strategy_signals?: StrategySignal[];
  technical_levels?: {
    support: number;
    resistance: number;
  };
}

export interface MomentumRanking {
  pairs: CurrencyPair[];
  last_updated: string;
  total_pairs: number;
  ranking_criteria: string;   // "composite_momentum_score"
}

// Portfolio exposure types
export interface CurrencyExposure {
  currency: string;           // "USD", "EUR", etc.
  net_position: number;       // In USD equivalent
  exposure_percent: number;   // Percentage of total portfolio
  pairs_contributing: string[]; // Which pairs contribute to this exposure
}

export interface PortfolioExposure {
  currencies: CurrencyExposure[];
  total_exposure: number;
  max_single_currency: number;
  exposure_concentration: number; // 0-1, higher = more concentrated
  last_calculated: string;
}

// System health types
export interface SystemHealth {
  overall_status: 'healthy' | 'warning' | 'critical';
  data_collector: {
    status: 'online' | 'offline' | 'degraded';
    last_seen: string;
    pairs_collected: number;
    collection_latency_ms: number;
  };
  redis: {
    status: 'connected' | 'disconnected';
    latency_ms: number;
    cache_hit_rate: number;
    memory_usage_percent: number;
  };
  database: {
    status: 'connected' | 'disconnected';
    query_latency_ms: number;
    connection_pool_usage: number;
  };
  lambda_functions: {
    total_executions: number;
    successful_executions: number;
    error_rate: number;
    avg_duration_ms: number;
  };
}

// WebSocket message types
export interface WebSocketMessage {
  type: 'momentum_update' | 'price_update' | 'trade_update' | 'system_health';
  timestamp: string;
  data: MomentumRanking | CurrencyPair | ActiveTrade | SystemHealth;
}

// API response types
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: string;
  timestamp: string;
}

// Chart display types
export interface ChartConfig {
  timeframe: '15m' | '1h' | '4h' | '1d';
  show_trades: boolean;
  show_momentum_overlay: boolean;
  height: number;
  width: number;
}

export interface TradeOverlay {
  entry_level: number;
  stop_loss_level: number;
  take_profit_level: number;
  position_type: 'long' | 'short';
  strategy_name: string;
  risk_amount: number;
  potential_reward: number;
}

// LumiSignals Strategy Types
export interface StrategySignal {
  strategy_id: string;
  strategy_name: string;
  strategy_type: 'PC' | 'QC' | 'DC'; // Penny, Quarter, Dime Curve
  signal_type: 'BUY' | 'SELL' | 'HOLD';
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  confidence: number;
  timeframe: string;
  risk_reward_ratio: number;
  psychological_level: number;
  momentum_alignment: boolean;
  signal_strength: 'WEAK' | 'MODERATE' | 'STRONG';
  created_at: string;
}

export interface TradingStrategy {
  id: string;
  name: string;
  type: 'PC' | 'QC' | 'DC';
  timeframe: string;
  status: 'ACTIVE' | 'PAUSED' | 'DISABLED';
  risk_per_trade: number;
  expected_trades_per_day: string;
  expected_rr_ratio: string;
  current_positions: number;
  total_trades: number;
  win_rate: number;
  profit_loss: number;
  last_signal: string;
}

export interface StrategyPerformance {
  strategy_id: string;
  daily_pnl: number;
  weekly_pnl: number;
  monthly_pnl: number;
  win_rate: number;
  avg_trade_duration: number;
  total_trades: number;
  active_trades: number;
  max_drawdown: number;
  sharpe_ratio: number;
}