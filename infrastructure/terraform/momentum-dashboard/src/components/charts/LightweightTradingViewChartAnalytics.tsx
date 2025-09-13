import React, { useEffect, useRef, useState } from 'react';
import { 
  createChart, 
  ColorType, 
  IChartApi, 
  ISeriesApi, 
  CandlestickData as TVCandlestickData,
  IPriceLine,
  ITimeScaleApi,
  Time
} from 'lightweight-charts';
import { TrendingUp, TrendingDown, AlertCircle, ArrowUp, ArrowDown, Activity, Zap } from 'lucide-react';
import { api } from '../../services/api';

interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface AnalyticsData {
  fibonacci?: {
    swingHigh: number;
    swingLow: number;
    levels: {
      level_0: number;
      level_236: number;
      level_382: number;
      level_500: number;
      level_618: number;
      level_786: number;
      level_1000: number;
    };
  };
  momentum?: {
    strength: number;
    direction: 'bullish' | 'bearish' | 'neutral';
    alignment: {
      M5: boolean;
      M15: boolean;
      H1: boolean;
      H4: boolean;
      D1: boolean;
    };
  };
  sentiment?: {
    current: 'bullish' | 'bearish' | 'neutral';
    pattern: string;
    levelBreach?: {
      type: 'support' | 'resistance';
      level: string;
      price: number;
    };
  };
  institutionalLevels?: Array<{
    price: number;
    type: 'penny' | 'quarter' | 'dime';
    label: string;
  }>;
  confluence?: {
    score: number;
    signals: string[];
    isPremiumSetup: boolean;
  };
}

interface LightweightTradingViewChartAnalyticsProps {
  currencyPair: string;
  timeframe?: string;
  height?: number;
  selectedAnalytics?: string[];
  sortRank?: number;
  onUserInteraction?: () => void;
  preserveZoom?: boolean;
}

interface InstitutionalLevel {
  price: number;
  type: 'penny' | 'quarter' | 'dime';
  label: string;
}

// Color schemes for analytics
const ANALYTICS_COLORS = {
  fibonacci: {
    0: '#FF0000',     // Red
    236: '#FF7F00',   // Orange
    382: '#FFFF00',   // Yellow
    500: '#00FF00',   // Green
    618: '#0000FF',   // Blue
    786: '#4B0082',   // Indigo
    1000: '#9400D3'   // Violet
  },
  momentum: {
    strong: '#00FF00',
    medium: '#FFFF00',
    weak: '#FF0000',
    neutral: '#808080'
  },
  sentiment: {
    bullish: '#00FF00',
    bearish: '#FF0000',
    neutral: '#808080'
  }
};

// Institutional level colors as specified
const INSTITUTIONAL_COLORS = {
  penny: '#FF69B4', // Pink
  quarter: '#00FF00', // Green  
  dime: '#0000FF'   // Blue
};

