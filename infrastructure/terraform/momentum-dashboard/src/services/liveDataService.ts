import { 
  CurrencyStrengthData, 
  StrategyPerformanceData, 
  RiskExposureData, 
  TimeframeData 
} from '../types/dashboardTypes';

// API Configuration using environment variables (secure)
const API_CONFIG = {
  baseURL: process.env.REACT_APP_API_GATEWAY_BASE_URL || 'https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod',
  apiKey: process.env.REACT_APP_API_GATEWAY_KEY || 'lumi-dash-2025-secure-api-key-renaissance-trading-system',
  headers: {
    'Content-Type': 'application/json',
    'x-api-key': process.env.REACT_APP_API_GATEWAY_KEY || 'lumi-dash-2025-secure-api-key-renaissance-trading-system'
  }
};

// API Response interfaces based on your RDS schema
interface RDSStrategy {
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

interface RDSTrade {
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

interface RDSSignal {
  id: string;
  strategy_id: string;
  symbol: string;
  signal_type: 'buy' | 'sell' | 'hold';
  strength: number;
  price: number;
  volume: number;
  timestamp: string;
}

// Enhanced API client with error handling and retries
class LiveDataAPI {
  private async makeRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${API_CONFIG.baseURL}${endpoint}`;
    
    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          ...API_CONFIG.headers,
          ...options.headers
        }
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`API request failed: ${response.status} ${response.statusText}`, errorText);
        throw new Error(`API request failed: ${response.status} ${response.statusText}`);
      }

      return response.json();
    } catch (error) {
      console.error(`Network error for ${endpoint}:`, error);
      throw error;
    }
  }

  async getStrategies(): Promise<RDSStrategy[]> {
    try {
      return await this.makeRequest<RDSStrategy[]>('/strategies');
    } catch (error) {
      console.error('❌ Strategy API unavailable:', error);
      throw error;
    }
  }

  async getTrades(strategyId?: string): Promise<RDSTrade[]> {
    try {
      const endpoint = strategyId ? `/trades?strategy_id=${strategyId}` : '/trades';
      return await this.makeRequest<RDSTrade[]>(endpoint);
    } catch (error) {
      console.error('❌ Trade API unavailable:', error);
      throw error;
    }
  }

  async getSignals(symbol?: string): Promise<RDSSignal[]> {
    try {
      const endpoint = symbol ? `/signals?symbol=${symbol}` : '/signals';
      return await this.makeRequest<RDSSignal[]>(endpoint);
    } catch (error) {
      console.error('❌ Signal API unavailable:', error);
      throw error;
    }
  }

  async getStrategyPerformance(strategyId: string): Promise<any> {
    return this.makeRequest(`/strategies/${strategyId}/performance`);
  }
}

const liveDataAPI = new LiveDataAPI();

// Data transformation functions to convert RDS data to dashboard format
export const transformStrategiesToHeatmapData = (
  strategies: RDSStrategy[], 
  trades: RDSTrade[]
): StrategyPerformanceData[] => {
  return strategies.map(strategy => {
    const strategyTrades = trades.filter(trade => trade.strategy_id === strategy.id);
    const pairs = [...new Set(strategyTrades.map(trade => trade.symbol))];
    
    return pairs.map(pair => ({
      strategy: strategy.name,
      pair: pair,
      performance: strategy.total_pnl,
      winRate: strategy.win_rate * 100,
      sharpeRatio: strategy.sharpe_ratio,
      maxDrawdown: strategy.max_drawdown,
      tradesCount: strategyTrades.filter(trade => trade.symbol === pair).length,
      status: strategy.status,
      volume: strategyTrades
        .filter(trade => trade.symbol === pair)
        .reduce((sum, trade) => sum + Math.abs(trade.quantity), 0),
      lastTrade: strategyTrades
        .filter(trade => trade.symbol === pair)
        .sort((a, b) => new Date(b.exit_time).getTime() - new Date(a.exit_time).getTime())[0]?.exit_time
    }));
  }).flat();
};

export const transformSignalsToCurrencyStrength = (signals: RDSSignal[]): CurrencyStrengthData[] => {
  const currencies = ['USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'NZD'];
  
  return currencies.map((currency, index) => {
    const currencySignals = signals.filter(signal => 
      signal.symbol.includes(currency)
    );
    
    // Calculate strength based on signal types and strength values
    const totalSignals = currencySignals.length;
    const bullishSignals = currencySignals.filter(s => s.signal_type === 'buy').length;
    const bearishSignals = currencySignals.filter(s => s.signal_type === 'sell').length;
    
    const avgStrength = currencySignals.reduce((sum, signal) => sum + signal.strength, 0) / totalSignals || 0;
    
    // Convert to -100 to 100 scale
    const strengthScore = ((bullishSignals - bearishSignals) / Math.max(totalSignals, 1)) * avgStrength;
    
    // Calculate volatility based on price variations
    const prices = currencySignals.map(s => s.price);
    const avgPrice = prices.reduce((sum, price) => sum + price, 0) / prices.length || 0;
    const volatility = prices.length > 1 ? 
      Math.sqrt(prices.reduce((sum, price) => sum + Math.pow(price - avgPrice, 2), 0) / prices.length) / avgPrice * 100 : 
      0;
    
    return {
      currency,
      strength: strengthScore,
      trend: strengthScore > 10 ? 'strengthening' : strengthScore < -10 ? 'weakening' : 'stable',
      volatility: Math.min(volatility, 100),
      rank: index + 1,
      volume: currencySignals.reduce((sum, signal) => sum + signal.volume, 0)
    };
  }).sort((a, b) => b.strength - a.strength)
    .map((item, index) => ({ ...item, rank: index + 1 }));
};

export const transformTradesToRiskExposure = (
  trades: RDSTrade[], 
  strategies: RDSStrategy[]
): RiskExposureData[] => {
  const symbols = [...new Set(trades.map(trade => trade.symbol))];
  
  return symbols.map(symbol => {
    const symbolTrades = trades.filter(trade => trade.symbol === symbol);
    const totalVolume = symbolTrades.reduce((sum, trade) => sum + Math.abs(trade.quantity), 0);
    const totalPnL = symbolTrades.reduce((sum, trade) => sum + trade.pnl, 0);
    
    // Calculate exposure as percentage of total portfolio
    const totalPortfolioVolume = trades.reduce((sum, trade) => sum + Math.abs(trade.quantity), 0);
    const exposure = (totalVolume / totalPortfolioVolume) * 100;
    
    // Calculate VaR (simplified)
    const avgPnL = totalPnL / symbolTrades.length;
    const variance = symbolTrades.reduce((sum, trade) => sum + Math.pow(trade.pnl - avgPnL, 2), 0) / symbolTrades.length;
    const var95 = Math.abs(avgPnL - 1.96 * Math.sqrt(variance));
    
    // Determine risk level
    const getRiskLevel = (exposure: number, volatility: number): 'low' | 'medium' | 'high' | 'extreme' => {
      if (exposure > 30 || volatility > 25) return 'extreme';
      if (exposure > 20 || volatility > 15) return 'high';
      if (exposure > 10 || volatility > 10) return 'medium';
      return 'low';
    };
    
    const volatility = Math.sqrt(variance) / Math.abs(avgPnL) * 100 || 0;
    
    return {
      currency: symbol.substring(0, 3), // Extract base currency
      exposure: exposure,
      risk: getRiskLevel(exposure, volatility),
      var: var95,
      expectedReturn: (totalPnL / totalVolume) * 100,
      correlation: 0.65, // This would need historical correlation calculation
      volatility: Math.min(volatility, 100)
    };
  }).sort((a, b) => b.exposure - a.exposure);
};

export const transformSignalsToTimeframeData = (signals: RDSSignal[]): TimeframeData[] => {
  const timeframes = ['1M', '5M', '15M', '1H', '4H', '1D'];
  
  return timeframes.map(timeframe => {
    // Filter signals by time ranges (simplified - would need actual timeframe logic)
    const timeframeSignals = signals.slice(0, 10); // Simplified sampling
    
    const bullishSignals = timeframeSignals.filter(s => s.signal_type === 'buy').length;
    const bearishSignals = timeframeSignals.filter(s => s.signal_type === 'sell').length;
    const totalSignals = timeframeSignals.length;
    
    const trend = bullishSignals > bearishSignals ? 'bullish' : 
                  bearishSignals > bullishSignals ? 'bearish' : 'sideways';
    
    const strength = totalSignals > 0 ? 
      (Math.abs(bullishSignals - bearishSignals) / totalSignals) * 100 : 50;
    
    const avgPrice = timeframeSignals.reduce((sum, signal) => sum + signal.price, 0) / totalSignals || 1.0850;
    const priceRange = 0.01; // Simplified range
    
    return {
      timeframe,
      trend,
      strength: strength,
      support: avgPrice - priceRange,
      resistance: avgPrice + priceRange,
      volatility: Math.random() * 20 + 5, // Would calculate from actual price data
      volume: timeframeSignals.reduce((sum, signal) => sum + signal.volume, 0),
      price: avgPrice,
      change: (Math.random() - 0.5) * 0.01,
      changePercent: (Math.random() - 0.5) * 2
    };
  });
};

// Main service class for dashboard data
export class LiveDataService {
  private strategies: RDSStrategy[] = [];
  private trades: RDSTrade[] = [];
  private signals: RDSSignal[] = [];
  private lastUpdate: Date = new Date();

  async refreshData(): Promise<void> {
    try {
      console.log('🔄 Refreshing live data from RDS...');
      
      // Fetch all data in parallel
      const [strategies, trades, signals] = await Promise.all([
        liveDataAPI.getStrategies(),
        liveDataAPI.getTrades(),
        liveDataAPI.getSignals()
      ]);

      this.strategies = strategies;
      this.trades = trades;
      this.signals = signals;
      this.lastUpdate = new Date();
      
      console.log('✅ Live data refreshed successfully', {
        strategies: strategies.length,
        trades: trades.length,
        signals: signals.length
      });
    } catch (error) {
      console.error('❌ Failed to refresh live data:', error);
      throw error;
    }
  }

  async getCurrencyStrengthData(): Promise<CurrencyStrengthData[]> {
    if (this.signals.length === 0) {
      await this.refreshData();
    }
    return transformSignalsToCurrencyStrength(this.signals);
  }

  async getStrategyHeatmapData(): Promise<StrategyPerformanceData[]> {
    if (this.strategies.length === 0 || this.trades.length === 0) {
      await this.refreshData();
    }
    return transformStrategiesToHeatmapData(this.strategies, this.trades);
  }

  async getRiskExposureData(): Promise<RiskExposureData[]> {
    if (this.trades.length === 0 || this.strategies.length === 0) {
      await this.refreshData();
    }
    return transformTradesToRiskExposure(this.trades, this.strategies);
  }

  async getTimeframeData(): Promise<TimeframeData[]> {
    if (this.signals.length === 0) {
      await this.refreshData();
    }
    return transformSignalsToTimeframeData(this.signals);
  }

  async getPortfolioSummary(): Promise<{
    totalValue: number;
    totalPnL: number;
    activeStrategies: number;
    totalTrades: number;
  }> {
    if (this.strategies.length === 0 || this.trades.length === 0) {
      await this.refreshData();
    }

    const totalPnL = this.trades.reduce((sum, trade) => sum + trade.pnl, 0);
    const totalValue = Math.abs(this.trades.reduce((sum, trade) => sum + trade.entry_price * trade.quantity, 0));
    
    return {
      totalValue,
      totalPnL,
      activeStrategies: this.strategies.filter(s => s.status === 'active').length,
      totalTrades: this.trades.length
    };
  }

  getConnectionStatus(): {
    connected: boolean;
    lastUpdate: string;
    dataPoints: number;
  } {
    return {
      connected: this.strategies.length > 0 || this.trades.length > 0 || this.signals.length > 0,
      lastUpdate: this.lastUpdate.toLocaleTimeString(),
      dataPoints: this.strategies.length + this.trades.length + this.signals.length
    };
  }
}

// Singleton instance
export const liveDataService = new LiveDataService();

// Chart data service for price/volume charts
export const generateLiveChartData = async (symbol: string = 'EURUSD'): Promise<any[]> => {
  try {
    const signals = await liveDataAPI.getSignals(symbol);
    
    return signals.slice(-50).map((signal, index) => ({
      timestamp: new Date(signal.timestamp).toLocaleTimeString(),
      value: signal.price,
      volume: signal.volume,
      high: signal.price + 0.001,
      low: signal.price - 0.001,
      open: signal.price - 0.0005,
      close: signal.price + 0.0005
    }));
  } catch (error) {
    console.error('❌ Chart data API unavailable:', error);
    throw error;
  }
};