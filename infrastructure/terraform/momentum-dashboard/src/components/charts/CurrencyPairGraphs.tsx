import React from 'react';
import { CandlestickChart } from './CandlestickChart';

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

interface CurrencyPairGraphsProps {
  timeframe?: string;
  chartHeight?: number;
}

export const CurrencyPairGraphs: React.FC<CurrencyPairGraphsProps> = ({
  timeframe = 'H1',
  chartHeight = 160
}) => {
  return (
    <div className="p-8">
      <div className="mb-8 text-center">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
          Currency Pair Candlestick Charts
        </h2>
        <p className="text-gray-600 dark:text-gray-300 mb-2">
          Real-time candlestick data from Fargate → Redis architecture
        </p>
        <div className="flex items-center justify-center gap-4 text-sm text-gray-500 dark:text-gray-400">
          <span>📊 28 Currency Pairs</span>
          <span>•</span>
          <span>⏱️ {timeframe} Timeframe</span>
          <span>•</span>
          <span>🔄 Auto-refresh every 5 minutes</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {CURRENCY_PAIRS.map((pair) => (
          <CandlestickChart
            key={pair}
            currencyPair={pair}
            timeframe={timeframe}
            height={chartHeight}
          />
        ))}
      </div>

      <div className="mt-8 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
        <h3 className="text-lg font-semibold text-blue-900 dark:text-blue-100 mb-2">
          🏗️ Architecture Verification
        </h3>
        <p className="text-blue-800 dark:text-blue-200 text-sm">
          This section verifies the complete data flow: 
          <span className="font-mono bg-blue-100 dark:bg-blue-800 px-2 py-1 rounded mx-1">
            OANDA API → Fargate Data Orchestrator → Redis Cache → Lambda API → Dashboard
          </span>
        </p>
        <div className="mt-3 text-xs text-blue-700 dark:text-blue-300">
          <strong>Data Sources:</strong> Real-time candlestick data collected by Fargate every 5 minutes and cached in Redis for fast access
        </div>
      </div>
    </div>
  );
};

export default CurrencyPairGraphs;