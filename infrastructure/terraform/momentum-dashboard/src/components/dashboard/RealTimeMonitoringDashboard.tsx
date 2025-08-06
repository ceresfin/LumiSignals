import React, { useState, useEffect, useMemo } from 'react';
import { Activity, Wifi, WifiOff, Clock, RefreshCw, Settings, Maximize2, AlertCircle } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';
import { CurrencyStrengthMatrix } from '../charts/CurrencyStrengthMatrix';
import { StrategyHeatmap } from '../charts/StrategyHeatmap';
import { RiskExposureChart } from '../charts/RiskExposureChart';
import { MultiTimeframeAnalysis } from '../charts/MultiTimeframeAnalysis';
import { InstitutionalChart } from '../charts/InstitutionalChart';
import { useLiveData } from '../../hooks/useLiveData';

// Dashboard state interface
interface DashboardState {
  selectedTimeframe: string;
  selectedMetric: 'performance' | 'winRate' | 'sharpeRatio' | 'maxDrawdown';
  autoRefresh: boolean;
  refreshInterval: number;
  expandedPanel: string | null;
}

// Connection status indicator
const ConnectionStatusIndicator = ({ 
  status, 
  theme 
}: { 
  status: import('../../types/dashboardTypes').ConnectionStatus;
  theme: any;
}) => {
  return (
    <div className="flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium" style={{
      backgroundColor: status.connected ? `${theme.bullishPrimary}20` : `${theme.bearishPrimary}20`,
      color: status.connected ? theme.bullishPrimary : theme.bearishPrimary
    }}>
      {status.connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
      <span>{status.connected ? 'Connected' : 'Disconnected'}</span>
      {status.connected && status.dataPoints && (
        <span className="text-xs opacity-75">
          {status.dataPoints} pts
        </span>
      )}
    </div>
  );
};

// Auto-refresh indicator
const AutoRefreshIndicator = ({ 
  enabled, 
  interval, 
  theme,
  onToggle 
}: { 
  enabled: boolean;
  interval: number;
  theme: any;
  onToggle: () => void;
}) => {
  const [countdown, setCountdown] = useState(interval);

  useEffect(() => {
    if (!enabled) return;

    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          return interval;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [enabled, interval]);

  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium transition-colors"
      style={{
        backgroundColor: enabled ? `${theme.bullishPrimary}20` : `${theme.neutralMedium}20`,
        color: enabled ? theme.bullishPrimary : theme.neutralMedium
      }}
    >
      <RefreshCw className={`w-3 h-3 ${enabled ? 'animate-spin' : ''}`} />
      <span>{enabled ? `Auto (${countdown}s)` : 'Manual'}</span>
    </button>
  );
};

// Loading skeleton for dashboard panels
const LoadingSkeleton = ({ theme }: { theme: any }) => (
  <div className="space-y-4">
    {[...Array(3)].map((_, i) => (
      <div key={i} className="h-4 rounded animate-pulse" style={{ backgroundColor: theme.surface }} />
    ))}
  </div>
);

// Live data integration complete - mock data generators removed

export const RealTimeMonitoringDashboard: React.FC = () => {
  const { effectiveTheme } = useTheme();
  
  // Use live data hook instead of mock data
  const {
    currencyData,
    strategyData,
    riskData,
    timeframeData,
    chartData,
    portfolioSummary,
    connectionStatus,
    loading,
    error,
    refreshData
  } = useLiveData({
    autoRefresh: true,
    refreshInterval: 30000, // 30 seconds
    onError: (error) => {
      console.error('Live data error:', error);
    }
  });

  const [dashboardState, setDashboardState] = useState<DashboardState>({
    selectedTimeframe: '1H',
    selectedMetric: 'performance',
    autoRefresh: true,
    refreshInterval: 30,
    expandedPanel: null
  });

  const theme = useMemo(() => ({
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
      text: '#1f2937',
      textSecondary: '#6b7280',
      border: '#e5e7eb',
      bullishPrimary: '#047857',
      bearishPrimary: '#991b1b',
      neutralMedium: '#6b7280',
      hoverOverlay: 'rgba(0, 0, 0, 0.05)'
    },
    dark: {
      background: '#111827',
      surface: '#1f2937',
      text: '#f3f4f6',
      textSecondary: '#d1d5db',
      border: '#374151',
      bullishPrimary: '#34d399',
      bearishPrimary: '#f87171',
      neutralMedium: '#d1d5db',
      hoverOverlay: 'rgba(255, 255, 255, 0.05)'
    }
  })[effectiveTheme], [effectiveTheme]);

  // Manual refresh function
  const handleRefreshToggle = () => {
    setDashboardState(prev => ({ ...prev, autoRefresh: !prev.autoRefresh }));
  };

  // Manual refresh trigger
  const handleManualRefresh = () => {
    refreshData();
  };

  const handleTimeframeSelect = (timeframe: string) => {
    setDashboardState(prev => ({ ...prev, selectedTimeframe: timeframe }));
  };

  const handleMetricChange = (metric: 'performance' | 'winRate' | 'sharpeRatio' | 'maxDrawdown') => {
    setDashboardState(prev => ({ ...prev, selectedMetric: metric }));
  };

  const handlePanelExpand = (panelId: string) => {
    setDashboardState(prev => ({ 
      ...prev, 
      expandedPanel: prev.expandedPanel === panelId ? null : panelId 
    }));
  };

  return (
    <div className={`min-h-screen p-6 transition-colors duration-200`} style={{ backgroundColor: theme.surface }}>
      {/* Dashboard Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold mb-2" style={{ color: theme.text }}>
            Real-Time Trading Dashboard
          </h1>
          <p className="text-lg" style={{ color: theme.textSecondary }}>
            Live market analysis and strategy monitoring
          </p>
          {error && (
            <div className="flex items-center gap-2 mt-2 px-3 py-1 rounded-lg bg-red-100 dark:bg-red-900/20">
              <AlertCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
              <span className="text-sm text-red-700 dark:text-red-300">
                {error}
              </span>
            </div>
          )}
        </div>
        
        <div className="flex items-center gap-4">
          <ConnectionStatusIndicator status={connectionStatus} theme={theme} />
          <AutoRefreshIndicator 
            enabled={dashboardState.autoRefresh}
            interval={dashboardState.refreshInterval}
            theme={theme}
            onToggle={handleRefreshToggle}
          />
          <button 
            onClick={handleManualRefresh}
            disabled={loading}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
            title="Manual refresh"
          >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} style={{ color: theme.textSecondary }} />
          </button>
          <button className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700">
            <Settings className="w-5 h-5" style={{ color: theme.textSecondary }} />
          </button>
        </div>
      </div>

      {/* Main Dashboard Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-8">
        {/* Currency Strength Matrix */}
        <div className={`p-6 rounded-lg border ${dashboardState.expandedPanel === 'currency' ? 'xl:col-span-2' : ''}`} style={{ backgroundColor: theme.background, borderColor: theme.border }}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold" style={{ color: theme.text }}>Currency Strength</h2>
            <button onClick={() => handlePanelExpand('currency')}>
              <Maximize2 className="w-4 h-4" style={{ color: theme.textSecondary }} />
            </button>
          </div>
          {loading ? (
            <LoadingSkeleton theme={theme} />
          ) : (
            <CurrencyStrengthMatrix 
              data={currencyData}
              timeframe={dashboardState.selectedTimeframe as any}
              showRankings={true}
              interactive={true}
            />
          )}
        </div>

        {/* Strategy Performance Heatmap */}
        <div className={`p-6 rounded-lg border ${dashboardState.expandedPanel === 'strategy' ? 'xl:col-span-2' : ''}`} style={{ backgroundColor: theme.background, borderColor: theme.border }}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold" style={{ color: theme.text }}>Strategy Performance</h2>
            <button onClick={() => handlePanelExpand('strategy')}>
              <Maximize2 className="w-4 h-4" style={{ color: theme.textSecondary }} />
            </button>
          </div>
          {loading ? (
            <LoadingSkeleton theme={theme} />
          ) : (
            <StrategyHeatmap 
              data={strategyData}
              metric={dashboardState.selectedMetric}
              sortBy="performance"
              showDetails={true}
              onMetricChange={handleMetricChange}
            />
          )}
        </div>
      </div>

      {/* Risk and Timeframe Analysis */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-8">
        {/* Risk Exposure Chart */}
        <div className={`p-6 rounded-lg border ${dashboardState.expandedPanel === 'risk' ? 'xl:col-span-2' : ''}`} style={{ backgroundColor: theme.background, borderColor: theme.border }}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold" style={{ color: theme.text }}>Risk Exposure</h2>
            <button onClick={() => handlePanelExpand('risk')}>
              <Maximize2 className="w-4 h-4" style={{ color: theme.textSecondary }} />
            </button>
          </div>
          {loading ? (
            <LoadingSkeleton theme={theme} />
          ) : (
            <RiskExposureChart 
              data={riskData}
              totalPortfolioValue={portfolioSummary.totalValue}
              riskTolerance={portfolioSummary.totalValue * 0.2} // 20% risk tolerance
              showCorrelations={true}
              showTooltips={true}
            />
          )}
        </div>

        {/* Multi-Timeframe Analysis */}
        <div className={`p-6 rounded-lg border ${dashboardState.expandedPanel === 'timeframe' ? 'xl:col-span-2' : ''}`} style={{ backgroundColor: theme.background, borderColor: theme.border }}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold" style={{ color: theme.text }}>Multi-Timeframe</h2>
            <button onClick={() => handlePanelExpand('timeframe')}>
              <Maximize2 className="w-4 h-4" style={{ color: theme.textSecondary }} />
            </button>
          </div>
          {loading ? (
            <LoadingSkeleton theme={theme} />
          ) : (
            <MultiTimeframeAnalysis 
              data={timeframeData}
              currentPair="EURUSD"
              selectedTimeframe={dashboardState.selectedTimeframe}
              onTimeframeSelect={handleTimeframeSelect}
              showDetails={true}
            />
          )}
        </div>
      </div>

      {/* Price Chart */}
      <div className="p-6 rounded-lg border mb-8" style={{ backgroundColor: theme.background, borderColor: theme.border }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold" style={{ color: theme.text }}>EURUSD Price Chart</h2>
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4" style={{ color: theme.textSecondary }} />
            <span className="text-sm" style={{ color: theme.textSecondary }}>
              {dashboardState.selectedTimeframe}
            </span>
          </div>
        </div>
        {loading ? (
          <LoadingSkeleton theme={theme} />
        ) : (
          <InstitutionalChart 
            data={chartData}
            title="EURUSD"
            subtitle="Real-time price action"
            type="area"
            height={400}
            showControls={true}
            showGrid={true}
            animated={true}
            precision={5}
          />
        )}
      </div>

      {/* Status Bar */}
      <div className="flex items-center justify-between p-4 rounded-lg border" style={{ backgroundColor: theme.background, borderColor: theme.border }}>
        <div className="flex items-center gap-4 text-sm" style={{ color: theme.textSecondary }}>
          <span>Last Update: {connectionStatus.lastUpdate}</span>
          <span>•</span>
          <span>Data Points: {connectionStatus.dataPoints || 0}</span>
          <span>•</span>
          <span>Active Strategies: {portfolioSummary.activeStrategies}</span>
          <span>•</span>
          <span>Total Trades: {portfolioSummary.totalTrades}</span>
          <span>•</span>
          <span className={portfolioSummary.totalPnL >= 0 ? 'text-green-500' : 'text-red-500'}>
            P&L: ${portfolioSummary.totalPnL.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-green-500" />
          <span className="text-sm font-medium text-green-500">System Operational</span>
        </div>
      </div>
    </div>
  );
};