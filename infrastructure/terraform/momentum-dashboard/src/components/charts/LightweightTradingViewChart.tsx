import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, CandlestickData as TVCandlestickData } from 'lightweight-charts';
import { TrendingUp, TrendingDown, AlertCircle } from 'lucide-react';
import { api } from '../../services/api';

interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface LightweightTradingViewChartProps {
  currencyPair: string;
  timeframe?: string;
  height?: number;
}

export const LightweightTradingViewChart: React.FC<LightweightTradingViewChartProps> = ({
  currencyPair,
  timeframe = 'H1',
  height = 300
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  
  const [candlestickData, setCandlestickData] = useState<CandlestickData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [priceChange, setPriceChange] = useState<number | null>(null);

  // Clean up chart on unmount
  useEffect(() => {
    return () => {
      if (chartRef.current) {
        chartRef.current.remove();
      }
    };
  }, []);

  // Initialize chart when container is ready
  useEffect(() => {
    if (!chartContainerRef.current || loading || error) return;

    // Create chart with dark theme matching PipStop
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: '#1E1E1E' },
        textColor: '#B3B3B3',
      },
      grid: {
        vertLines: {
          color: '#333333',
          style: 1,
          visible: true,
        },
        horzLines: {
          color: '#333333',
          style: 1,
          visible: true,
        },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: '#8FC9CF',
          width: 1,
          style: 2,
          labelBackgroundColor: '#2C2C2C',
        },
        horzLine: {
          color: '#8FC9CF',
          width: 1,
          style: 2,
          labelBackgroundColor: '#2C2C2C',
        },
      },
      rightPriceScale: {
        borderColor: '#333333',
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
      },
      timeScale: {
        borderColor: '#333333',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Create candlestick series with PipStop colors
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#C7D9C5',
      downColor: '#C26A6A',
      borderUpColor: '#C7D9C5',
      borderDownColor: '#C26A6A',
      wickUpColor: '#C7D9C5',
      wickDownColor: '#C26A6A',
    });

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [height, loading, error]);

  // Update chart data when candlestick data changes
  useEffect(() => {
    if (!candlestickSeriesRef.current || candlestickData.length === 0) return;

    // Convert data to TradingView format
    const tvData: TVCandlestickData[] = candlestickData.map(candle => ({
      time: (new Date(candle.time).getTime() / 1000) as any, // Convert to Unix timestamp
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));

    candlestickSeriesRef.current.setData(tvData);

    // Update current price and price change
    if (candlestickData.length > 0) {
      const latest = candlestickData[candlestickData.length - 1];
      setCurrentPrice(latest.close);
      
      if (candlestickData.length > 1) {
        const previous = candlestickData[candlestickData.length - 2];
        const change = ((latest.close - previous.close) / previous.close) * 100;
        setPriceChange(change);
      }
    }

    // Fit content
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent();
    }
  }, [candlestickData]);

  // Fetch data with retry logic
  useEffect(() => {
    let mounted = true;
    
    const fetchCandlestickData = async (retryCount = 0) => {
      if (!mounted) return;
      
      try {
        setLoading(true);
        if (retryCount === 0) setError(null);

        // Add delay between API calls to avoid rate limiting
        if (retryCount > 0) {
          await new Promise(resolve => setTimeout(resolve, Math.min(1000 * retryCount, 5000)));
        }

        // Fetch 100 candlesticks from Redis via Lambda API
        console.log(`🎯 NEW TRADINGVIEW COMPONENT LOADING: ${currencyPair} with 100 candles`);
        const response = await api.getCandlestickData(currencyPair, timeframe, 100);
        
        if (!mounted) return;
        
        if (!response.success) {
          throw new Error(response.error || 'Failed to fetch data');
        }

        const data = response;
        
        if (data.success && data.data && Array.isArray(data.data) && data.data.length > 0) {
          // Convert Lambda response format to component format
          const formattedData = data.data.map((candle: any) => ({
            time: candle.datetime || candle.time,
            open: parseFloat(candle.open),
            high: parseFloat(candle.high),
            low: parseFloat(candle.low),
            close: parseFloat(candle.close),
            volume: candle.volume || 0
          })).filter(candle => 
            !isNaN(candle.open) && !isNaN(candle.high) && 
            !isNaN(candle.low) && !isNaN(candle.close)
          );
          
          if (formattedData.length > 0) {
            setCandlestickData(formattedData);
            setError(null);
          } else {
            throw new Error('No valid candlestick data');
          }
        } else {
          throw new Error(data.error || 'No candlestick data available');
        }
      } catch (err: any) {
        if (!mounted) return;
        
        console.error(`Error fetching candlestick data for ${currencyPair}:`, err);
        
        // Retry logic for common errors
        if (retryCount < 2 && (
          err.message?.includes('CORS') || 
          err.message?.includes('Network') || 
          err.message?.includes('500') ||
          err.message?.includes('Failed to fetch')
        )) {
          console.log(`Retrying ${currencyPair} (attempt ${retryCount + 1}/3)...`);
          fetchCandlestickData(retryCount + 1);
          return;
        }
        
        setError(`Failed to load data (${retryCount + 1} attempts)`);
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    // Add random delay to stagger API calls for different pairs
    const randomDelay = Math.random() * 2000;
    const delayedFetch = setTimeout(() => fetchCandlestickData(), randomDelay);
    
    // Refresh every 5 minutes with random offset
    const refreshInterval = (5 + Math.random() * 2) * 60 * 1000; // 5-7 minutes
    const interval = setInterval(() => fetchCandlestickData(), refreshInterval);
    
    return () => {
      mounted = false;
      clearTimeout(delayedFetch);
      clearInterval(interval);
    };
  }, [currencyPair, timeframe]);

  if (loading) {
    return (
      <div className="bg-gray-900 p-4 rounded-lg border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-white">{currencyPair.replace('_', '/')}</h3>
            <p className="text-sm text-gray-400">{timeframe} Timeframe</p>
          </div>
          <div className="animate-pulse">
            <div className="h-6 w-20 bg-gray-700 rounded"></div>
          </div>
        </div>
        <div className="flex items-center justify-center" style={{ height: `${height}px` }}>
          <div className="text-gray-500 text-sm">Loading chart...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-900 p-4 rounded-lg border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-white">{currencyPair.replace('_', '/')}</h3>
            <p className="text-sm text-gray-400">{timeframe} Timeframe</p>
          </div>
          <AlertCircle className="w-5 h-5 text-red-400" />
        </div>
        <div className="flex items-center justify-center" style={{ height: `${height}px` }}>
          <div className="text-red-400 text-sm text-center">
            <AlertCircle className="w-8 h-8 mx-auto mb-2" />
            {error}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 p-4 rounded-lg border border-gray-700 shadow-lg hover:shadow-xl transition-all duration-200">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-white">{currencyPair.replace('_', '/')}</h3>
          <p className="text-sm text-gray-400">{timeframe} • {candlestickData.length} candles</p>
        </div>
        <div className="text-right">
          {currentPrice && (
            <>
              <div className="text-lg font-semibold text-white">
                {currentPrice.toFixed(5)}
              </div>
              {priceChange !== null && (
                <div className={`flex items-center justify-end gap-1 text-sm ${priceChange >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {priceChange >= 0 ? (
                    <TrendingUp className="w-4 h-4" />
                  ) : (
                    <TrendingDown className="w-4 h-4" />
                  )}
                  <span>{priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}%</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      
      <div ref={chartContainerRef} style={{ height: `${height}px` }} />
      
      <div className="mt-2 text-xs text-gray-500 text-center">
        ⚡ NEW TradingView Component • Real-time data from Redis • 100 Candles • Powered by TradingView Lightweight Charts
      </div>
    </div>
  );
};

export default LightweightTradingViewChart;