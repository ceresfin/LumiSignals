import React, { useState, useEffect, useMemo } from 'react';
import { LightweightTradingViewChartAnalytics } from './LightweightTradingViewChartAnalytics';
import { api } from '../../services/api';
import { ChevronDown, Filter, TrendingUp, LineChart, BarChart3, Activity } from 'lucide-react';

// All 28 currency pairs from the LumiSignals trading system
const CURRENCY_PAIRS = [
  'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CHF', 'USD_CAD', 'AUD_USD', 'NZD_USD',
  'EUR_GBP', 'EUR_JPY', 'EUR_CHF', 'EUR_AUD', 'EUR_NZD', 'EUR_CAD',
  'GBP_JPY', 'GBP_CHF', 'GBP_AUD', 'GBP_NZD', 'GBP_CAD',
  'AUD_JPY', 'AUD_CHF', 'AUD_NZD', 'AUD_CAD',
  'NZD_JPY', 'NZD_CHF', 'NZD_CAD',
  'CAD_JPY', 'CAD_CHF',
  'CHF_JPY'
];

interface CurrencyPairGraphsAnalyticsProps {
  timeframe?: string;
  chartHeight?: number;
}

// Calculate distance to nearest institutional level
const calculateInstitutionalDistance = (price: number, isJPYPair: boolean): { type: 'dime' | 'quarter' | 'penny', distance: number } => {
  if (!price || isNaN(price)) return { type: 'penny', distance: Infinity };
  
  let distances = [];
  
  if (isJPYPair) {
    // JPY pairs
    const nearestDime = Math.round(price / 10) * 10;
    const nearestQuarter = Math.round(price / 2.5) * 2.5;
    const nearestPenny = Math.round(price);
    
    distances.push(
      { type: 'dime' as const, distance: Math.abs(price - nearestDime) },
      { type: 'quarter' as const, distance: Math.abs(price - nearestQuarter) },
      { type: 'penny' as const, distance: Math.abs(price - nearestPenny) }
    );
  } else {
    // Non-JPY pairs
    const nearestDime = Math.round(price * 10) / 10;
    const nearestQuarter = Math.round(price / 0.025) * 0.025;
    const nearestPenny = Math.round(price * 100) / 100;
    
    distances.push(
      { type: 'dime' as const, distance: Math.abs(price - nearestDime) },
      { type: 'quarter' as const, distance: Math.abs(price - nearestQuarter) },
      { type: 'penny' as const, distance: Math.abs(price - nearestPenny) }
    );
  }
  
  // Return the closest level type and distance
  return distances.reduce((min, curr) => curr.distance < min.distance ? curr : min);
};

