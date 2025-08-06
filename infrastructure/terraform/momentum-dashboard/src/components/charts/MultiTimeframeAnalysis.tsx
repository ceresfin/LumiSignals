import React, { useMemo, useState } from 'react';
import { TrendingUp, TrendingDown, Minus, Clock, Target, Activity, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';

interface TimeframeData {
  timeframe: string;
  trend: 'bullish' | 'bearish' | 'sideways';
  strength: number; // 0-100
  support: number;
  resistance: number;
  volatility: number;
  volume: number;
  price?: number;
  change?: number;
  changePercent?: number;
  lastUpdated?: string;
}

interface MultiTimeframeAnalysisProps {
  data: TimeframeData[];
  currentPair: string;
  selectedTimeframe: string;
  onTimeframeSelect: (timeframe: string) => void;
  showDetails?: boolean;
  className?: string;
}

// Strength gauge component
const StrengthGauge = ({ 
  strength, 
  trend, 
  theme,
  size = 'normal'
}: { 
  strength: number; 
  trend: 'bullish' | 'bearish' | 'sideways';
  theme: any;
  size?: 'small' | 'normal' | 'large';
}) => {
  const getStrengthColor = (strength: number, trend: string) => {
    if (trend === 'sideways') {
      return `linear-gradient(90deg, ${theme.neutralMedium}, ${theme.neutralWeak})`;
    }
    
    if (strength >= 70) {
      return trend === 'bullish' 
        ? `linear-gradient(90deg, ${theme.bullishSecondary}, ${theme.bullishPrimary})`
        : `linear-gradient(90deg, ${theme.bearishSecondary}, ${theme.bearishPrimary})`;
    } else if (strength >= 40) {
      return trend === 'bullish'
        ? `linear-gradient(90deg, ${theme.bullishTertiary}, ${theme.bullishSecondary})`
        : `linear-gradient(90deg, ${theme.bearishTertiary}, ${theme.bearishSecondary})`;
    } else {
      return `linear-gradient(90deg, ${theme.goldLight}, ${theme.goldDark || theme.goldLight})`;
    }
  };

  const sizes = {
    small: { height: 6, track: 4 },
    normal: { height: 8, track: 6 },
    large: { height: 12, track: 8 }
  };

  return (
    <div className="w-full">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs font-medium" style={{ color: theme.textSecondary }}>
          Strength
        </span>
        <span className="text-xs font-mono font-bold" style={{ color: theme.text }}>
          {strength.toFixed(0)}%
        </span>
      </div>
      <div 
        className="w-full rounded-full overflow-hidden"
        style={{ 
          height: `${sizes[size].track}px`,
          backgroundColor: theme.surface
        }}
      >
        <div 
          className="h-full transition-all duration-1000 ease-out relative"
          style={{ 
            width: `${strength}%`,
            background: getStrengthColor(strength, trend)
          }}
        >
          {/* Pulse indicator */}
          <div 
            className="absolute top-0 right-0 w-0.5 h-full bg-white opacity-60"
            style={{ animation: 'pulse 2s infinite' }}
          />
        </div>
      </div>
    </div>
  );
};

// Trend indicator component
const TrendIndicator = ({ 
  trend, 
  strength, 
  theme,
  size = 'normal'
}: { 
  trend: 'bullish' | 'bearish' | 'sideways';
  strength: number;
  theme: any;
  size?: 'small' | 'normal' | 'large';
}) => {
  const getTrendConfig = (trend: string) => {
    switch (trend) {
      case 'bullish':
        return {
          icon: TrendingUp,
          color: theme.bullishPrimary,
          bgColor: `${theme.bullishPrimary}20`,
          label: 'Bullish'
        };
      case 'bearish':
        return {
          icon: TrendingDown,
          color: theme.bearishPrimary,
          bgColor: `${theme.bearishPrimary}20`,
          label: 'Bearish'
        };
      case 'sideways':
        return {
          icon: Minus,
          color: theme.neutralMedium,
          bgColor: `${theme.neutralMedium}20`,
          label: 'Sideways'
        };
      default:
        return {
          icon: Minus,
          color: theme.neutralMedium,
          bgColor: `${theme.neutralMedium}20`,
          label: 'Unknown'
        };
    }
  };

  const config = getTrendConfig(trend);
  const Icon = config.icon;
  
  const iconSizes = {
    small: 'w-3 h-3',
    normal: 'w-4 h-4',
    large: 'w-5 h-5'
  };

  const textSizes = {
    small: 'text-xs',
    normal: 'text-sm',
    large: 'text-base'
  };

  return (
    <div 
      className={`inline-flex items-center gap-2 px-2 py-1 rounded-full ${textSizes[size]} font-semibold`}
      style={{ 
        backgroundColor: config.bgColor,
        color: config.color
      }}
    >
      <Icon className={iconSizes[size]} />
      <span>{config.label}</span>
      <span className="text-xs font-mono">({strength.toFixed(0)}%)</span>
    </div>
  );
};

// Volatility dots component
const VolatilityIndicator = ({ 
  volatility, 
  theme,
  size = 'normal'
}: { 
  volatility: number;
  theme: any;
  size?: 'small' | 'normal' | 'large';
}) => {
  const dotCount = 5;
  const activeDots = Math.min(Math.ceil(volatility / 20), dotCount);
  
  const dotSizes = {
    small: 'w-1.5 h-1.5',
    normal: 'w-2 h-2',
    large: 'w-3 h-3'
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium" style={{ color: theme.textSecondary }}>
        Volatility:
      </span>
      <div className="flex gap-1">
        {[...Array(dotCount)].map((_, i) => (
          <div 
            key={i}
            className={`${dotSizes[size]} rounded-full transition-all duration-300`}
            style={{ 
              backgroundColor: i < activeDots ? theme.goldLight : theme.neutralWeak,
              boxShadow: i < activeDots ? `0 0 4px ${theme.goldLight}` : 'none'
            }}
          />
        ))}
      </div>
      <span className="text-xs font-mono" style={{ color: theme.textSecondary }}>
        {volatility.toFixed(1)}%
      </span>
    </div>
  );
};

// Key levels component
const KeyLevels = ({ 
  support, 
  resistance, 
  currentPrice, 
  theme,
  precision = 5
}: { 
  support: number;
  resistance: number;
  currentPrice?: number;
  theme: any;
  precision?: number;
}) => {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div 
        className="p-3 rounded-lg border text-center"
        style={{ 
          backgroundColor: theme.surface,
          borderColor: theme.border,
          borderLeftColor: theme.bullishSecondary,
          borderLeftWidth: '3px'
        }}
      >
        <div className="text-xs font-medium mb-1" style={{ color: theme.textSecondary }}>
          Support
        </div>
        <div className="text-sm font-mono font-bold" style={{ color: theme.text }}>
          {support.toFixed(precision)}
        </div>
        {currentPrice && (
          <div className="text-xs mt-1" style={{ color: theme.textSecondary }}>
            {((currentPrice - support) / support * 100).toFixed(1)}%
          </div>
        )}
      </div>
      
      <div 
        className="p-3 rounded-lg border text-center"
        style={{ 
          backgroundColor: theme.surface,
          borderColor: theme.border,
          borderLeftColor: theme.bearishSecondary,
          borderLeftWidth: '3px'
        }}
      >
        <div className="text-xs font-medium mb-1" style={{ color: theme.textSecondary }}>
          Resistance
        </div>
        <div className="text-sm font-mono font-bold" style={{ color: theme.text }}>
          {resistance.toFixed(precision)}
        </div>
        {currentPrice && (
          <div className="text-xs mt-1" style={{ color: theme.textSecondary }}>
            {((resistance - currentPrice) / currentPrice * 100).toFixed(1)}%
          </div>
        )}
      </div>
    </div>
  );
};