// Calculate institutional levels based on psychological price points
const calculateInstitutionalLevels = (currentPrice: number, isJPYPair: boolean): InstitutionalLevel[] => {
  const levels: InstitutionalLevel[] = [];
  
  if (!currentPrice || isNaN(currentPrice)) return levels;
  
  if (isJPYPair) {
    // JPY pairs (2 decimal places)
    
    // Dimes: X00.00 levels (every 10.00) - 2 above and below current price
    const currentDime = Math.round(currentPrice / 10) * 10;
    for (let i = -2; i <= 2; i++) {
      const price = currentDime + (i * 10);
      if (price > 0) {
        levels.push({
          price,
          type: 'dime',
          label: `${price.toFixed(2)}`
        });
      }
    }
    
    // Get dime range for quarters
    const minDime = currentDime - 20;
    const maxDime = currentDime + 20;
    
    // Quarters: XX2.50, XX5.00, XX7.50 levels (every 2.50) - all within dime range
    for (let price = Math.ceil(minDime / 2.5) * 2.5; price <= maxDime; price += 2.5) {
      if (price > 0 && price % 10 !== 0) { // Exclude dime levels
        levels.push({
          price,
          type: 'quarter',
          label: `${price.toFixed(2)}`
        });
      }
    }
    
    // Pennies: XX1.00, XX2.00 levels (every 1.00) - 2 above and below current price
    const currentPenny = Math.round(currentPrice);
    for (let i = -2; i <= 2; i++) {
      const price = currentPenny + i;
      if (price > 0 && price % 2.5 !== 0) { // Exclude quarter/dime levels
        levels.push({
          price,
          type: 'penny',
          label: `${price.toFixed(2)}`
        });
      }
    }
    
  } else {
    // Non-JPY pairs (4 decimal places)
    
    // Dimes: X.1000, X.2000 levels (every 0.1000) - 2 above and below current price
    const currentDime = Math.round(currentPrice * 10) / 10;
    for (let i = -2; i <= 2; i++) {
      const price = currentDime + (i * 0.1);
      if (price > 0) {
        levels.push({
          price,
          type: 'dime',
          label: `${price.toFixed(4)}`
        });
      }
    }
    
    // Get dime range for quarters
    const minDime = currentDime - 0.2;
    const maxDime = currentDime + 0.2;
    
    // Quarters: X.X250, X.X500, X.X750 levels (every 0.0250) - all within dime range
    for (let price = Math.ceil(minDime / 0.025) * 0.025; price <= maxDime; price += 0.025) {
      if (price > 0 && (price * 10) % 1 !== 0) { // Exclude dime levels
        levels.push({
          price: Math.round(price * 10000) / 10000, // Fix floating point precision
          type: 'quarter',
          label: `${price.toFixed(4)}`
        });
      }
    }
    
    // Pennies: X.XX10, X.XX20 levels (every 0.0100) - 2 above and below current price
    const currentPenny = Math.round(currentPrice * 100) / 100;
    for (let i = -2; i <= 2; i++) {
      const price = currentPenny + (i * 0.01);
      if (price > 0 && (price * 100) % 2.5 !== 0) { // Exclude quarter/dime levels
        levels.push({
          price: Math.round(price * 10000) / 10000, // Fix floating point precision
          type: 'penny',
          label: `${price.toFixed(4)}`
        });
      }
    }
  }
  
  return levels.sort((a, b) => a.price - b.price);
};