export const CurrencyPairGraphsAnalytics: React.FC<CurrencyPairGraphsAnalyticsProps> = ({
  timeframe = 'M5', // Changed to M5 for 5-minute data
  chartHeight = 400
}) => {
  console.log(`🚀 ANALYTICS PARENT: Rendering at ${new Date().toISOString().split('T')[1].split('.')[0]}`);
  // Stable reference to prevent remounting - defined outside state to avoid recreating
  const defaultAnalytics = React.useMemo(() => ['fibonacci', 'momentum', 'sentiment', 'levels'], []);
  const [availableAnalytics, setAvailableAnalytics] = useState<string[]>(defaultAnalytics);
  const [selectedAnalytics, setSelectedAnalytics] = useState<string[]>(defaultAnalytics);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [currentPrices, setCurrentPrices] = useState<Record<string, number>>({});
  const [userInteractedCharts, setUserInteractedCharts] = useState<Set<string>>(new Set());
  const [preserveUserState, setPreserveUserState] = useState(true);
  const [sortedPairs, setSortedPairs] = useState<string[]>(CURRENCY_PAIRS);
  const [hasInitialSort, setHasInitialSort] = useState(true); // Start true to show charts immediately

  // Initialize available analytics
  useEffect(() => {
    setLoading(false);
  }, []);

  const toggleAnalytic = (analytic: string) => {
    setSelectedAnalytics(prev => {
      if (prev.includes(analytic)) {
        return prev.filter(a => a !== analytic);
      } else {
        return [...prev, analytic];
      }
    });
  };

  const selectAllAnalytics = () => {
    setSelectedAnalytics(availableAnalytics);
  };

  const clearAllAnalytics = () => {
    setSelectedAnalytics([]);
  };
  
  // TEMPORARILY DISABLED: Price fetching causes remounts due to failed API calls
  // This was causing Mount #2 and #3 when price fetches fail
  // Fetch current prices for all pairs (using M5 timeframe)
  // useEffect(() => {
  //   const fetchPrices = async () => {
  //     const prices: Record<string, number> = {};
      
  //     // Fetch candlestick data for each pair to get current price
  //     const pricePromises = CURRENCY_PAIRS.map(async (pair) => {
  //       try {
  //         console.log(`🔍 PRICE DEBUG: Starting 1-candle price fetch for ${pair} ${timeframe} at ${new Date().toISOString()}`);
  //         const response = await api.getCandlestickData(pair, timeframe, 1);
  //         console.log(`🔍 PRICE DEBUG: 1-candle price fetch completed for ${pair} - success: ${response.success}, candles: ${response.data?.length || 0}`);
  //         if (response.success && response.data && response.data.length > 0) {
  //           const latestCandle = response.data[response.data.length - 1];
  //           prices[pair] = parseFloat(latestCandle.close);
  //         }
  //       } catch (error) {
  //         console.error(`Failed to fetch price for ${pair}:`, error);
  //         // Don't update state on error to prevent remounts
  //       }
  //     });
      
  //     await Promise.all(pricePromises);
  //     setCurrentPrices(prices);
  //   };
    
  //   fetchPrices();
  //   // Removed 60-second refresh to prevent chart remounting
  // }, [timeframe]);
  
  // Perform sorting calculation
  const calculateSortedPairs = (prices: Record<string, number>) => {
    if (Object.keys(prices).length === 0) {
      return CURRENCY_PAIRS;
    }
    
    const pairsWithDistance = CURRENCY_PAIRS.map(pair => {
      const price = prices[pair];
      if (!price) {
        return { pair, type: 'penny' as const, distance: Infinity, hierarchyScore: 3 };
      }
      
      const isJPYPair = pair.includes('JPY');
      const { type, distance } = calculateInstitutionalDistance(price, isJPYPair);
      
      // Create hierarchy score: dime=1, quarter=2, penny=3
      const hierarchyScore = type === 'dime' ? 1 : type === 'quarter' ? 2 : 3;
      
      return { pair, type, distance, hierarchyScore };
    });
    
    // Sort by hierarchy first (dime < quarter < penny), then by distance
    const sorted = [...pairsWithDistance]
      .sort((a, b) => {
        if (a.hierarchyScore !== b.hierarchyScore) {
          return a.hierarchyScore - b.hierarchyScore;
        }
        return a.distance - b.distance;
      });
    
    return sorted.map(item => item.pair);
  };

  // TEMPORARILY DISABLED: Sorting to test if it's causing remounts
  // Do initial sort when prices are first loaded
  // useEffect(() => {
  //   if (Object.keys(currentPrices).length > 0) {
  //     const sorted = calculateSortedPairs(currentPrices);
  //     setSortedPairs(sorted);
  //   }
  // }, [currentPrices]);

  // Calculate rankings for display (based on current sorted order)
  const sortRankings = useMemo(() => {
    return new Map(sortedPairs.map((pair, index) => [pair, index + 1]));
  }, [sortedPairs]);
  
  // Handler for when user interacts with a chart - memoized to prevent remounting
  const handleChartInteraction = React.useCallback((currencyPair: string) => {
    setUserInteractedCharts(prev => new Set(prev).add(currencyPair));
  }, []);

  // TEMPORARILY DISABLED: Handler for manual re-sort
  const handleResort = () => {
    // const sorted = calculateSortedPairs(currentPrices);
    // setSortedPairs(sorted);
    // // Clear user interactions when resorting
    // setUserInteractedCharts(new Set());
    console.log('Sorting temporarily disabled for debugging');
  };

  // Debug parent renders
  console.log(`🔍 PARENT RENDER: CurrencyPairGraphsAnalytics at ${new Date().toISOString().split('T')[1].split('.')[0]}`);
  console.log(`🔍 PARENT STATE: selectedAnalytics=${selectedAnalytics.length}, sortedPairs=${sortedPairs.length}, loading=${loading}`);

  return (
    <div className="p-8">
      {/* Header with Analytics Selector */}
      <div className="mb-8">
        <div className="text-center mb-6">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
            Advanced Analytics Dashboard
          </h2>
          <p className="text-gray-600 dark:text-gray-300 mb-2">
            Real-time M5 candlestick data with advanced analytical overlays
          </p>
          <div className="flex items-center justify-center gap-4 text-sm text-gray-500 dark:text-gray-400">
            <span>📊 28 Currency Pairs</span>
            <span>•</span>
            <span>⏱️ M5 (5-minute) Timeframe</span>
            <span>•</span>
            <span>🔄 Auto-refresh every minute</span>
            <span>•</span>
            <span>📈 Backend Analytics Engine</span>
          </div>
        </div>

        {/* Analytics Selector Dropdown */}
        <div className="flex justify-center mb-6">
          <div className="relative">
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className="flex items-center gap-2 px-4 py-2 bg-gray-800 text-white rounded-lg hover:bg-gray-700 transition-colors"
              disabled={loading}
            >
              <Filter className="w-4 h-4" />
              <span>
                {loading ? 'Loading analytics...' : 
                 selectedAnalytics.length === 0 ? 'Select Analytics' :
                 selectedAnalytics.length === 1 ? selectedAnalytics[0] :
                 `${selectedAnalytics.length} analytics selected`}
              </span>
              <ChevronDown className={`w-4 h-4 transition-transform ${isDropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* Dropdown Menu */}
            {isDropdownOpen && !loading && (
              <div className="absolute top-full mt-2 left-0 right-0 min-w-[250px] bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50">
                <div className="p-2">
                  {/* Quick Actions */}
                  <div className="flex gap-2 mb-2 pb-2 border-b border-gray-700">
                    <button
                      onClick={selectAllAnalytics}
                      className="flex-1 text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors"
                    >
                      Select All
                    </button>
                    <button
                      onClick={clearAllAnalytics}
                      className="flex-1 text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors"
                    >
                      Clear All
                    </button>
                  </div>

                  {/* Analytics List */}
                  <div className="max-h-60 overflow-y-auto">
                    <label className="flex items-center gap-2 px-2 py-2 hover:bg-gray-700 rounded cursor-pointer transition-colors">
                      <input
                        type="checkbox"
                        checked={selectedAnalytics.includes('fibonacci')}
                        onChange={() => toggleAnalytic('fibonacci')}
                        className="w-4 h-4 text-blue-500 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                      />
                      <span className="text-white text-sm">📐 Fibonacci Levels</span>
                    </label>
                    <label className="flex items-center gap-2 px-2 py-2 hover:bg-gray-700 rounded cursor-pointer transition-colors">
                      <input
                        type="checkbox"
                        checked={selectedAnalytics.includes('momentum')}
                        onChange={() => toggleAnalytic('momentum')}
                        className="w-4 h-4 text-blue-500 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                      />
                      <span className="text-white text-sm">📈 Momentum Strength</span>
                    </label>
                    <label className="flex items-center gap-2 px-2 py-2 hover:bg-gray-700 rounded cursor-pointer transition-colors">
                      <input
                        type="checkbox"
                        checked={selectedAnalytics.includes('sentiment')}
                        onChange={() => toggleAnalytic('sentiment')}
                        className="w-4 h-4 text-blue-500 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                      />
                      <span className="text-white text-sm">💭 Candlestick Sentiment</span>
                    </label>
                    <label className="flex items-center gap-2 px-2 py-2 hover:bg-gray-700 rounded cursor-pointer transition-colors">
                      <input
                        type="checkbox"
                        checked={selectedAnalytics.includes('levels')}
                        onChange={() => toggleAnalytic('levels')}
                        className="w-4 h-4 text-blue-500 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                      />
                      <span className="text-white text-sm">🎯 Institutional Levels</span>
                    </label>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Legend */}
        {selectedAnalytics.length > 0 && (
          <div className="flex justify-center gap-6 text-sm flex-wrap">
            {selectedAnalytics.includes('fibonacci') && (
              <div className="flex items-center gap-2">
                <div className="w-4 h-1 bg-purple-500"></div>
                <span className="text-gray-600 dark:text-gray-400">Fibonacci Levels</span>
              </div>
            )}
            {selectedAnalytics.includes('momentum') && (
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-orange-500" />
                <span className="text-gray-600 dark:text-gray-400">Momentum Strength</span>
              </div>
            )}
            {selectedAnalytics.includes('sentiment') && (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded bg-gradient-to-r from-green-500 to-red-500"></div>
                <span className="text-gray-600 dark:text-gray-400">Sentiment Analysis</span>
              </div>
            )}
            {selectedAnalytics.includes('levels') && (
              <div className="flex items-center gap-2">
                <div className="flex gap-1">
                  <div className="w-2 h-2 rounded-full bg-blue-500"></div>
                  <div className="w-2 h-2 rounded-full bg-green-500"></div>
                  <div className="w-2 h-2 rounded-full bg-pink-500"></div>
                </div>
                <span className="text-gray-600 dark:text-gray-400">Institutional Levels</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Institutional Level Proximity Indicator and Resort Button */}
      {Object.keys(currentPrices).length > 0 && (
        <div className="mb-4 flex items-center justify-center gap-6">
          <span className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
            <span className="text-blue-500">●</span> Closest to Dimes
            <span className="mx-2">→</span>
            <span className="text-green-500">●</span> Closest to Quarters
            <span className="mx-2">→</span>
            <span className="text-pink-500">●</span> Closest to Pennies
          </span>
          <button
            onClick={handleResort}
            className="px-4 py-2 bg-gray-800 text-white text-sm rounded-lg hover:bg-gray-700 transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Re-sort Charts
          </button>
        </div>
      )}
      
      {/* Currency Pair Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {sortedPairs.map((pair) => (
            <LightweightTradingViewChartAnalytics
              key={`chart-${pair}`}
              currencyPair={pair}
              timeframe={timeframe}
              height={chartHeight}
              selectedAnalytics={selectedAnalytics}
              sortRank={sortRankings.get(pair)}
              onUserInteraction={handleChartInteraction}
              preserveZoom={preserveUserState && userInteractedCharts.has(pair)}
            />
        ))}
      </div>

      {/* Architecture Information */}
      <div className="mt-8 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
        <h3 className="text-lg font-semibold text-blue-900 dark:text-blue-100 mb-2">
          🎯 Advanced Analytics Architecture
        </h3>
        <p className="text-blue-800 dark:text-blue-200 text-sm">
          This analytics view leverages the lumisignals-trading-core Lambda layer for advanced market analysis:
        </p>
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
          <div className="text-sm text-blue-700 dark:text-blue-300">
            <strong>Analytics Pipeline:</strong>
            <span className="font-mono bg-blue-100 dark:bg-blue-800 px-2 py-1 rounded ml-2">
              Market Data → Lambda Layer → Analytics API → Charts
            </span>
          </div>
          <div className="text-sm text-blue-700 dark:text-blue-300">
            <strong>Core Modules:</strong>
            <span className="font-mono bg-blue-100 dark:bg-blue-800 px-2 py-1 rounded ml-2">
              Fibonacci, Momentum, Sentiment, Levels
            </span>
          </div>
        </div>
        <div className="mt-3 text-xs text-blue-600 dark:text-blue-400">
          <strong>Features:</strong> M5 timeframe analysis, four-pillar confluence detection, institutional level tracking, 
          real-time momentum strength, automated Fibonacci retracements, candlestick sentiment analysis
        </div>
      </div>
    </div>
  );
};

export default CurrencyPairGraphsAnalytics;