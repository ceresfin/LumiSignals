import React, { useState, useEffect } from 'react';
import { LightweightTradingViewChartWithTrades } from './LightweightTradingViewChartWithTrades';
import { api } from '../../services/api';
import { ChevronDown, Filter, TrendingUp, Target, Shield } from 'lucide-react';

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

interface CurrencyPairGraphsWithTradesProps {
  timeframe?: string;
  chartHeight?: number;
}

export const CurrencyPairGraphsWithTrades: React.FC<CurrencyPairGraphsWithTradesProps> = ({
  timeframe = 'H1',
  chartHeight = 400
}) => {
  const [availableStrategies, setAvailableStrategies] = useState<string[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  // Fetch available strategies from active trades
  useEffect(() => {
    const fetchStrategies = async () => {
      try {
        setLoading(true);
        const response = await api.getActiveTradesFromRDS();
        
        console.log('📊 Raw strategy response:', response);
        if (response.success && response.data) {
          console.log('📊 Response data:', response.data);
          // Extract unique strategies from active trades
          const strategies = [...new Set(response.data.map((trade: any) => {
            console.log('🎯 Trade object:', trade);
            return trade.strategy_name || trade.strategy || trade.Strategy || trade.STRATEGY;
          }))];
          console.log('📊 Extracted strategies:', strategies);
          setAvailableStrategies(strategies.filter(s => s)); // Remove empty/null strategies
        } else {
          console.log('❌ Strategy fetch failed:', response);
        }
      } catch (error) {
        console.error('Failed to fetch strategies:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchStrategies();
    
    // Refresh strategies every minute
    const interval = setInterval(fetchStrategies, 60000);
    
    return () => clearInterval(interval);
  }, []);

  const toggleStrategy = (strategy: string) => {
    setSelectedStrategies(prev => {
      if (prev.includes(strategy)) {
        return prev.filter(s => s !== strategy);
      } else {
        return [...prev, strategy];
      }
    });
  };

  const selectAllStrategies = () => {
    setSelectedStrategies(availableStrategies);
  };

  const clearAllStrategies = () => {
    setSelectedStrategies([]);
  };

  return (
    <div className="p-8">
      {/* Header with Strategy Selector */}
      <div className="mb-8">
        <div className="text-center mb-6">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
            Currency Pair Candlestick Charts with Active Trades
          </h2>
          <p className="text-gray-600 dark:text-gray-300 mb-2">
            Real-time candlestick data with trade overlay visualization
          </p>
          <div className="flex items-center justify-center gap-4 text-sm text-gray-500 dark:text-gray-400">
            <span>📊 28 Currency Pairs</span>
            <span>•</span>
            <span>⏱️ {timeframe} Timeframe</span>
            <span>•</span>
            <span>🔄 Auto-refresh every 5 minutes</span>
            <span>•</span>
            <span>📈 100 Candlesticks per chart</span>
          </div>
        </div>

        {/* Strategy Selector Dropdown */}
        <div className="flex justify-center mb-6">
          <div className="relative">
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className="flex items-center gap-2 px-4 py-2 bg-gray-800 text-white rounded-lg hover:bg-gray-700 transition-colors"
              disabled={loading}
            >
              <Filter className="w-4 h-4" />
              <span>
                {loading ? 'Loading strategies...' : 
                 selectedStrategies.length === 0 ? 'Select Strategies' :
                 selectedStrategies.length === 1 ? selectedStrategies[0] :
                 `${selectedStrategies.length} strategies selected`}
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
                      onClick={selectAllStrategies}
                      className="flex-1 text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors"
                    >
                      Select All
                    </button>
                    <button
                      onClick={clearAllStrategies}
                      className="flex-1 text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors"
                    >
                      Clear All
                    </button>
                  </div>

                  {/* Strategy List */}
                  {availableStrategies.length > 0 ? (
                    <div className="max-h-60 overflow-y-auto">
                      {availableStrategies.map(strategy => (
                        <label
                          key={strategy}
                          className="flex items-center gap-2 px-2 py-2 hover:bg-gray-700 rounded cursor-pointer transition-colors"
                        >
                          <input
                            type="checkbox"
                            checked={selectedStrategies.includes(strategy)}
                            onChange={() => toggleStrategy(strategy)}
                            className="w-4 h-4 text-blue-500 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                          />
                          <span className="text-white text-sm">{strategy}</span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <div className="text-gray-400 text-sm text-center py-4">
                      No active strategies found
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Legend */}
        {selectedStrategies.length > 0 && (
          <div className="flex justify-center gap-6 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-1 bg-blue-500"></div>
              <span className="text-gray-600 dark:text-gray-400">Entry Price</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-1 bg-green-500"></div>
              <span className="text-gray-600 dark:text-gray-400">Target Price</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-1 bg-red-500"></div>
              <span className="text-gray-600 dark:text-gray-400">Stop Loss</span>
            </div>
            <div className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-gray-600 dark:text-gray-400" />
              <span className="text-gray-600 dark:text-gray-400">Direction</span>
            </div>
          </div>
        )}
      </div>

      {/* Currency Pair Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {CURRENCY_PAIRS.map((pair) => (
          <LightweightTradingViewChartWithTrades
            key={pair}
            currencyPair={pair}
            timeframe={timeframe}
            height={chartHeight}
            selectedStrategies={selectedStrategies}
          />
        ))}
      </div>

      {/* Architecture Information */}
      <div className="mt-8 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
        <h3 className="text-lg font-semibold text-blue-900 dark:text-blue-100 mb-2">
          🏗️ Enhanced Trading View Architecture
        </h3>
        <p className="text-blue-800 dark:text-blue-200 text-sm">
          This enhanced view combines real-time candlestick data with active trade overlays:
        </p>
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
          <div className="text-sm text-blue-700 dark:text-blue-300">
            <strong>Data Flow:</strong>
            <span className="font-mono bg-blue-100 dark:bg-blue-800 px-2 py-1 rounded ml-2">
              OANDA → Fargate → Redis → Lambda → Dashboard
            </span>
          </div>
          <div className="text-sm text-blue-700 dark:text-blue-300">
            <strong>Trade Data:</strong>
            <span className="font-mono bg-blue-100 dark:bg-blue-800 px-2 py-1 rounded ml-2">
              RDS PostgreSQL → Lambda API → Charts
            </span>
          </div>
        </div>
        <div className="mt-3 text-xs text-blue-600 dark:text-blue-400">
          <strong>Features:</strong> Strategy filtering, multi-trade overlay support, real-time P&L tracking, 
          entry/target/stop visualization, directional indicators
        </div>
      </div>
    </div>
  );
};

export default CurrencyPairGraphsWithTrades;