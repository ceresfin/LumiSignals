import React, { useMemo, useState } from 'react';
import { TrendingUp, TrendingDown, Minus, Trophy, Clock, Activity } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';

interface CurrencyStrengthData {
  currency: string;
  strength: number; // -100 to 100
  trend: 'strengthening' | 'weakening' | 'stable';
  volatility: number;
  rank: number;
  previousStrength?: number;
  volume?: number;
}

interface CurrencyStrengthMatrixProps {
  data: CurrencyStrengthData[];
  timeframe: '1H' | '4H' | '1D' | '1W';
  showRankings?: boolean;
  interactive?: boolean;
  onCurrencyClick?: (currency: string) => void;
  className?: string;
}

// Professional tooltip component
const CurrencyTooltip = ({ 
  currency, 
  visible, 
  position, 
  theme 
}: { 
  currency: CurrencyStrengthData; 
  visible: boolean; 
  position: { x: number; y: number }; 
  theme: any;
}) => {
  if (!visible) return null;

  const strengthChange = currency.previousStrength 
    ? currency.strength - currency.previousStrength 
    : 0;

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
        <h3 className="font-semibold text-lg">{currency.currency}</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs px-2 py-1 rounded-full bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300">
            Rank #{currency.rank}
          </span>
        </div>
      </div>
      
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Strength:</span>
          <span className="font-mono font-bold text-lg">{currency.strength.toFixed(1)}</span>
        </div>
        
        {strengthChange !== 0 && (
          <div className="flex justify-between items-center">
            <span className="text-sm" style={{ color: theme.textSecondary }}>Change:</span>
            <div className={`flex items-center gap-1 ${
              strengthChange > 0 ? 'text-green-500' : 'text-red-500'
            }`}>
              {strengthChange > 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
              <span className="font-mono text-sm">{strengthChange > 0 ? '+' : ''}{strengthChange.toFixed(1)}</span>
            </div>
          </div>
        )}
        
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Volatility:</span>
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {[...Array(5)].map((_, i) => (
                <div 
                  key={i}
                  className={`w-2 h-2 rounded-full ${
                    i < Math.floor(currency.volatility / 20) 
                      ? 'bg-yellow-400' 
                      : 'bg-gray-300 dark:bg-gray-600'
                  }`}
                />
              ))}
            </div>
            <span className="font-mono text-sm">{currency.volatility.toFixed(1)}%</span>
          </div>
        </div>
        
        <div className="flex justify-between items-center">
          <span className="text-sm" style={{ color: theme.textSecondary }}>Trend:</span>
          <div className={`flex items-center gap-1 capitalize ${
            currency.trend === 'strengthening' ? 'text-green-500' : 
            currency.trend === 'weakening' ? 'text-red-500' : 'text-gray-500'
          }`}>
            {currency.trend === 'strengthening' ? <TrendingUp className="w-3 h-3" /> : 
             currency.trend === 'weakening' ? <TrendingDown className="w-3 h-3" /> : 
             <Minus className="w-3 h-3" />}
            <span className="text-sm font-medium">{currency.trend}</span>
          </div>
        </div>
        
        {currency.volume && (
          <div className="flex justify-between items-center">
            <span className="text-sm" style={{ color: theme.textSecondary }}>Volume:</span>
            <span className="font-mono text-sm">{currency.volume.toLocaleString()}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export const CurrencyStrengthMatrix: React.FC<CurrencyStrengthMatrixProps> = ({
  data,
  timeframe,
  showRankings = true,
  interactive = true,
  onCurrencyClick,
  className = ''
}) => {
  const { effectiveTheme } = useTheme();
  const [hoveredCurrency, setHoveredCurrency] = useState<CurrencyStrengthData | null>(null);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });

  const theme = useMemo(() => ({
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
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
      neutralMedium: '#6b7280',
      neutralWeak: '#9ca3af',
      hoverOverlay: 'rgba(0, 0, 0, 0.05)'
    },
    dark: {
      background: '#111827',
      surface: '#1f2937',
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
      neutralMedium: '#d1d5db',
      neutralWeak: '#9ca3af',
      hoverOverlay: 'rgba(255, 255, 255, 0.05)'
    }
  })[effectiveTheme], [effectiveTheme]);

  const getStrengthCategory = (strength: number): string => {
    if (strength >= 60) return 'strength-very-strong';
    if (strength >= 20) return 'strength-strong';
    if (strength >= -20) return 'strength-neutral';
    if (strength >= -60) return 'strength-weak';
    return 'strength-very-weak';
  };

  const getStrengthColors = (strength: number) => {
    if (strength >= 60) return {
      background: `linear-gradient(135deg, ${theme.bullishPrimary}, ${theme.bullishSecondary})`,
      color: 'white',
      boxShadow: `0 4px 12px ${theme.bullishPrimary}30`
    };
    if (strength >= 20) return {
      background: `linear-gradient(135deg, ${theme.bullishSecondary}, ${theme.bullishTertiary})`,
      color: 'white',
      boxShadow: `0 4px 12px ${theme.bullishSecondary}20`
    };
    if (strength >= -20) return {
      background: `linear-gradient(135deg, ${theme.neutralMedium}, ${theme.neutralWeak})`,
      color: theme.text,
      boxShadow: '0 2px 6px rgba(0, 0, 0, 0.1)'
    };
    if (strength >= -60) return {
      background: `linear-gradient(135deg, ${theme.bearishTertiary}, ${theme.bearishSecondary})`,
      color: 'white',
      boxShadow: `0 4px 12px ${theme.bearishSecondary}20`
    };
    return {
      background: `linear-gradient(135deg, ${theme.bearishSecondary}, ${theme.bearishPrimary})`,
      color: 'white',
      boxShadow: `0 4px 12px ${theme.bearishPrimary}30`
    };
  };

  const sortedData = useMemo(() => {
    return [...data].sort((a, b) => b.strength - a.strength);
  }, [data]);

  const handleMouseMove = (e: React.MouseEvent, currency: CurrencyStrengthData) => {
    if (!interactive) return;
    
    setMousePosition({
      x: e.clientX + 10,
      y: e.clientY - 10
    });
    setHoveredCurrency(currency);
  };

  const handleMouseLeave = () => {
    setHoveredCurrency(null);
  };

  const handleCurrencyClick = (currency: string) => {
    if (interactive && onCurrencyClick) {
      onCurrencyClick(currency);
    }
  };

  return (
    <div className={`${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold mb-1" style={{ color: theme.text }}>
            Currency Strength Matrix
          </h2>
          <p className="text-sm" style={{ color: theme.textSecondary }}>
            Real-time strength analysis across major currencies
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-blue-100 dark:bg-blue-900/20">
            <Clock className="w-4 h-4 text-blue-600 dark:text-blue-400" />
            <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
              {timeframe}
            </span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-green-100 dark:bg-green-900/20">
            <Activity className="w-4 h-4 text-green-600 dark:text-green-400" />
            <span className="text-sm font-medium text-green-700 dark:text-green-300">
              Live
            </span>
          </div>
        </div>
      </div>

      {/* Currency Matrix */}
      <div 
        className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 p-6 rounded-lg border"
        style={{ 
          backgroundColor: theme.background,
          borderColor: theme.border
        }}
      >
        {sortedData.map((currency, index) => {
          const strengthColors = getStrengthColors(currency.strength);
          
          return (
            <div
              key={currency.currency}
              className={`
                relative p-4 rounded-lg text-center transition-all duration-300 cursor-pointer overflow-hidden
                ${interactive ? 'hover:scale-105 hover:-translate-y-1' : ''}
              `}
              style={{
                background: strengthColors.background,
                color: strengthColors.color,
                boxShadow: strengthColors.boxShadow
              }}
              onMouseMove={(e) => handleMouseMove(e, currency)}
              onMouseLeave={handleMouseLeave}
              onClick={() => handleCurrencyClick(currency.currency)}
            >
              {/* Shimmer effect */}
              <div 
                className="absolute inset-0 opacity-0 hover:opacity-100 transition-opacity duration-500"
                style={{
                  background: 'linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent)',
                  transform: 'translateX(-100%)',
                  animation: interactive ? 'shimmer 1.5s infinite' : 'none'
                }}
              />

              {/* Rank indicator */}
              {showRankings && (
                <div className="absolute top-2 right-2 w-6 h-6 bg-black bg-opacity-20 rounded-full flex items-center justify-center">
                  {index + 1 <= 3 && <Trophy className="w-3 h-3" />}
                  {index + 1 > 3 && (
                    <span className="text-xs font-semibold">{index + 1}</span>
                  )}
                </div>
              )}

              {/* Currency Code */}
              <div className="text-xl font-bold letter-spacing-wider mb-2">
                {currency.currency}
              </div>

              {/* Strength Value */}
              <div className="text-2xl font-semibold font-mono mb-1">
                {currency.strength > 0 ? '+' : ''}{currency.strength.toFixed(1)}
              </div>

              {/* Trend Indicator */}
              <div className="flex items-center justify-center gap-1 text-xs font-medium uppercase tracking-wider opacity-90">
                {currency.trend === 'strengthening' && <TrendingUp className="w-3 h-3" />}
                {currency.trend === 'weakening' && <TrendingDown className="w-3 h-3" />}
                {currency.trend === 'stable' && <Minus className="w-3 h-3" />}
                <span>{currency.trend}</span>
              </div>

              {/* Volatility indicator */}
              <div className="absolute bottom-2 left-2 flex gap-1">
                {[...Array(3)].map((_, i) => (
                  <div 
                    key={i}
                    className={`w-1 h-1 rounded-full ${
                      i < Math.floor(currency.volatility / 33) 
                        ? 'bg-white bg-opacity-80' 
                        : 'bg-white bg-opacity-30'
                    }`}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Tooltip */}
      <CurrencyTooltip 
        currency={hoveredCurrency!}
        visible={!!hoveredCurrency}
        position={mousePosition}
        theme={theme}
      />

      {/* Legend */}
      <div className="mt-6 p-4 rounded-lg border" style={{ 
        backgroundColor: theme.surface,
        borderColor: theme.border
      }}>
        <h3 className="text-sm font-medium mb-3" style={{ color: theme.text }}>
          Strength Levels
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bullishPrimary }} />
            <span style={{ color: theme.textSecondary }}>Very Strong (60+)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bullishSecondary }} />
            <span style={{ color: theme.textSecondary }}>Strong (20-60)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.neutralMedium }} />
            <span style={{ color: theme.textSecondary }}>Neutral (-20-20)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bearishSecondary }} />
            <span style={{ color: theme.textSecondary }}>Weak (-60--20)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded" style={{ background: theme.bearishPrimary }} />
            <span style={{ color: theme.textSecondary }}>Very Weak (-60-)</span>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
};