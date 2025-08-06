import { useState, useEffect, useCallback, useRef } from 'react';
import { liveDataService, generateLiveChartData } from '../services/liveDataService';
import { 
  CurrencyStrengthData, 
  StrategyPerformanceData, 
  RiskExposureData, 
  TimeframeData,
  ChartData,
  PortfolioSummary,
  ConnectionStatus,
  UseLiveDataReturn,
  APIError
} from '../types/dashboardTypes';

interface UseLiveDataOptions {
  autoRefresh?: boolean;
  refreshInterval?: number;
  enableWebSocket?: boolean;
  onError?: (error: APIError) => void;
  onDataUpdate?: (data: any) => void;
}

export const useLiveData = (options: UseLiveDataOptions = {}): UseLiveDataReturn => {
  const {
    autoRefresh = true,
    refreshInterval = 30000, // 30 seconds
    enableWebSocket = false,
    onError,
    onDataUpdate
  } = options;

  // State management
  const [currencyData, setCurrencyData] = useState<CurrencyStrengthData[]>([]);
  const [strategyData, setStrategyData] = useState<StrategyPerformanceData[]>([]);
  const [riskData, setRiskData] = useState<RiskExposureData[]>([]);
  const [timeframeData, setTimeframeData] = useState<TimeframeData[]>([]);
  const [chartData, setChartData] = useState<ChartData[]>([]);
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary>({
    totalValue: 0,
    totalPnL: 0,
    activeStrategies: 0,
    totalTrades: 0
  });
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    connected: false,
    lastUpdate: '',
    dataPoints: 0
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Refs for cleanup
  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isInitializedRef = useRef(false);

  // Error handling utility
  const handleError = useCallback((err: Error, endpoint: string) => {
    const apiError: APIError = {
      message: err.message,
      status: 0,
      endpoint,
      timestamp: new Date()
    };

    setError(err.message);
    onError?.(apiError);
    
    console.error(`❌ Live data error (${endpoint}):`, err);
  }, [onError]);

  // Data refresh function
  const refreshData = useCallback(async () => {
    if (loading) return; // Prevent concurrent refreshes
    
    setLoading(true);
    setError(null);

    try {
      console.log('🔄 Refreshing all dashboard data...');
      
      // Fetch all data concurrently
      const [
        currencies,
        strategies,
        risks,
        timeframes,
        charts,
        portfolio
      ] = await Promise.all([
        liveDataService.getCurrencyStrengthData().catch(err => {
          handleError(err, '/currencies');
          return [];
        }),
        liveDataService.getStrategyHeatmapData().catch(err => {
          handleError(err, '/strategies');
          return [];
        }),
        liveDataService.getRiskExposureData().catch(err => {
          handleError(err, '/risks');
          return [];
        }),
        liveDataService.getTimeframeData().catch(err => {
          handleError(err, '/timeframes');
          return [];
        }),
        generateLiveChartData('EURUSD').catch(err => {
          handleError(err, '/charts');
          return [];
        }),
        liveDataService.getPortfolioSummary().catch(err => {
          handleError(err, '/portfolio');
          return {
            totalValue: 0,
            totalPnL: 0,
            activeStrategies: 0,
            totalTrades: 0
          };
        })
      ]);

      // Update state
      setCurrencyData(currencies);
      setStrategyData(strategies);
      setRiskData(risks);
      setTimeframeData(timeframes);
      setChartData(charts);
      setPortfolioSummary(portfolio);

      // Update connection status
      const status = liveDataService.getConnectionStatus();
      setConnectionStatus(status);

      // Success callback
      const allData = {
        currencies,
        strategies,
        risks,
        timeframes,
        charts,
        portfolio,
        connection: status
      };
      onDataUpdate?.(allData);

      console.log('✅ All dashboard data refreshed successfully', {
        currencies: currencies.length,
        strategies: strategies.length,
        risks: risks.length,
        timeframes: timeframes.length,
        charts: charts.length,
        connected: status.connected
      });

    } catch (err) {
      handleError(err as Error, '/refresh');
    } finally {
      setLoading(false);
    }
  }, [loading, handleError, onDataUpdate]);

  // Initial data load
  useEffect(() => {
    if (!isInitializedRef.current) {
      isInitializedRef.current = true;
      console.log('🚀 Initializing live data connection...');
      refreshData();
    }
  }, [refreshData]);

  // Auto-refresh setup
  useEffect(() => {
    if (autoRefresh && refreshInterval > 0) {
      console.log(`⏰ Setting up auto-refresh every ${refreshInterval}ms`);
      
      refreshTimerRef.current = setInterval(() => {
        console.log('⏰ Auto-refresh triggered');
        refreshData();
      }, refreshInterval);

      return () => {
        if (refreshTimerRef.current) {
          clearInterval(refreshTimerRef.current);
          refreshTimerRef.current = null;
        }
      };
    }
  }, [autoRefresh, refreshInterval, refreshData]);

  // WebSocket connection (placeholder for future implementation)
  useEffect(() => {
    if (enableWebSocket) {
      console.log('🔌 WebSocket connection would be established here');
      // TODO: Implement WebSocket connection for real-time updates
    }
  }, [enableWebSocket]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, []);

  // Return interface
  return {
    currencyData,
    strategyData,
    riskData,
    timeframeData,
    chartData,
    portfolioSummary,
    connectionStatus,
    loading,
    error,
    refreshData
  };
};

// Specialized hooks for individual data types
export const useCurrencyStrengthData = (options: UseLiveDataOptions = {}) => {
  const [data, setData] = useState<CurrencyStrengthData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshData = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const currencies = await liveDataService.getCurrencyStrengthData();
      setData(currencies);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  return { data, loading, error, refreshData };
};

export const useStrategyHeatmapData = (options: UseLiveDataOptions = {}) => {
  const [data, setData] = useState<StrategyPerformanceData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshData = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const strategies = await liveDataService.getStrategyHeatmapData();
      setData(strategies);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  return { data, loading, error, refreshData };
};

export const useRiskExposureData = (options: UseLiveDataOptions = {}) => {
  const [data, setData] = useState<RiskExposureData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshData = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const risks = await liveDataService.getRiskExposureData();
      setData(risks);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  return { data, loading, error, refreshData };
};

// Connection health monitoring hook
export const useConnectionHealth = () => {
  const [status, setStatus] = useState<ConnectionStatus>({
    connected: false,
    lastUpdate: '',
    dataPoints: 0
  });

  const checkConnection = useCallback(() => {
    const connectionStatus = liveDataService.getConnectionStatus();
    setStatus(connectionStatus);
  }, []);

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, 5000); // Check every 5 seconds
    return () => clearInterval(interval);
  }, [checkConnection]);

  return status;
};

// Error recovery hook
export const useDataRecovery = () => {
  const [retryCount, setRetryCount] = useState(0);
  const [isRecovering, setIsRecovering] = useState(false);

  const attemptRecovery = useCallback(async () => {
    if (isRecovering) return;
    
    setIsRecovering(true);
    setRetryCount(prev => prev + 1);

    try {
      await liveDataService.refreshData();
      setRetryCount(0);
    } catch (err) {
      console.error('Recovery attempt failed:', err);
    } finally {
      setIsRecovering(false);
    }
  }, [isRecovering]);

  return { retryCount, isRecovering, attemptRecovery };
};