// Enhanced Trade Grid - PipStop Design System
import React, { useState, useMemo } from 'react';
import { useMomentumRanking } from '../../hooks/useMomentumRanking';
import { TradeCard } from './TradeCard';
import { CurrencyPair } from '../../types/momentum';
import { RefreshCw, Filter, TrendingUp, TrendingDown, Minus, Grid3x3, List, Activity } from 'lucide-react';

interface TradeGridProps {
  showFilters?: boolean;
  autoRefresh?: boolean;
}

export const TradeGrid: React.FC<TradeGridProps> = ({
  showFilters = true,
  autoRefresh = true
}) => {
  const { rankedPairs, loading, error, connected, lastUpdated, refreshRanking, filterBySignal } = useMomentumRanking();
  const [selectedPair, setSelectedPair] = useState<CurrencyPair | null>(null);
  const [signalFilter, setSignalFilter] = useState<string>('');
  const [showMajorOnly, setShowMajorOnly] = useState(false);
  const [viewMode, setViewMode] = useState<'cards' | 'list'>('cards');

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

  const getSignalIcon = (signal: string) => {
    if (signal.includes('BULLISH')) return <TrendingUp className="w-4 h-4" />;
    if (signal.includes('BEARISH')) return <TrendingDown className="w-4 h-4" />;
    return <Minus className="w-4 h-4" />;
  };

  const getSignalColor = (signal: string) => {
    if (signal.includes('STRONG') && signal.includes('BULLISH')) return 'var(--ps-success)';
    if (signal.includes('WEAK') && signal.includes('BULLISH')) return 'var(--ps-success)';
    if (signal.includes('NEUTRAL')) return 'var(--ps-text-secondary)';
    if (signal.includes('WEAK') && signal.includes('BEARISH')) return 'var(--ps-danger)';
    if (signal.includes('STRONG') && signal.includes('BEARISH')) return 'var(--ps-danger)';
    return 'var(--ps-text-secondary)';
  };

  if (loading && rankedPairs.length === 0) {
    return (
      <div className="ps-card" style={{ 
        padding: 'var(--ps-spacing-xl)',
        textAlign: 'center',
        minHeight: '400px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <div>
          <RefreshCw className="w-8 h-8 ps-pulse" style={{ 
            color: 'var(--ps-accent-primary)',
            margin: '0 auto var(--ps-spacing-md)',
            display: 'block'
          }} />
          <p style={{ color: 'var(--ps-text-secondary)', margin: 0 }}>
            Loading momentum analysis...
          </p>
        </div>
      </div>
    );
  }

  if (error && rankedPairs.length === 0) {
    return (
      <div className="ps-card" style={{ 
        padding: 'var(--ps-spacing-xl)',
        textAlign: 'center',
        minHeight: '400px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <div>
          <p style={{ color: 'var(--ps-danger)', marginBottom: 'var(--ps-spacing-md)' }}>
            Error: {error}
          </p>
          <button
            onClick={refreshRanking}
            className="ps-btn ps-btn-primary"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ps-spacing-lg)' }}>
      {/* Header and Controls */}
      <div className="ps-card-header" style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between',
        background: 'var(--ps-bg-surface)',
        border: `1px solid var(--ps-border)`,
        borderRadius: 'var(--ps-radius-lg)',
        padding: 'var(--ps-spacing-lg)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--ps-spacing-md)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--ps-spacing-sm)' }}>
            <Activity className="w-6 h-6" style={{ color: 'var(--ps-accent-primary)' }} />
            <h2 style={{ 
              fontSize: 'var(--ps-font-size-2xl)',
              fontWeight: 700,
              color: 'var(--ps-text-primary)',
              margin: 0
            }}>
              Active Trades
            </h2>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--ps-spacing-sm)' }}>
            <div style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: connected ? 'var(--ps-status-active)' : 'var(--ps-status-stopped)'
            }} />
            <span style={{ 
              fontSize: 'var(--ps-font-size-sm)',
              color: 'var(--ps-text-secondary)'
            }}>
              {connected ? 'Live' : 'Offline'}
            </span>
            {lastUpdated && (
              <span style={{ 
                fontSize: 'var(--ps-font-size-sm)',
                color: 'var(--ps-text-secondary)'
              }}>
                • Updated {new Date(lastUpdated).toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--ps-spacing-sm)' }}>
          {/* View Toggle */}
          <div style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: '2px',
            background: 'var(--ps-bg-elevated)',
            borderRadius: 'var(--ps-radius-md)',
            padding: '2px'
          }}>
            <button
              onClick={() => setViewMode('cards')}
              className="ps-btn"
              style={{
                padding: 'var(--ps-spacing-sm)',
                background: viewMode === 'cards' ? 'var(--ps-accent-primary)' : 'transparent',
                color: viewMode === 'cards' ? 'var(--ps-bg-primary)' : 'var(--ps-text-secondary)',
                border: 'none',
                borderRadius: 'var(--ps-radius-sm)'
              }}
              title="Card View"
            >
              <Grid3x3 className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className="ps-btn"
              style={{
                padding: 'var(--ps-spacing-sm)',
                background: viewMode === 'list' ? 'var(--ps-accent-primary)' : 'transparent',
                color: viewMode === 'list' ? 'var(--ps-bg-primary)' : 'var(--ps-text-secondary)',
                border: 'none',
                borderRadius: 'var(--ps-radius-sm)'
              }}
              title="List View"
            >
              <List className="w-4 h-4" />
            </button>
          </div>
          
          <button
            onClick={refreshRanking}
            disabled={loading}
            className="ps-btn ps-btn-secondary"
            style={{
              padding: 'var(--ps-spacing-sm)',
              opacity: loading ? 0.5 : 1
            }}
            title="Refresh Rankings"
          >
            <RefreshCw className={`w-5 h-5 ${loading ? 'ps-pulse' : ''}`} />
          </button>
          
          <span style={{ 
            fontSize: 'var(--ps-font-size-sm)',
            color: 'var(--ps-text-secondary)'
          }}>
            {displayPairs.length} Active Trade{displayPairs.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Filters */}
      {showFilters && (
        <div className="ps-card" style={{ padding: 'var(--ps-spacing-lg)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ps-spacing-md)' }}>
            {/* Signal Filters */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--ps-spacing-sm)', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--ps-spacing-xs)' }}>
                <Filter className="w-4 h-4" style={{ color: 'var(--ps-text-secondary)' }} />
                <span style={{ 
                  fontSize: 'var(--ps-font-size-sm)',
                  color: 'var(--ps-text-secondary)'
                }}>
                  Filter by signal:
                </span>
              </div>
              
              <button
                onClick={() => setSignalFilter('')}
                className="ps-btn"
                style={{
                  padding: 'var(--ps-spacing-xs) var(--ps-spacing-sm)',
                  fontSize: 'var(--ps-font-size-xs)',
                  background: signalFilter === '' ? 'var(--ps-accent-primary)' : 'var(--ps-bg-elevated)',
                  color: signalFilter === '' ? 'var(--ps-bg-primary)' : 'var(--ps-text-secondary)',
                  border: `1px solid ${signalFilter === '' ? 'var(--ps-accent-primary)' : 'var(--ps-border)'}`
                }}
              >
                All ({rankedPairs.length})
              </button>
              
              {Object.entries(signalCounts).map(([signal, count]) => (
                <button
                  key={signal}
                  onClick={() => setSignalFilter(signal === signalFilter ? '' : signal)}
                  className="ps-btn"
                  style={{
                    padding: 'var(--ps-spacing-xs) var(--ps-spacing-sm)',
                    fontSize: 'var(--ps-font-size-xs)',
                    background: signalFilter === signal ? getSignalColor(signal) : 'var(--ps-bg-elevated)',
                    color: signalFilter === signal ? 'var(--ps-bg-primary)' : 'var(--ps-text-secondary)',
                    border: `1px solid ${signalFilter === signal ? getSignalColor(signal) : 'var(--ps-border)'}`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--ps-spacing-xs)'
                  }}
                >
                  {getSignalIcon(signal)}
                  <span>{signal.replace('_', ' ').toLowerCase()} ({count})</span>
                </button>
              ))}
            </div>
            
            {/* Additional Filters */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--ps-spacing-md)' }}>
              <label style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: 'var(--ps-spacing-sm)',
                fontSize: 'var(--ps-font-size-sm)',
                color: 'var(--ps-text-secondary)',
                cursor: 'pointer'
              }}>
                <input
                  type="checkbox"
                  checked={showMajorOnly}
                  onChange={(e) => setShowMajorOnly(e.target.checked)}
                  style={{ borderRadius: 'var(--ps-radius-sm)' }}
                />
                <span>Major pairs only</span>
              </label>
            </div>
          </div>
        </div>
      )}

      {/* Content Area */}
      <div style={{ 
        display: viewMode === 'cards' ? 'grid' : 'flex',
        gridTemplateColumns: viewMode === 'cards' ? 'repeat(auto-fill, minmax(400px, 1fr))' : 'none',
        flexDirection: viewMode === 'list' ? 'column' : 'row',
        gap: 'var(--ps-spacing-md)'
      }}>
        {displayPairs.map((pair) => (
          <TradeCard
            key={pair.pair}
            pair={pair}
            onClick={handlePairClick}
            compact={viewMode === 'list'}
          />
        ))}
      </div>

      {/* Empty State - ONLY REAL DATA */}
      {displayPairs.length === 0 && !loading && (
        <div className="ps-card" style={{ 
          padding: 'var(--ps-spacing-xl)',
          textAlign: 'center',
          minHeight: '300px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '2px dashed var(--ps-border)'
        }}>
          <div>
            <Activity className="w-12 h-12" style={{ 
              color: 'var(--ps-text-muted)',
              margin: '0 auto var(--ps-spacing-md)',
              display: 'block',
              opacity: 0.5
            }} />
            <h3 style={{ 
              color: 'var(--ps-text-primary)', 
              marginBottom: 'var(--ps-spacing-sm)',
              fontSize: 'var(--ps-font-size-lg)'
            }}>
              No Active Trades Found
            </h3>
            <p style={{ color: 'var(--ps-text-secondary)', marginBottom: 'var(--ps-spacing-md)' }}>
              {error || 'The RDS API returned no active trading positions.'}
            </p>
            <p style={{ 
              color: 'var(--ps-text-muted)', 
              fontSize: 'var(--ps-font-size-sm)',
              marginBottom: 'var(--ps-spacing-lg)'
            }}>
              This dashboard only displays REAL trading data. No fake or demo data will be shown.
            </p>
            <div style={{ display: 'flex', gap: 'var(--ps-spacing-sm)', justifyContent: 'center' }}>
              <button
                onClick={refreshRanking}
                className="ps-btn ps-btn-primary"
              >
                <RefreshCw className="w-4 h-4" style={{ marginRight: 'var(--ps-spacing-xs)' }} />
                Refresh Data
              </button>
              {rankedPairs.length === 0 && signalFilter && (
                <button
                  onClick={() => {
                    setSignalFilter('');
                    setShowMajorOnly(false);
                  }}
                  className="ps-btn ps-btn-secondary"
                >
                  Clear Filters
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TradeGrid;