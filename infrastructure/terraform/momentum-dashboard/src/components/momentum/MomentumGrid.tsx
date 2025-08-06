// Dynamic 28-pair momentum grid - strongest pairs rise to top-left
import React, { useState, useMemo } from 'react';
import { useMomentumRanking } from '../../hooks/useMomentumRanking';
import { PairCard } from './PairCard';
import { TradingViewChart } from '../charts/TradingViewChart';
import { CurrencyStrengthMatrix } from './CurrencyStrengthMatrix';
import TradingViewGrid from './TradingViewGrid';
import { TradeGrid } from '../trades/TradeGrid';
import { CurrencyPair, MomentumSignal } from '../../types/momentum';
import { RefreshCw, Filter, TrendingUp, TrendingDown, Minus, Grid3x3, BarChart3, BarChart2, Activity } from 'lucide-react';

interface MomentumGridProps {
  columns?: number;
  showFilters?: boolean;
  autoRefresh?: boolean;
}

export const MomentumGrid: React.FC<MomentumGridProps> = ({
  columns = 7,
  showFilters = true,
  autoRefresh = true
}) => {
  const { rankedPairs, loading, error, connected, lastUpdated, refreshRanking, filterBySignal } = useMomentumRanking();
  const [selectedPair, setSelectedPair] = useState<CurrencyPair | null>(null);
  const [signalFilter, setSignalFilter] = useState<string>('');
  const [showMajorOnly, setShowMajorOnly] = useState(false);
  const [viewMode, setViewMode] = useState<'grid' | 'matrix' | 'charts' | 'trades'>('trades');

  // Filter and display pairs
  const displayPairs = useMemo(() => {
    let filtered = rankedPairs;
    
    // Apply signal filter
    if (signalFilter) {
      filtered = filterBySignal(signalFilter);
    }
    
    // Apply major pairs filter
    if (showMajorOnly) {
      filtered = filtered.filter(pair => pair.is_major);
    }
    
    return filtered;
  }, [rankedPairs, signalFilter, showMajorOnly, filterBySignal]);

  // Signal counts for filter buttons
  const signalCounts = useMemo(() => {
    const counts = {
      'STRONG_BULLISH': 0,
      'WEAK_BULLISH': 0,
      'NEUTRAL': 0,
      'WEAK_BEARISH': 0,
      'STRONG_BEARISH': 0
    };
    
    rankedPairs.forEach(pair => {
      counts[pair.momentum.signal]++;
    });
    
    return counts;
  }, [rankedPairs]);

  const handlePairClick = (pair: CurrencyPair) => {
    setSelectedPair(pair);
  };

  const handleCloseModal = () => {
    setSelectedPair(null);
  };

  const getSignalIcon = (signal: string) => {
    if (signal.includes('BULLISH')) return <TrendingUp className="w-4 h-4" />;
    if (signal.includes('BEARISH')) return <TrendingDown className="w-4 h-4" />;
    return <Minus className="w-4 h-4" />;
  };

  const getSignalColor = (signal: string) => {
    if (signal.includes('STRONG') && signal.includes('BULLISH')) return 'bg-green-600 hover:bg-green-500';
    if (signal.includes('WEAK') && signal.includes('BULLISH')) return 'bg-green-500 hover:bg-green-400';
    if (signal.includes('NEUTRAL')) return 'bg-gray-500 hover:bg-gray-400';
    if (signal.includes('WEAK') && signal.includes('BEARISH')) return 'bg-red-500 hover:bg-red-400';
    if (signal.includes('STRONG') && signal.includes('BEARISH')) return 'bg-red-600 hover:bg-red-500';
    return 'bg-gray-500 hover:bg-gray-400';
  };

  if (loading && rankedPairs.length === 0) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-blue-500" />
          <p className="text-gray-400">Loading momentum analysis...</p>
        </div>
      </div>
    );
  }

  if (error && rankedPairs.length === 0) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <p className="text-red-400 mb-4">Error: {error}</p>
          <button
            onClick={refreshRanking}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-500 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 bg-gray-50 dark:bg-gray-900 min-h-screen">
      {/* Enhanced Header and Controls */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <div>
            <h2 className="text-3xl font-bold text-gray-900 dark:text-white">
              Momentum Grid
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
              Real-time momentum analysis of all 28 currency pairs
            </p>
          </div>
          
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
            <div className={`w-2 h-2 rounded-full animate-pulse ${
              connected ? 'bg-green-500' : 'bg-red-500'
            }`} />
            <span className={`text-sm font-medium ${
              connected ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
            }`}>
              {connected ? 'Live Data' : 'Offline'}
            </span>
            {lastUpdated && (
              <>
                <span className="text-gray-600 dark:text-gray-300">•</span>
                <span className="text-sm text-gray-600 dark:text-gray-300">
                  Updated {new Date(lastUpdated).toLocaleTimeString()}
                </span>
              </>
            )}
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Enhanced View Toggle */}
          <div className="flex items-center bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-1 gap-1">
            <button
              onClick={() => setViewMode('trades')}
              className={`px-3 py-2 rounded-md transition-all duration-200 flex items-center gap-2 text-sm font-medium ${
                viewMode === 'trades' 
                  ? 'bg-blue-600 text-white shadow-lg' 
                  : 'text-gray-600 dark:text-gray-300 hover:text-blue-600 hover:bg-gray-50 dark:hover:bg-gray-700'
              }`}
              title="Enhanced Trade Cards"
            >
              <Activity className="w-4 h-4" />
              <span className="hidden sm:block">Trades</span>
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`px-3 py-2 rounded-md transition-all duration-200 flex items-center gap-2 text-sm font-medium ${
                viewMode === 'grid' 
                  ? 'bg-blue-600 text-white shadow-lg' 
                  : 'text-gray-600 dark:text-gray-300 hover:text-blue-600 hover:bg-gray-50 dark:hover:bg-gray-700'
              }`}
              title="Grid View"
            >
              <Grid3x3 className="w-4 h-4" />
              <span className="hidden sm:block">Grid</span>
            </button>
            <button
              onClick={() => setViewMode('matrix')}
              className={`px-3 py-2 rounded-md transition-all duration-200 flex items-center gap-2 text-sm font-medium ${
                viewMode === 'matrix' 
                  ? 'bg-pipstop-primary text-white shadow-lg' 
                  : 'text-text-secondary-light dark:text-text-secondary-dark hover:text-pipstop-primary hover:bg-surface-light dark:hover:bg-surface-dark'
              }`}
              title="Strength Matrix"
            >
              <BarChart3 className="w-4 h-4" />
              <span className="hidden sm:block">Matrix</span>
            </button>
            <button
              onClick={() => setViewMode('charts')}
              className={`px-3 py-2 rounded-md transition-all duration-200 flex items-center gap-2 text-sm font-medium ${
                viewMode === 'charts' 
                  ? 'bg-pipstop-primary text-white shadow-lg' 
                  : 'text-text-secondary-light dark:text-text-secondary-dark hover:text-pipstop-primary hover:bg-surface-light dark:hover:bg-surface-dark'
              }`}
              title="TradingView Charts"
            >
              <BarChart2 className="w-4 h-4" />
              <span className="hidden sm:block">Charts</span>
            </button>
          </div>
          
          <button
            onClick={refreshRanking}
            disabled={loading}
            className="p-3 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark text-text-primary-light dark:text-text-primary-dark rounded-lg hover:bg-pipstop-primary hover:text-white hover:border-pipstop-primary transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
            title="Refresh Rankings"
          >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Enhanced Filter Section */}
      {showFilters && (viewMode === 'grid' || viewMode === 'charts') && (
        <div className="bg-elevated-light dark:bg-elevated-dark rounded-xl p-4 space-y-4">
          {/* Signal Filters */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-pipstop-primary" />
              <span className="text-sm font-medium text-text-primary-light dark:text-text-primary-dark">Filter by Signal Strength</span>
            </div>
            
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={() => setSignalFilter('')}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 flex items-center gap-2 ${
                  signalFilter === '' 
                    ? 'bg-pipstop-primary text-white shadow-lg' 
                    : 'bg-surface-light dark:bg-surface-dark text-text-secondary-light dark:text-text-secondary-dark hover:bg-pipstop-primary/10 hover:text-pipstop-primary border border-border-light dark:border-border-dark'
                }`}
              >
                <span>All Pairs</span>
                <span className="px-2 py-0.5 rounded-full bg-black/20 text-xs font-bold">
                  {rankedPairs.length}
                </span>
              </button>
              
              {Object.entries(signalCounts).map(([signal, count]) => {
                const isActive = signalFilter === signal;
                const getButtonStyling = () => {
                  if (isActive) {
                    switch (signal) {
                      case 'STRONG_BULLISH':
                        return 'bg-pipstop-success text-green-900 shadow-lg';
                      case 'WEAK_BULLISH':
                        return 'bg-pipstop-success/70 text-green-800 shadow-lg';
                      case 'NEUTRAL':
                        return 'bg-text-muted-light dark:bg-text-muted-dark text-text-primary-light dark:text-text-primary-dark shadow-lg';
                      case 'WEAK_BEARISH':
                        return 'bg-pipstop-danger/70 text-red-800 shadow-lg';
                      case 'STRONG_BEARISH':
                        return 'bg-pipstop-danger text-red-900 shadow-lg';
                      default:
                        return 'bg-pipstop-primary text-white shadow-lg';
                    }
                  } else {
                    return 'bg-surface-light dark:bg-surface-dark text-text-secondary-light dark:text-text-secondary-dark hover:bg-pipstop-primary/10 hover:text-pipstop-primary border border-border-light dark:border-border-dark';
                  }
                };
                
                return (
                  <button
                    key={signal}
                    onClick={() => setSignalFilter(signal === signalFilter ? '' : signal)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 flex items-center gap-2 ${getButtonStyling()}`}
                  >
                    {getSignalIcon(signal)}
                    <span className="capitalize">{signal.replace('_', ' ').toLowerCase()}</span>
                    <span className="px-2 py-0.5 rounded-full bg-black/20 text-xs font-bold">
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          
          {/* Additional Filters */}
          <div className="flex items-center justify-between pt-3 border-t border-border-light dark:border-border-dark">
            <label className="flex items-center gap-3 text-sm font-medium text-text-primary-light dark:text-text-primary-dark cursor-pointer">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={showMajorOnly}
                  onChange={(e) => setShowMajorOnly(e.target.checked)}
                  className="sr-only"
                />
                <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all duration-200 ${
                  showMajorOnly 
                    ? 'bg-pipstop-primary border-pipstop-primary' 
                    : 'border-border-light dark:border-border-dark hover:border-pipstop-primary'
                }`}>
                  {showMajorOnly && (
                    <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                </div>
              </div>
              <span>Show Major Pairs Only</span>
              <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">(EUR, GBP, USD, JPY, CHF, CAD, AUD, NZD)</span>
            </label>
            
            <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
              Showing <span className="font-semibold text-pipstop-primary">{displayPairs.length}</span> of {rankedPairs.length} pairs
            </div>
          </div>
        </div>
      )}

      {/* Content Area - Trades, Grid, Matrix, or Charts */}
      {viewMode === 'trades' ? (
        <TradeGrid
          showFilters={false}
          autoRefresh={autoRefresh}
        />
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-6">
          {displayPairs.map((pair) => (
            <PairCard
              key={pair.pair}
              pair={pair}
              onClick={handlePairClick}
              compact={false}
            />
          ))}
        </div>
      ) : viewMode === 'matrix' ? (
        <CurrencyStrengthMatrix
          showTimeframes={true}
          autoRefresh={autoRefresh}
          onPairSelect={(pair) => {
            // Convert pair format from "USD/EUR" to "USD_EUR" and find matching pair
            const formattedPair = pair.replace('/', '_');
            const matchingPair = rankedPairs.find(p => p.pair === formattedPair);
            if (matchingPair) {
              setSelectedPair(matchingPair);
            }
          }}
        />
      ) : (
        <TradingViewGrid
          columns={3}
          showFilters={false}
          autoRefresh={autoRefresh}
        />
      )}

      {/* Empty State - only for grid view */}
      {viewMode === 'grid' && displayPairs.length === 0 && !loading && (
        <div className="text-center py-12">
          <p className="text-gray-400">No pairs match the current filters</p>
          <button
            onClick={() => {
              setSignalFilter('');
              setShowMajorOnly(false);
            }}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-500 transition-colors"
          >
            Clear Filters
          </button>
        </div>
      )}

      {/* Detailed Chart Modal */}
      {selectedPair && (
        <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 rounded-lg max-w-6xl w-full max-h-[90vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-gray-700">
              <div className="flex items-center space-x-4">
                <h3 className="text-xl font-bold text-white">
                  {selectedPair.display_name}
                </h3>
                <div className="flex items-center space-x-2">
                  <span className="text-sm text-gray-400">Rank #{selectedPair.momentum.rank}</span>
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    selectedPair.momentum.signal.includes('BULLISH') ? 'bg-green-600 text-white' :
                    selectedPair.momentum.signal.includes('BEARISH') ? 'bg-red-600 text-white' :
                    'bg-gray-600 text-white'
                  }`}>
                    {selectedPair.momentum.signal.replace('_', ' ')}
                  </span>
                </div>
              </div>
              <button
                onClick={handleCloseModal}
                className="text-gray-400 hover:text-white transition-colors"
              >
                <span className="sr-only">Close</span>
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            
            <div className="p-4 h-96">
              <TradingViewChart
                pair={selectedPair}
                height={350}
                showTradeOverlays={true}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};