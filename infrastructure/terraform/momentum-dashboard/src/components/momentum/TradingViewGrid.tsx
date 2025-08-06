// TradingView Grid - 28 Currency Pairs in 3-column layout
import React, { useState } from 'react';
import TradingViewWidget from '../charts/TradingViewWidget';
import { RefreshCw, Grid3x3, BarChart3, Filter } from 'lucide-react';

interface TradingViewGridProps {
  columns?: number;
  showFilters?: boolean;
  autoRefresh?: boolean;
}

// All 28 currency pairs as specified
const CURRENCY_PAIRS = [
  // Majors
  'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'USD/CAD', 'AUD/USD', 'NZD/USD',
  // EUR crosses
  'EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD', 'EUR/NZD', 'EUR/CAD',
  // GBP crosses
  'GBP/JPY', 'GBP/CHF', 'GBP/AUD', 'GBP/NZD', 'GBP/CAD',
  // AUD crosses
  'AUD/JPY', 'AUD/CHF', 'AUD/NZD', 'AUD/CAD',
  // NZD crosses
  'NZD/JPY', 'NZD/CHF', 'NZD/CAD',
  // CAD crosses
  'CAD/JPY', 'CAD/CHF',
  // Final cross
  'CHF/JPY'
];

const TradingViewGrid: React.FC<TradingViewGridProps> = ({
  columns = 3,
  showFilters = true,
  autoRefresh = true
}) => {
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('D');
  const [showMajorOnly, setShowMajorOnly] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  // Filter pairs based on major pairs filter
  const displayPairs = showMajorOnly 
    ? CURRENCY_PAIRS.slice(0, 7) // First 7 are major pairs
    : CURRENCY_PAIRS;

  const handleRefresh = () => {
    setRefreshKey(prev => prev + 1);
  };

  const isMajorPair = (pair: string) => {
    const majors = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'USD/CAD', 'AUD/USD', 'NZD/USD'];
    return majors.includes(pair);
  };

  return (
    <div className="space-y-6">
      {/* Header and Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <h2 className="text-2xl font-bold text-white">
            TradingView Charts
          </h2>
          <div className="flex items-center space-x-2 text-sm text-gray-400">
            <BarChart3 className="w-4 h-4" />
            <span>{displayPairs.length} currency pairs</span>
          </div>
        </div>
        
        <div className="flex items-center space-x-3">
          {/* Timeframe Selector */}
          <select 
            value={selectedTimeframe}
            onChange={(e) => setSelectedTimeframe(e.target.value)}
            className="px-3 py-1 rounded border text-sm"
            style={{
              background: 'rgba(30, 30, 30, 0.8)',
              borderColor: '#2C2C2C',
              color: '#F7F2E6'
            }}
          >
            <option value="1">1 min</option>
            <option value="5">5 min</option>
            <option value="15">15 min</option>
            <option value="60">1 hour</option>
            <option value="240">4 hour</option>
            <option value="D">Daily</option>
            <option value="W">Weekly</option>
          </select>

          <button
            onClick={handleRefresh}
            className="p-2 bg-gray-700 text-white rounded hover:bg-gray-600 transition-colors"
            title="Refresh Charts"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Filters */}
      {showFilters && (
        <div className="flex items-center space-x-4">
          <Filter className="w-4 h-4 text-gray-400" />
          <label className="flex items-center space-x-2 text-sm text-gray-400">
            <input
              type="checkbox"
              checked={showMajorOnly}
              onChange={(e) => setShowMajorOnly(e.target.checked)}
              className="rounded"
            />
            <span>Show major pairs only (7 pairs)</span>
          </label>
        </div>
      )}

      {/* TradingView Charts Grid */}
      <div 
        className="grid gap-4"
        style={{
          gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`
        }}
      >
        {displayPairs.map((pair, index) => (
          <div
            key={`${pair}-${refreshKey}`}
            className="p-4 rounded-lg border"
            style={{
              background: 'rgba(30, 30, 30, 0.8)',
              borderColor: '#2C2C2C'
            }}
          >
            {/* Pair Header */}
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center space-x-2">
                <h3 className="font-bold text-sm" style={{ color: '#F7F2E6' }}>
                  {pair}
                </h3>
                {isMajorPair(pair) && (
                  <span className="px-2 py-1 rounded text-xs" style={{
                    background: 'rgba(162, 200, 161, 0.2)',
                    color: '#A2C8A1'
                  }}>
                    MAJOR
                  </span>
                )}
              </div>
              <div className="text-xs" style={{ color: '#B6E6C4' }}>
                {selectedTimeframe === 'D' ? 'Daily' : 
                 selectedTimeframe === 'W' ? 'Weekly' :
                 selectedTimeframe === '240' ? '4H' :
                 selectedTimeframe === '60' ? '1H' :
                 selectedTimeframe === '15' ? '15M' :
                 selectedTimeframe === '5' ? '5M' : '1M'}
              </div>
            </div>
            
            {/* TradingView Chart */}
            <div className="w-full">
              <TradingViewWidget
                pair={pair}
                width={380}
                height={280}
                interval={selectedTimeframe}
                theme="dark"
                style="1"
                toolbar_bg="#1E1E1E"
                enable_publishing={false}
                allow_symbol_change={false}
                container_id={`tradingview_${pair.replace('/', '_')}_${index}`}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Summary Footer */}
      <div className="flex items-center justify-between text-sm" style={{ color: '#B6E6C4' }}>
        <div className="flex items-center space-x-4">
          <span>Displaying {displayPairs.length} of {CURRENCY_PAIRS.length} pairs</span>
          <span>•</span>
          <span>Timeframe: {
            selectedTimeframe === 'D' ? 'Daily' : 
            selectedTimeframe === 'W' ? 'Weekly' :
            selectedTimeframe === '240' ? '4 Hour' :
            selectedTimeframe === '60' ? '1 Hour' :
            selectedTimeframe === '15' ? '15 Minute' :
            selectedTimeframe === '5' ? '5 Minute' : '1 Minute'
          }</span>
        </div>
        <div>
          Charts powered by TradingView
        </div>
      </div>
    </div>
  );
};

export default TradingViewGrid;