export const LightweightTradingViewChartAnalytics: React.FC<LightweightTradingViewChartAnalyticsProps> = ({
  currencyPair,
  timeframe = 'M5',
  height = 300,
  selectedAnalytics = [],
  sortRank,
  onUserInteraction,
  preserveZoom = false
}) => {
  console.log(`🚀 TradingViewChartAnalytics mounted for ${currencyPair}, analytics:`, selectedAnalytics);
  
  // Determine if this is a JPY pair for proper decimal formatting
  const isJPYPair = currencyPair.includes('JPY');
  const decimalPlaces = isJPYPair ? 3 : 5;
  
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const analyticsLinesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<any[]>([]);
  const currentTimeRangeRef = useRef<{ from: Time | null, to: Time | null }>({ from: null, to: null });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [hasUserInteracted, setHasUserInteracted] = useState(false);
  const [analyticsData, setAnalyticsData] = useState<AnalyticsData | null>(null);

  // Format price based on currency pair type
  const formatPrice = (price: number): string => {
    return isJPYPair ? price.toFixed(2) : price.toFixed(4);
  };

  // Clear all analytics overlays
  const clearAnalyticsOverlays = () => {
    if (candlestickSeriesRef.current) {
      analyticsLinesRef.current.forEach(line => {
        candlestickSeriesRef.current?.removePriceLine(line);
      });
      analyticsLinesRef.current = [];
    }
  };

  // Draw Fibonacci levels
  const drawFibonacciLevels = (fibData: AnalyticsData['fibonacci']) => {
    if (!fibData || !candlestickSeriesRef.current) return;

    const fibLevels = [
      { name: '0%', value: fibData.levels.level_0, color: ANALYTICS_COLORS.fibonacci[0] },
      { name: '23.6%', value: fibData.levels.level_236, color: ANALYTICS_COLORS.fibonacci[236] },
      { name: '38.2%', value: fibData.levels.level_382, color: ANALYTICS_COLORS.fibonacci[382] },
      { name: '50%', value: fibData.levels.level_500, color: ANALYTICS_COLORS.fibonacci[500] },
      { name: '61.8%', value: fibData.levels.level_618, color: ANALYTICS_COLORS.fibonacci[618] },
      { name: '78.6%', value: fibData.levels.level_786, color: ANALYTICS_COLORS.fibonacci[786] },
      { name: '100%', value: fibData.levels.level_1000, color: ANALYTICS_COLORS.fibonacci[1000] }
    ];

    fibLevels.forEach(level => {
      const priceLine = candlestickSeriesRef.current!.createPriceLine({
        price: level.value,
        color: level.color,
        lineWidth: 1,
        lineStyle: 2, // Dashed
        axisLabelVisible: true,
        title: `Fib ${level.name}`
      });
      analyticsLinesRef.current.push(priceLine);
    });
  };

  // Draw institutional levels
  const drawInstitutionalLevels = (levels: InstitutionalLevel[]) => {
    if (!candlestickSeriesRef.current) return;

    levels.forEach(level => {
      const priceLine = candlestickSeriesRef.current!.createPriceLine({
        price: level.price,
        color: INSTITUTIONAL_COLORS[level.type],
        lineWidth: level.type === 'dime' ? 3 : level.type === 'quarter' ? 2 : 1,
        lineStyle: 0, // Solid
        axisLabelVisible: true,
        title: level.label
      });
      analyticsLinesRef.current.push(priceLine);
    });
  };

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const isDarkMode = document.documentElement.classList.contains('dark');
    
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: isDarkMode ? '#1a1a1a' : '#ffffff' },
        textColor: isDarkMode ? '#d1d5db' : '#374151',
      },
      grid: {
        vertLines: { color: isDarkMode ? '#2a2a2a' : '#f3f4f6' },
        horzLines: { color: isDarkMode ? '#2a2a2a' : '#f3f4f6' },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          width: 1,
          color: isDarkMode ? '#4a4a4a' : '#9ca3af',
          style: 0,
        },
        horzLine: {
          width: 1,
          color: isDarkMode ? '#4a4a4a' : '#9ca3af',
          style: 0,
        },
      },
      rightPriceScale: {
        borderColor: isDarkMode ? '#2a2a2a' : '#e5e7eb',
        visible: true,
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
      },
      timeScale: {
        borderColor: isDarkMode ? '#2a2a2a' : '#e5e7eb',
        timeVisible: true,
        secondsVisible: true,
      },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
      priceFormat: {
        type: 'price',
        precision: isJPYPair ? 2 : 4,
        minMove: isJPYPair ? 0.01 : 0.0001,
      },
    });

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;

    // Add click handler for user interaction tracking
    chart.subscribeClick(() => {
      if (onUserInteraction && !hasUserInteracted) {
        setHasUserInteracted(true);
        onUserInteraction();
      }
    });

    // Subscribe to visible time range changes
    chart.timeScale().subscribeVisibleTimeRangeChange(() => {
      const timeScale = chart.timeScale();
      const range = timeScale.getVisibleRange();
      if (range) {
        currentTimeRangeRef.current = { from: range.from, to: range.to };
      }
    });

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // Fetch candlestick data
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch M5 candlestick data (200 candles for better analysis)
        const candleResponse = await api.getCandlestickData(currencyPair, timeframe, 200);
        
        if (candleResponse.success && candleResponse.data) {
          const chartData: TVCandlestickData[] = candleResponse.data.map((candle: CandlestickData) => ({
            time: (new Date(candle.time).getTime() / 1000) as Time,
            open: parseFloat(candle.open.toString()),
            high: parseFloat(candle.high.toString()),
            low: parseFloat(candle.low.toString()),
            close: parseFloat(candle.close.toString()),
          }));

          if (candlestickSeriesRef.current && chartData.length > 0) {
            candlestickSeriesRef.current.setData(chartData);
            
            // Set current price
            const latestCandle = chartData[chartData.length - 1];
            setCurrentPrice(latestCandle.close);

            // Auto-fit content if no user interaction
            if (chartRef.current && !preserveZoom) {
              chartRef.current.timeScale().fitContent();
            } else if (chartRef.current && preserveZoom && currentTimeRangeRef.current.from && currentTimeRangeRef.current.to) {
              // Restore previous zoom level
              chartRef.current.timeScale().setVisibleRange({
                from: currentTimeRangeRef.current.from,
                to: currentTimeRangeRef.current.to
              });
            }

            // TODO: Fetch analytics data from backend
            // For now, simulate with calculated institutional levels
            const levels = calculateInstitutionalLevels(latestCandle.close, isJPYPair);
            setAnalyticsData({
              institutionalLevels: levels,
              momentum: {
                strength: 0.75,
                direction: 'bullish',
                alignment: { M5: true, M15: true, H1: false, H4: false, D1: false }
              },
              sentiment: {
                current: 'bullish',
                pattern: 'Bullish Engulfing',
                levelBreach: undefined
              }
            });
          }
        } else {
          setError('Failed to load candlestick data');
        }
      } catch (err) {
        console.error('Error fetching data:', err);
        setError('Error loading chart data');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    
    // Refresh data every minute
    const interval = setInterval(fetchData, 60000);
    
    return () => clearInterval(interval);
  }, [currencyPair, timeframe, preserveZoom]);

  // Update analytics overlays when data or selection changes
  useEffect(() => {
    clearAnalyticsOverlays();

    if (!analyticsData || !candlestickSeriesRef.current) return;

    // Draw selected analytics
    if (selectedAnalytics.includes('fibonacci') && analyticsData.fibonacci) {
      drawFibonacciLevels(analyticsData.fibonacci);
    }

    if (selectedAnalytics.includes('levels') && analyticsData.institutionalLevels) {
      drawInstitutionalLevels(analyticsData.institutionalLevels);
    }

    // TODO: Add momentum and sentiment visual indicators
  }, [analyticsData, selectedAnalytics]);

  return (
    <div className="bg-gray-800 rounded-lg shadow-lg p-4 relative">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold text-white">
            {currencyPair.replace('_', '/')}
          </h3>
          {sortRank && (
            <span className="text-xs px-2 py-1 bg-gray-700 text-gray-300 rounded">
              #{sortRank}
            </span>
          )}
          <span className="text-xs text-gray-400">
            {timeframe} • {formatPrice(currentPrice || 0)}
          </span>
        </div>

        {/* Analytics Indicators */}
        <div className="flex items-center gap-2">
          {analyticsData?.momentum && selectedAnalytics.includes('momentum') && (
            <div className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
              analyticsData.momentum.direction === 'bullish' ? 'bg-green-900 text-green-300' :
              analyticsData.momentum.direction === 'bearish' ? 'bg-red-900 text-red-300' :
              'bg-gray-700 text-gray-300'
            }`}>
              <Activity className="w-3 h-3" />
              <span>{Math.round(analyticsData.momentum.strength * 100)}%</span>
            </div>
          )}
          
          {analyticsData?.sentiment && selectedAnalytics.includes('sentiment') && (
            <div className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
              analyticsData.sentiment.current === 'bullish' ? 'bg-green-900 text-green-300' :
              analyticsData.sentiment.current === 'bearish' ? 'bg-red-900 text-red-300' :
              'bg-gray-700 text-gray-300'
            }`}>
              {analyticsData.sentiment.current === 'bullish' ? <TrendingUp className="w-3 h-3" /> : 
               analyticsData.sentiment.current === 'bearish' ? <TrendingDown className="w-3 h-3" /> :
               <AlertCircle className="w-3 h-3" />}
              <span>{analyticsData.sentiment.pattern}</span>
            </div>
          )}

          {analyticsData?.confluence && analyticsData.confluence.isPremiumSetup && (
            <div className="flex items-center gap-1 px-2 py-1 bg-yellow-900 text-yellow-300 rounded text-xs">
              <Zap className="w-3 h-3" />
              <span>Premium Setup</span>
            </div>
          )}
        </div>
      </div>

      {/* Chart Container */}
      <div ref={chartContainerRef} className="relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-800 bg-opacity-75 z-10">
            <div className="text-white">Loading chart data...</div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-800 bg-opacity-75 z-10">
            <div className="text-red-400">{error}</div>
          </div>
        )}
      </div>

      {/* Momentum Alignment Indicator */}
      {analyticsData?.momentum && selectedAnalytics.includes('momentum') && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="text-gray-400">Timeframe Alignment:</span>
          <div className="flex gap-1">
            {Object.entries(analyticsData.momentum.alignment).map(([tf, aligned]) => (
              <div
                key={tf}
                className={`px-1.5 py-0.5 rounded ${
                  aligned ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-500'
                }`}
              >
                {tf}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default LightweightTradingViewChartAnalytics;