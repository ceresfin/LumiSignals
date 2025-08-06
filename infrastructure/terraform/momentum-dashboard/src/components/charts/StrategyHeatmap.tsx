import React, { useMemo, useState } from 'react';
import { Play, Pause, Square, TrendingUp, TrendingDown, BarChart3, Settings, Filter } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';

interface StrategyPerformanceData {
  strategy: string;
  pair: string;
  performance: number; // Percentage return
  winRate: number;
  sharpeRatio: number;
  maxDrawdown: number;
  tradesCount: number;
  status: 'active' | 'paused' | 'stopped';
  volume?: number;
  lastTrade?: string;
}

interface StrategyHeatmapProps {
  data: StrategyPerformanceData[];
  metric: 'performance' | 'winRate' | 'sharpeRatio' | 'maxDrawdown';
  sortBy: 'performance' | 'winRate' | 'alphabetical';
  showDetails?: boolean;
  onStrategyClick?: (strategy: string, pair: string) => void;
  onMetricChange?: (metric: 'performance' | 'winRate' | 'sharpeRatio' | 'maxDrawdown') => void;
  className?: string;
}

// Professional tooltip for strategy details
const StrategyTooltip = ({ 
  strategy, 
  visible, 
  position, 
  theme 
}: { 
  strategy: StrategyPerformanceData; 
  visible: boolean; 
  position: { x: number; y: number }; 
  theme: any;
}) => {
  if (!visible) return null;

  const formatValue = (value: number, type: 'percentage' | 'ratio' | 'count') => {
    switch (type) {
      case 'percentage':
        return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
      case 'ratio':
        return value.toFixed(2);
      case 'count':
        return value.toLocaleString();
      default:
        return value.toString();
    }
  };

  return (
    <div 
      className="fixed z-50 max-w-80 p-4 rounded-lg border backdrop-blur-sm transition-all duration-200"
      style={{
        left: position.x,
        top: position.y,
        backgroundColor: theme.background,
        borderColor: theme.border,
        color: theme.text,
        boxShadow: '0 12px 24px rgba(0, 0, 0, 0.2)'
      }}
    >
      <div className="flex items-center justify-between mb-3 pb-2 border-b" style={{ borderColor: theme.border }}>
        <div>
          <h3 className="font-semibold text-sm">{strategy.strategy}</h3>
          <p className="text-xs font-mono" style={{ color: theme.textSecondary }}>{strategy.pair}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${
            strategy.status === 'active' ? 'bg-green-500' : 
            strategy.status === 'paused' ? 'bg-yellow-500' : 'bg-red-500'
          }`} />
          <span className="text-xs capitalize" style={{ color: theme.textSecondary }}>
            {strategy.status}
          </span>
        </div>
      </div>
      
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Performance:</span>
          <span className={`font-mono font-bold ${
            strategy.performance > 0 ? 'text-green-500' : 'text-red-500'
          }`}>
            {formatValue(strategy.performance, 'percentage')}
          </span>
        </div>
        
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Win Rate:</span>
          <span className="font-mono text-sm">{formatValue(strategy.winRate, 'percentage')}</span>
        </div>
        
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Sharpe Ratio:</span>
          <span className="font-mono text-sm">{formatValue(strategy.sharpeRatio, 'ratio')}</span>
        </div>
        
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Max Drawdown:</span>
          <span className="font-mono text-sm text-red-500">
            {formatValue(strategy.maxDrawdown, 'percentage')}
          </span>
        </div>
        
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Trades:</span>
          <span className="font-mono text-sm">{formatValue(strategy.tradesCount, 'count')}</span>
        </div>
        
        {strategy.volume && (
          <div className="flex justify-between items-center">
            <span className="text-sm" style={{ color: theme.textSecondary }}>Volume:</span>
            <span className="font-mono text-sm">{strategy.volume.toLocaleString()}</span>
          </div>
        )}
        
        {strategy.lastTrade && (
          <div className="flex justify-between items-center">
            <span className="text-sm" style={{ color: theme.textSecondary }}>Last Trade:</span>
            <span className="font-mono text-xs">{strategy.lastTrade}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export const StrategyHeatmap: React.FC<StrategyHeatmapProps> = ({
  data,
  metric,
  sortBy,
  showDetails = true,
  onStrategyClick,
  onMetricChange,
  className = ''
}) => {
  const { effectiveTheme } = useTheme();
  const [hoveredStrategy, setHoveredStrategy] = useState<StrategyPerformanceData | null>(null);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });

  const theme = useMemo(() => ({
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
      secondary: '#f3f4f6',
      text: '#1f2937',
      textSecondary: '#6b7280',
      border: '#e5e7eb',
      gridLines: '#e5e7eb',
      bullishPrimary: '#047857',
      bullishSecondary: '#059669',
      bullishTertiary: '#10b981',
      bearishPrimary: '#991b1b',
      bearishSecondary: '#dc2626',
      bearishTertiary: '#ef4444',
      goldLight: '#a68b4a',
      neutralMedium: '#6b7280',
      hoverOverlay: 'rgba(0, 0, 0, 0.05)'
    },
    dark: {
      background: '#111827',
      surface: '#1f2937',
      secondary: '#374151',
      text: '#f3f4f6',
      textSecondary: '#d1d5db',
      border: '#374151',
      gridLines: '#374151',
      bullishPrimary: '#34d399',
      bullishSecondary: '#10b981',
      bullishTertiary: '#6ee7b7',
      bearishPrimary: '#f87171',
      bearishSecondary: '#ef4444',
      bearishTertiary: '#fca5a5',
      goldLight: '#c2a565',
      neutralMedium: '#d1d5db',
      hoverOverlay: 'rgba(255, 255, 255, 0.05)'
    }
  })[effectiveTheme], [effectiveTheme]);

  // Get unique strategies and pairs
  const strategies = useMemo(() => {
    const uniqueStrategies = Array.from(new Set(data.map(item => item.strategy)));
    return uniqueStrategies.sort();
  }, [data]);

  const pairs = useMemo(() => {
    const uniquePairs = Array.from(new Set(data.map(item => item.pair)));
    return uniquePairs.sort();
  }, [data]);

  // Create matrix data
  const matrixData = useMemo(() => {
    return strategies.map(strategy => ({
      strategy,
      cells: pairs.map(pair => {
        const item = data.find(d => d.strategy === strategy && d.pair === pair);
        return item || null;
      })
    }));
  }, [strategies, pairs, data]);

  const getPerformanceCategory = (value: number, metricType: string): string => {
    if (metricType === 'performance') {
      if (value >= 15) return 'performance-excellent';
      if (value >= 5) return 'performance-good';
      if (value >= -5) return 'performance-neutral';
      if (value >= -15) return 'performance-poor';
      return 'performance-very-poor';
    }
    if (metricType === 'winRate') {
      if (value >= 70) return 'performance-excellent';
      if (value >= 60) return 'performance-good';
      if (value >= 50) return 'performance-neutral';
      if (value >= 40) return 'performance-poor';
      return 'performance-very-poor';
    }
    if (metricType === 'sharpeRatio') {
      if (value >= 2) return 'performance-excellent';
      if (value >= 1) return 'performance-good';
      if (value >= 0) return 'performance-neutral';
      if (value >= -0.5) return 'performance-poor';
      return 'performance-very-poor';
    }
    // maxDrawdown
    if (value >= -5) return 'performance-excellent';
    if (value >= -10) return 'performance-good';
    if (value >= -20) return 'performance-neutral';
    if (value >= -30) return 'performance-poor';
    return 'performance-very-poor';
  };

  const getCellColors = (value: number, metricType: string) => {
    const category = getPerformanceCategory(value, metricType);
    
    switch (category) {
      case 'performance-excellent':
        return {
          background: `linear-gradient(135deg, ${theme.bullishPrimary}, ${theme.bullishSecondary})`,
          color: 'white'
        };
      case 'performance-good':
        return {
          background: `linear-gradient(135deg, ${theme.bullishSecondary}, ${theme.bullishTertiary})`,
          color: 'white'
        };
      case 'performance-neutral':
        return {
          background: theme.background,
          color: theme.text,
          border: `1px solid ${theme.gridLines}`
        };
      case 'performance-poor':
        return {
          background: `linear-gradient(135deg, ${theme.bearishTertiary}, ${theme.bearishSecondary})`,
          color: 'white'
        };
      case 'performance-very-poor':
        return {
          background: `linear-gradient(135deg, ${theme.bearishSecondary}, ${theme.bearishPrimary})`,
          color: 'white'
        };
      default:
        return {
          background: theme.surface,
          color: theme.textSecondary
        };
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active':
        return <Play className="w-3 h-3 text-green-500" />;
      case 'paused':
        return <Pause className="w-3 h-3 text-yellow-500" />;
      case 'stopped':
        return <Square className="w-3 h-3 text-red-500" />;
      default:
        return null;
    }
  };

  const formatMetricValue = (item: StrategyPerformanceData, metricType: string) => {
    switch (metricType) {
      case 'performance':
        return `${item.performance > 0 ? '+' : ''}${item.performance.toFixed(1)}%`;
      case 'winRate':
        return `${item.winRate.toFixed(1)}%`;
      case 'sharpeRatio':
        return item.sharpeRatio.toFixed(2);
      case 'maxDrawdown':
        return `${item.maxDrawdown.toFixed(1)}%`;
      default:
        return '';
    }
  };

  const handleMouseMove = (e: React.MouseEvent, strategy: StrategyPerformanceData) => {
    setMousePosition({
      x: e.clientX + 10,
      y: e.clientY - 10
    });
    setHoveredStrategy(strategy);
  };

  const handleMouseLeave = () => {
    setHoveredStrategy(null);
  };

  const handleCellClick = (strategy: string, pair: string) => {
    if (onStrategyClick) {
      onStrategyClick(strategy, pair);
    }
  };

  const metricOptions = [
    { value: 'performance', label: 'Performance', icon: TrendingUp },
    { value: 'winRate', label: 'Win Rate', icon: BarChart3 },
    { value: 'sharpeRatio', label: 'Sharpe Ratio', icon: TrendingUp },
    { value: 'maxDrawdown', label: 'Max Drawdown', icon: TrendingDown }
  ];

  return (
    <div className={`${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold mb-1" style={{ color: theme.text }}>
            Strategy Performance Heatmap
          </h2>
          <p className="text-sm" style={{ color: theme.textSecondary }}>
            Performance matrix across strategies and trading pairs
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4" style={{ color: theme.textSecondary }} />
            <select 
              value={metric}
              onChange={(e) => onMetricChange?.(e.target.value as any)}
              className="px-3 py-1 text-sm rounded-md border"
              style={{ 
                backgroundColor: theme.surface,
                borderColor: theme.border,
                color: theme.text
              }}
            >
              {metricOptions.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Heatmap */}
      <div className="overflow-x-auto">
        <div 
          className="inline-block min-w-full rounded-lg overflow-hidden"
          style={{ backgroundColor: theme.gridLines }}
        >
          {/* Header Row */}
          <div className="flex">
            <div 
              className="w-48 p-3 text-sm font-semibold border-b-2"
              style={{ 
                backgroundColor: theme.secondary,
                color: theme.text,
                borderColor: theme.gridLines
              }}
            >
              Strategy \ Pair
            </div>
            {pairs.map(pair => (
              <div 
                key={pair}
                className="w-24 p-3 text-center text-sm font-semibold border-b-2"
                style={{ 
                  backgroundColor: theme.secondary,
                  color: theme.text,
                  borderColor: theme.gridLines
                }}
              >
                {pair}
              </div>
            ))}
          </div>

          {/* Data Rows */}
          {matrixData.map(({ strategy, cells }) => (
            <div key={strategy} className="flex">
              {/* Strategy Label */}
              <div 
                className="w-48 p-3 text-sm font-medium flex items-center gap-2"
                style={{ 
                  backgroundColor: theme.secondary,
                  color: theme.text
                }}
              >
                <span className="truncate">{strategy}</span>
              </div>

              {/* Data Cells */}
              {cells.map((item, index) => (
                <div 
                  key={index}
                  className="w-24 p-3 text-center text-sm font-semibold font-mono cursor-pointer transition-all duration-200 hover:scale-105 hover:z-10 relative overflow-hidden"
                  style={item ? getCellColors(item[metric], metric) : { backgroundColor: theme.surface, color: theme.textSecondary }}
                  onMouseMove={(e) => item && handleMouseMove(e, item)}
                  onMouseLeave={handleMouseLeave}
                  onClick={() => item && handleCellClick(item.strategy, item.pair)}
                >
                  {item ? (
                    <>
                      <div className="text-sm font-bold mb-1">
                        {formatMetricValue(item, metric)}
                      </div>
                      {showDetails && (
                        <div className="text-xs opacity-80 flex items-center justify-center gap-1">
                          {getStatusIcon(item.status)}
                          <span>{item.tradesCount}</span>
                        </div>
                      )}
                      {/* Hover overlay */}
                      <div 
                        className="absolute inset-0 opacity-0 hover:opacity-100 transition-opacity duration-200"
                        style={{ backgroundColor: theme.hoverOverlay }}
                      />
                    </>
                  ) : (
                    <span className="text-xs">-</span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="mt-6 p-4 rounded-lg border" style={{ 
        backgroundColor: theme.surface,
        borderColor: theme.border
      }}>
        <h3 className="text-sm font-medium mb-3" style={{ color: theme.text }}>
          Performance Legend
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bullishPrimary }} />
            <span style={{ color: theme.textSecondary }}>Excellent</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bullishSecondary }} />
            <span style={{ color: theme.textSecondary }}>Good</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded border" style={{ 
              backgroundColor: theme.background,
              borderColor: theme.gridLines
            }} />
            <span style={{ color: theme.textSecondary }}>Neutral</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bearishSecondary }} />
            <span style={{ color: theme.textSecondary }}>Poor</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bearishPrimary }} />
            <span style={{ color: theme.textSecondary }}>Very Poor</span>
          </div>
        </div>
      </div>

      {/* Tooltip */}
      <StrategyTooltip 
        strategy={hoveredStrategy!}
        visible={!!hoveredStrategy}
        position={mousePosition}
        theme={theme}
      />
    </div>
  );
};