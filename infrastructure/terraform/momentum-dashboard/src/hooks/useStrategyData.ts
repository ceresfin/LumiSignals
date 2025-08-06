// LumiSignals Strategy Data Hook - Connects to 10 Active Lambda Strategies
import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { TradingStrategy, StrategySignal, StrategyPerformance } from '../types/momentum';

interface UseStrategyDataReturn {
  strategies: TradingStrategy[];
  signals: StrategySignal[];
  performance: StrategyPerformance[];
  loading: boolean;
  error: string | null;
  connected: boolean;
  lastUpdated: string | null;
  refreshData: () => Promise<void>;
}



export function useStrategyData(): UseStrategyDataReturn {
  const [strategies, setStrategies] = useState<TradingStrategy[]>([]);
  const [signals, setSignals] = useState<StrategySignal[]>([]);
  const [performance, setPerformance] = useState<StrategyPerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchStrategyData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Try to fetch from real API first
      console.log('🔄 Fetching strategy data from Lambda APIs...');
      
      const [strategiesResponse, signalsResponse, performanceResponse] = await Promise.all([
        api.getStrategies(),
        api.getStrategySignals(),
        api.getStrategyPerformance()
      ]);

      if (strategiesResponse.success) {
        console.log('✅ Successfully fetched strategy data from Lambda');
        setStrategies(strategiesResponse.data);
        setConnected(true);
      } else {
        throw new Error('Strategy API not available');
      }

      if (signalsResponse.success) {
        setSignals(signalsResponse.data);
      }

      if (performanceResponse.success) {
        setPerformance(performanceResponse.data);
      }

      setLastUpdated(new Date().toISOString());
    } catch (err) {
      console.error('❌ Strategy APIs not available:', err);
      setError('Unable to fetch strategy data. Please check API connection.');
      setStrategies([]);
      setSignals([]);
      setPerformance([]);
      setConnected(false);
      setLastUpdated(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshData = useCallback(async () => {
    await fetchStrategyData();
  }, [fetchStrategyData]);

  useEffect(() => {
    fetchStrategyData();
    
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchStrategyData, 30000);
    return () => clearInterval(interval);
  }, [fetchStrategyData]);

  return {
    strategies,
    signals,
    performance,
    loading,
    error,
    connected,
    lastUpdated,
    refreshData
  };
}