export const MultiTimeframeAnalysis: React.FC<MultiTimeframeAnalysisProps> = ({
  data,
  currentPair,
  selectedTimeframe,
  onTimeframeSelect,
  showDetails = true,
  className = ''
}) => {
  const { effectiveTheme } = useTheme();
  const [hoveredTimeframe, setHoveredTimeframe] = useState<string | null>(null);

  const theme = useMemo(() => ({
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
      secondary: '#f3f4f6',
      text: '#1f2937',
      textSecondary: '#6b7280',
      border: '#e5e7eb',
      bullishPrimary: '#047857',
      bullishSecondary: '#059669',
      bullishTertiary: '#10b981',
      bearishPrimary: '#991b1b',
      bearishSecondary: '#dc2626',
      bearishTertiary: '#ef4444',
      goldLight: '#a68b4a',
      goldDark: '#8b7355',
      neutralMedium: '#6b7280',
      neutralWeak: '#9ca3af',
      sageLight: '#6b7d6e',
      hoverOverlay: 'rgba(0, 0, 0, 0.05)'
    },
    dark: {
      background: '#111827',
      surface: '#1f2937',
      secondary: '#374151',
      text: '#f3f4f6',
      textSecondary: '#d1d5db',
      border: '#374151',
      bullishPrimary: '#34d399',
      bullishSecondary: '#10b981',
      bullishTertiary: '#6ee7b7',
      bearishPrimary: '#f87171',
      bearishSecondary: '#ef4444',
      bearishTertiary: '#fca5a5',
      goldLight: '#c2a565',
      goldDark: '#a68b4a',
      neutralMedium: '#d1d5db',
      neutralWeak: '#9ca3af',
      sageLight: '#a2c4ba',
      hoverOverlay: 'rgba(255, 255, 255, 0.05)'
    }
  })[effectiveTheme], [effectiveTheme]);

  const sortedData = useMemo(() => {
    const timeframeOrder = ['1M', '5M', '15M', '1H', '4H', '1D', '1W', '1M'];
    return [...data].sort((a, b) => {
      const aIndex = timeframeOrder.indexOf(a.timeframe);
      const bIndex = timeframeOrder.indexOf(b.timeframe);
      return aIndex - bIndex;
    });
  }, [data]);

  const overallSentiment = useMemo(() => {
    const bullishCount = data.filter(d => d.trend === 'bullish').length;
    const bearishCount = data.filter(d => d.trend === 'bearish').length;
    const sidewaysCount = data.filter(d => d.trend === 'sideways').length;
    
    if (bullishCount > bearishCount && bullishCount > sidewaysCount) return 'bullish';
    if (bearishCount > bullishCount && bearishCount > sidewaysCount) return 'bearish';
    return 'mixed';
  }, [data]);

  const handleTimeframeClick = (timeframe: string) => {
    onTimeframeSelect(timeframe);
  };

  const handleCardHover = (timeframe: string | null) => {
    setHoveredTimeframe(timeframe);
  };

  return (
    <div className={`${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold mb-1" style={{ color: theme.text }}>
            Multi-Timeframe Analysis
          </h2>
          <p className="text-sm" style={{ color: theme.textSecondary }}>
            {currentPair} · Overall sentiment: <span className="font-semibold capitalize">{overallSentiment}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-green-500" />
          <span className="text-sm font-medium text-green-500">Real-time</span>
        </div>
      </div>

      {/* Timeframe Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-6">
        {sortedData.map((timeframe) => (
          <div
            key={timeframe.timeframe}
            className={`
              relative p-4 rounded-lg border transition-all duration-300 cursor-pointer overflow-hidden
              ${selectedTimeframe === timeframe.timeframe ? 'ring-2 ring-blue-500' : ''}
              hover:shadow-lg hover:-translate-y-1
            `}
            style={{
              backgroundColor: selectedTimeframe === timeframe.timeframe ? theme.background : theme.surface,
              borderColor: selectedTimeframe === timeframe.timeframe ? theme.sageLight : theme.border,
              boxShadow: selectedTimeframe === timeframe.timeframe ? `0 4px 16px ${theme.sageLight}20` : undefined
            }}
            onClick={() => handleTimeframeClick(timeframe.timeframe)}
            onMouseEnter={() => handleCardHover(timeframe.timeframe)}
            onMouseLeave={() => handleCardHover(null)}
          >
            {/* Card Header */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4" style={{ color: theme.textSecondary }} />
                <span className="text-lg font-bold" style={{ color: theme.text }}>
                  {timeframe.timeframe}
                </span>
              </div>
              <TrendIndicator 
                trend={timeframe.trend} 
                strength={timeframe.strength} 
                theme={theme}
                size="small"
              />
            </div>

            {/* Strength Gauge */}
            <div className="mb-4">
              <StrengthGauge 
                strength={timeframe.strength}
                trend={timeframe.trend}
                theme={theme}
                size="normal"
              />
            </div>

            {/* Key Levels */}
            <div className="mb-4">
              <KeyLevels 
                support={timeframe.support}
                resistance={timeframe.resistance}
                currentPrice={timeframe.price}
                theme={theme}
                precision={5}
              />
            </div>

            {/* Volatility Indicator */}
            <div className="mb-3">
              <VolatilityIndicator 
                volatility={timeframe.volatility}
                theme={theme}
                size="small"
              />
            </div>

            {/* Additional Details */}
            {showDetails && (
              <div className="space-y-2 pt-3 border-t" style={{ borderColor: theme.border }}>
                <div className="flex justify-between items-center text-xs">
                  <span style={{ color: theme.textSecondary }}>Volume:</span>
                  <span className="font-mono" style={{ color: theme.text }}>
                    {timeframe.volume.toLocaleString()}
                  </span>
                </div>
                
                {timeframe.change && (
                  <div className="flex justify-between items-center text-xs">
                    <span style={{ color: theme.textSecondary }}>Change:</span>
                    <div className={`flex items-center gap-1 font-mono ${
                      timeframe.change > 0 ? 'text-green-500' : 'text-red-500'
                    }`}>
                      {timeframe.change > 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                      <span>{timeframe.change > 0 ? '+' : ''}{timeframe.change.toFixed(4)}</span>
                      <span>({timeframe.changePercent?.toFixed(2)}%)</span>
                    </div>
                  </div>
                )}
                
                {timeframe.lastUpdated && (
                  <div className="text-xs" style={{ color: theme.textSecondary }}>
                    Updated: {timeframe.lastUpdated}
                  </div>
                )}
              </div>
            )}

            {/* Hover Overlay */}
            {hoveredTimeframe === timeframe.timeframe && (
              <div 
                className="absolute inset-0 pointer-events-none transition-opacity duration-200"
                style={{ backgroundColor: theme.hoverOverlay }}
              />
            )}

            {/* Selection Indicator */}
            {selectedTimeframe === timeframe.timeframe && (
              <div 
                className="absolute top-2 right-2 w-3 h-3 rounded-full"
                style={{ backgroundColor: theme.sageLight }}
              />
            )}
          </div>
        ))}
      </div>

      {/* Summary Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div 
          className="p-4 rounded-lg border"
          style={{ 
            backgroundColor: theme.surface,
            borderColor: theme.border
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-green-500" />
            <span className="text-sm font-medium" style={{ color: theme.textSecondary }}>
              Bullish Timeframes
            </span>
          </div>
          <div className="text-2xl font-bold" style={{ color: theme.text }}>
            {data.filter(d => d.trend === 'bullish').length}
          </div>
          <div className="text-xs mt-1" style={{ color: theme.textSecondary }}>
            out of {data.length} timeframes
          </div>
        </div>

        <div 
          className="p-4 rounded-lg border"
          style={{ 
            backgroundColor: theme.surface,
            borderColor: theme.border
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-4 h-4" style={{ color: theme.textSecondary }} />
            <span className="text-sm font-medium" style={{ color: theme.textSecondary }}>
              Avg Strength
            </span>
          </div>
          <div className="text-2xl font-bold" style={{ color: theme.text }}>
            {(data.reduce((sum, d) => sum + d.strength, 0) / data.length).toFixed(0)}%
          </div>
          <div className="text-xs mt-1" style={{ color: theme.textSecondary }}>
            across all timeframes
          </div>
        </div>

        <div 
          className="p-4 rounded-lg border"
          style={{ 
            backgroundColor: theme.surface,
            borderColor: theme.border
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4" style={{ color: theme.goldLight }} />
            <span className="text-sm font-medium" style={{ color: theme.textSecondary }}>
              Avg Volatility
            </span>
          </div>
          <div className="text-2xl font-bold" style={{ color: theme.text }}>
            {(data.reduce((sum, d) => sum + d.volatility, 0) / data.length).toFixed(1)}%
          </div>
          <div className="text-xs mt-1" style={{ color: theme.textSecondary }}>
            market volatility
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
};