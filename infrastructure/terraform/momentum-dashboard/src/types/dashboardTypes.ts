// Dashboard data type definitions for live data integration

export interface CurrencyStrengthData {
  currency: string;
  strength: number; // -100 to 100
  trend: 'strengthening' | 'weakening' | 'stable';
  volatility: number;
  rank: number;
  previousStrength?: number;
  volume?: number;
}

export interface StrategyPerformanceData {
  strategy: string;
  pair: string;
  performance: number; // Percentage return
  winRate: number;
  sharpeRatio: number;
  maxDrawdown: number;
  tradesCount: number;
  status: 'active' | 'paused' | 'stopped';
  volume?: number;
  lastTrade?: string;
}

export interface RiskExposureData {
  currency: string;
  exposure: number; // Percentage of portfolio
  risk: 'low' | 'medium' | 'high' | 'extreme';
  var: number; // Value at Risk
  expectedReturn: number;
  correlation: number;
  volatility?: number;
  lastUpdated?: string;
}

export interface TimeframeData {
  timeframe: string;
  trend: 'bullish' | 'bearish' | 'sideways';
  strength: number; // 0-100
  support: number;
  resistance: number;
  volatility: number;
  volume: number;
  price?: number;
  change?: number;
  changePercent?: number;
  lastUpdated?: string;
}

export interface ChartData {
  timestamp: string;
  value: number;
  volume?: number;
  high?: number;
  low?: number;
  open?: number;
  close?: number;
}

export interface DashboardState {
  selectedTimeframe: string;
  selectedMetric: 'performance' | 'winRate' | 'sharpeRatio' | 'maxDrawdown';
  autoRefresh: boolean;
  refreshInterval: number;
  expandedPanel: string | null;
}

export interface ConnectionStatus {
  connected: boolean;
  lastUpdate: string;
  latency?: number;
  reconnectAttempts?: number;
  dataPoints?: number;
}

export interface PortfolioSummary {
  totalValue: number;
  totalPnL: number;
  activeStrategies: number;
  totalTrades: number;
  riskUtilization?: number;
  avgReturn?: number;
}

// API Response types for RDS integration
export interface RDSStrategy {
  id: string;
  name: string;
  status: 'active' | 'paused' | 'stopped';
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  max_drawdown: number;
  sharpe_ratio: number;
  created_at: string;
  updated_at: string;
}

export interface RDSTrade {
  id: string;
  strategy_id: string;
  symbol: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  entry_time: string;
  exit_time: string;
  trade_type: 'buy' | 'sell';
}

export interface RDSSignal {
  id: string;
  strategy_id: string;
  symbol: string;
  signal_type: 'buy' | 'sell' | 'hold';
  strength: number;
  price: number;
  volume: number;
  timestamp: string;
}

// Custom hooks return types
export interface UseLiveDataReturn {
  currencyData: CurrencyStrengthData[];
  strategyData: StrategyPerformanceData[];
  riskData: RiskExposureData[];
  timeframeData: TimeframeData[];
  chartData: ChartData[];
  portfolioSummary: PortfolioSummary;
  connectionStatus: ConnectionStatus;
  loading: boolean;
  error: string | null;
  refreshData: () => Promise<void>;
}

// Error types for better error handling
export interface APIError {
  message: string;
  status: number;
  endpoint: string;
  timestamp: Date;
}

// Transformation function types
export type CurrencyStrengthTransformer = (signals: RDSSignal[]) => CurrencyStrengthData[];
export type StrategyHeatmapTransformer = (strategies: RDSStrategy[], trades: RDSTrade[]) => StrategyPerformanceData[];
export type RiskExposureTransformer = (trades: RDSTrade[], strategies: RDSStrategy[]) => RiskExposureData[];
export type TimeframeDataTransformer = (signals: RDSSignal[]) => TimeframeData[];

// WebSocket event types for real-time updates
export interface WebSocketEvent {
  type: 'trade' | 'signal' | 'strategy_update' | 'connection_status';
  data: any;
  timestamp: string;
}

// Dashboard configuration types
export interface DashboardConfig {
  refreshInterval: number;
  maxDataPoints: number;
  autoRefresh: boolean;
  enableWebSocket: boolean;
  apiEndpoint: string;
  apiKey: string;
  theme: 'light' | 'dark' | 'system';
}

// Utility types for component props
export interface BaseComponentProps {
  className?: string;
  theme?: 'light' | 'dark';
  loading?: boolean;
  error?: string | null;
}

export interface InteractiveComponentProps extends BaseComponentProps {
  interactive?: boolean;
  onItemClick?: (item: any) => void;
  onItemHover?: (item: any) => void;
}

export interface TooltipProps {
  visible: boolean;
  position: { x: number; y: number };
  data: any;
  theme: any;
}

// Data validation types
export interface DataValidation {
  isValid: boolean;
  errors: string[];
  warnings: string[];
}

// Real-time data subscription types
export interface DataSubscription {
  type: 'currency' | 'strategy' | 'risk' | 'timeframe' | 'chart';
  callback: (data: any) => void;
  filter?: any;
  interval?: number;
}

// Export utility type for components that need all data
export interface AllDashboardData {
  currencies: CurrencyStrengthData[];
  strategies: StrategyPerformanceData[];
  risks: RiskExposureData[];
  timeframes: TimeframeData[];
  charts: ChartData[];
  portfolio: PortfolioSummary;
  connection: ConnectionStatus;
}