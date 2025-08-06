import React, { useEffect, useState } from 'react';
import { BarChart3, TrendingUp, TrendingDown } from 'lucide-react';
import { api } from '../../services/api';

interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface CandlestickChartProps {
  currencyPair: string;
  timeframe?: string;
  height?: number;
}

export const CandlestickChart: React.FC<CandlestickChartProps> = ({
  currencyPair,
  timeframe = 'H1',
  height = 200
}) => {
  const [candlestickData, setCandlestickData] = useState<CandlestickData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchCandlestickData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch candlestick data from Redis via Lambda API using the api service (Updated 2025-08-05)
        const response = await api.getCandlestickData(currencyPair, timeframe, 50);
        
        if (!response.success) {
          throw new Error(response.error || 'Failed to fetch data');
        }

        const data = response;
        
        if (data.success && data.data) {
          // Convert Lambda response format to component format
          const formattedData = data.data.map((candle: any) => ({
            time: candle.datetime || candle.time,
            open: parseFloat(candle.open),
            high: parseFloat(candle.high),
            low: parseFloat(candle.low),
            close: parseFloat(candle.close),
            volume: candle.volume || 0
          }));
          setCandlestickData(formattedData);
        } else {
          setError(data.error || 'No candlestick data available');
        }
      } catch (err) {
        console.error('Error fetching candlestick data:', err);
        setError('Failed to load candlestick data');
      } finally {
        setLoading(false);
      }
    };

    fetchCandlestickData();
    
    // Refresh every 5 minutes
    const interval = setInterval(fetchCandlestickData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [currencyPair, timeframe]);

  const renderSimpleCandlesticks = () => {
    if (candlestickData.length === 0) return null;

    const maxPrice = Math.max(...candlestickData.map(d => d.high));
    const minPrice = Math.min(...candlestickData.map(d => d.low));
    const priceRange = maxPrice - minPrice;
    
    return (
      <div className="flex items-end justify-between h-full px-1">
        {candlestickData.slice(-20).map((candle, index) => {
          const isGreen = candle.close > candle.open;
          const bodyHeight = Math.abs(candle.close - candle.open) / priceRange * height * 0.8;
          const wickTop = (maxPrice - candle.high) / priceRange * height * 0.8;
          const wickBottom = (candle.low - minPrice) / priceRange * height * 0.8;
          
          return (
            <div key={index} className="flex flex-col items-center justify-end" style={{ height: '100%' }}>
              {/* Upper wick */}
              <div 
                className="w-0.5 bg-gray-400"
                style={{ height: `${wickTop}px` }}
              />
              
              {/* Candle body */}
              <div 
                className={`w-2 ${isGreen ? 'bg-green-500' : 'bg-red-500'}`}
                style={{ height: `${Math.max(bodyHeight, 1)}px` }}
              />
              
              {/* Lower wick */}
              <div 
                className="w-0.5 bg-gray-400"
                style={{ height: `${wickBottom}px` }}
              />
            </div>
          );
        })}
      </div>
    );
  };

  const getCurrentPrice = () => {
    if (candlestickData.length === 0) return null;
    const latest = candlestickData[candlestickData.length - 1];
    const previous = candlestickData[candlestickData.length - 2];
    const isUp = previous && latest.close > previous.close;
    
    return (
      <div className="flex items-center gap-1 text-xs">
        {isUp ? (
          <TrendingUp className="w-3 h-3 text-green-500" />
        ) : (
          <TrendingDown className="w-3 h-3 text-red-500" />
        )}
        <span className={`font-medium ${isUp ? 'text-green-600' : 'text-red-600'}`}>
          {latest.close.toFixed(5)}
        </span>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-gray-900 dark:text-white">
            {currencyPair}
          </h3>
          <BarChart3 className="w-4 h-4 text-gray-400 animate-pulse" />
        </div>
        <div className="flex items-center justify-center" style={{ height: `${height}px` }}>
          <div className="animate-pulse text-gray-500 dark:text-gray-400 text-xs">
            Loading chart...
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-gray-900 dark:text-white">
            {currencyPair}
          </h3>
          <BarChart3 className="w-4 h-4 text-red-400" />
        </div>
        <div className="flex items-center justify-center" style={{ height: `${height}px` }}>
          <div className="text-red-500 dark:text-red-400 text-xs text-center">
            {error}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-gray-900 dark:text-white">
          {currencyPair}
        </h3>
        {getCurrentPrice()}
      </div>
      
      <div style={{ height: `${height}px` }} className="relative">
        {renderSimpleCandlesticks()}
      </div>
      
      <div className="mt-2 text-xs text-gray-500 dark:text-gray-400 text-center">
        {timeframe} • {candlestickData.length} candles • Real-time data
      </div>
    </div>
  );
};

export default CandlestickChart;