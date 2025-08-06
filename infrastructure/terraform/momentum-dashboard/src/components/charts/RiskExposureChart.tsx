import React, { useMemo, useState, useEffect } from 'react';
import { AlertTriangle, Shield, TrendingUp, TrendingDown, Target, Activity, DollarSign } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';

interface RiskExposureData {
  currency: string;
  exposure: number; // Percentage of portfolio
  risk: 'low' | 'medium' | 'high' | 'extreme';
  var: number; // Value at Risk
  expectedReturn: number;
  correlation: number;
  volatility?: number;
  lastUpdated?: string;
}

interface RiskExposureChartProps {
  data: RiskExposureData[];
  totalPortfolioValue: number;
  riskTolerance: number;
  showCorrelations?: boolean;
  showTooltips?: boolean;
  onExposureClick?: (currency: string) => void;
  className?: string;
}

// Risk level indicator component
const RiskIndicator = ({ risk, theme }: { risk: string; theme: any }) => {
  const getRiskConfig = (riskLevel: string) => {
    switch (riskLevel) {
      case 'low':
        return { 
          color: theme.bullishPrimary, 
          icon: Shield, 
          label: 'Low',
          bgColor: `${theme.bullishPrimary}20`
        };
      case 'medium':
        return { 
          color: theme.goldLight, 
          icon: Target, 
          label: 'Medium',
          bgColor: `${theme.goldLight}20`
        };
      case 'high':
        return { 
          color: theme.bearishSecondary, 
          icon: AlertTriangle, 
          label: 'High',
          bgColor: `${theme.bearishSecondary}20`
        };
      case 'extreme':
        return { 
          color: theme.bearishPrimary, 
          icon: AlertTriangle, 
          label: 'Extreme',
          bgColor: `${theme.bearishPrimary}20`
        };
      default:
        return { 
          color: theme.neutralMedium, 
          icon: Shield, 
          label: 'Unknown',
          bgColor: `${theme.neutralMedium}20`
        };
    }
  };

  const config = getRiskConfig(risk);
  const Icon = config.icon;

  return (
    <div 
      className="flex items-center gap-2 px-2 py-1 rounded-md text-xs font-semibold"
      style={{ backgroundColor: config.bgColor, color: config.color }}
    >
      <Icon className="w-3 h-3" />
      <span>{config.label}</span>
    </div>
  );
};

// Animated progress bar component
const AnimatedProgressBar = ({ 
  value, 
  maxValue, 
  color, 
  height = 48, 
  animated = true,
  showValue = true,
  currency,
  theme
}: { 
  value: number; 
  maxValue: number; 
  color: string; 
  height?: number;
  animated?: boolean;
  showValue?: boolean;
  currency: string;
  theme: any;
}) => {
  const [animatedValue, setAnimatedValue] = useState(0);
  const percentage = (value / maxValue) * 100;

  useEffect(() => {
    if (animated) {
      const timer = setTimeout(() => {
        setAnimatedValue(percentage);
      }, 100);
      return () => clearTimeout(timer);
    } else {
      setAnimatedValue(percentage);
    }
  }, [percentage, animated]);

  return (
    <div 
      className="relative rounded-lg overflow-hidden border"
      style={{ 
        height: `${height}px`,
        backgroundColor: theme.surface,
        borderColor: theme.border
      }}
    >
      <div 
        className="h-full transition-all duration-1000 ease-out flex items-center justify-between px-4 relative"
        style={{ 
          width: `${animatedValue}%`,
          background: color,
          minWidth: showValue ? '120px' : '0px'
        }}
      >
        <div className="flex items-center gap-2 text-white font-semibold">
          <span className="text-sm">{currency}</span>
        </div>
        
        {showValue && (
          <div className="text-white font-bold font-mono">
            {value.toFixed(1)}%
          </div>
        )}

        {/* Animated shimmer effect */}
        <div 
          className="absolute top-0 right-0 w-0.5 h-full bg-white opacity-60"
          style={{
            animation: animated ? 'pulse 2s infinite' : 'none'
          }}
        />
      </div>
    </div>
  );
};

// Portfolio summary component
const PortfolioSummary = ({ 
  data, 
  totalValue, 
  riskTolerance, 
  theme 
}: { 
  data: RiskExposureData[]; 
  totalValue: number; 
  riskTolerance: number; 
  theme: any;
}) => {
  const summary = useMemo(() => {
    const totalExposure = data.reduce((sum, item) => sum + item.exposure, 0);
    const totalVaR = data.reduce((sum, item) => sum + item.var, 0);
    const avgReturn = data.reduce((sum, item) => sum + item.expectedReturn * (item.exposure / 100), 0);
    const highRiskCount = data.filter(item => item.risk === 'high' || item.risk === 'extreme').length;
    
    return {
      totalExposure,
      totalVaR,
      avgReturn,
      highRiskCount,
      riskUtilization: (totalVaR / riskTolerance) * 100
    };
  }, [data, riskTolerance]);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div 
        className="p-4 rounded-lg border"
        style={{ 
          backgroundColor: theme.surface,
          borderColor: theme.border
        }}
      >
        <div className="flex items-center gap-2 mb-2">
          <DollarSign className="w-4 h-4" style={{ color: theme.textSecondary }} />
          <span className="text-sm font-medium" style={{ color: theme.textSecondary }}>
            Portfolio Value
          </span>
        </div>
        <div className="text-2xl font-bold font-mono" style={{ color: theme.text }}>
          ${totalValue.toLocaleString()}
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
            Total Exposure
          </span>
        </div>
        <div className="text-2xl font-bold font-mono" style={{ color: theme.text }}>
          {summary.totalExposure.toFixed(1)}%
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
          <AlertTriangle className="w-4 h-4" style={{ color: theme.bearishSecondary }} />
          <span className="text-sm font-medium" style={{ color: theme.textSecondary }}>
            Value at Risk
          </span>
        </div>
        <div className="text-2xl font-bold font-mono text-red-500">
          ${summary.totalVaR.toLocaleString()}
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
          <TrendingUp className="w-4 h-4" style={{ color: theme.bullishSecondary }} />
          <span className="text-sm font-medium" style={{ color: theme.textSecondary }}>
            Expected Return
          </span>
        </div>
        <div className="text-2xl font-bold font-mono" style={{ color: theme.bullishSecondary }}>
          {summary.avgReturn.toFixed(2)}%
        </div>
      </div>
    </div>
  );
};

export const RiskExposureChart: React.FC<RiskExposureChartProps> = ({
  data,
  totalPortfolioValue,
  riskTolerance,
  showCorrelations = false,
  showTooltips = true,
  onExposureClick,
  className = ''
}) => {
  const { effectiveTheme } = useTheme();
  const [hoveredItem, setHoveredItem] = useState<RiskExposureData | null>(null);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });

  const theme = useMemo(() => ({
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
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

  const getRiskGradient = (risk: string) => {
    switch (risk) {
      case 'low':
        return `linear-gradient(90deg, ${theme.bullishTertiary}, ${theme.bullishSecondary})`;
      case 'medium':
        return `linear-gradient(90deg, ${theme.goldLight}, ${theme.goldLight}dd)`;
      case 'high':
        return `linear-gradient(90deg, ${theme.bearishTertiary}, ${theme.bearishSecondary})`;
      case 'extreme':
        return `linear-gradient(90deg, ${theme.bearishSecondary}, ${theme.bearishPrimary})`;
      default:
        return `linear-gradient(90deg, ${theme.neutralMedium}, ${theme.neutralMedium}dd)`;
    }
  };

  const maxExposure = Math.max(...data.map(item => item.exposure));
  const sortedData = [...data].sort((a, b) => b.exposure - a.exposure);

  const handleMouseMove = (e: React.MouseEvent, item: RiskExposureData) => {
    if (!showTooltips) return;
    
    setMousePosition({
      x: e.clientX + 10,
      y: e.clientY - 10
    });
    setHoveredItem(item);
  };

  const handleMouseLeave = () => {
    setHoveredItem(null);
  };

  const handleExposureClick = (currency: string) => {
    if (onExposureClick) {
      onExposureClick(currency);
    }
  };

  return (
    <div className={`${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold mb-1" style={{ color: theme.text }}>
            Risk Exposure Analysis
          </h2>
          <p className="text-sm" style={{ color: theme.textSecondary }}>
            Portfolio risk distribution and exposure management
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-green-500" />
          <span className="text-sm font-medium text-green-500">Live</span>
        </div>
      </div>

      {/* Portfolio Summary */}
      <PortfolioSummary 
        data={data}
        totalValue={totalPortfolioValue}
        riskTolerance={riskTolerance}
        theme={theme}
      />

      {/* Risk Exposure Chart */}
      <div 
        className="p-6 rounded-lg border"
        style={{ 
          backgroundColor: theme.background,
          borderColor: theme.border
        }}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold" style={{ color: theme.text }}>
            Currency Exposure Distribution
          </h3>
          <div className="text-sm" style={{ color: theme.textSecondary }}>
            Max exposure: {maxExposure.toFixed(1)}%
          </div>
        </div>

        <div className="space-y-4">
          {sortedData.map((item, index) => (
            <div 
              key={item.currency}
              className="relative group"
              onMouseMove={(e) => handleMouseMove(e, item)}
              onMouseLeave={handleMouseLeave}
              onClick={() => handleExposureClick(item.currency)}
            >
              {/* Currency label and risk indicator */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-sm" style={{ color: theme.text }}>
                    {item.currency}
                  </span>
                  <RiskIndicator risk={item.risk} theme={theme} />
                </div>
                <div className="flex items-center gap-4 text-sm">
                  <div style={{ color: theme.textSecondary }}>
                    VaR: <span className="font-mono text-red-500">${item.var.toLocaleString()}</span>
                  </div>
                  <div style={{ color: theme.textSecondary }}>
                    Return: <span className={`font-mono ${item.expectedReturn > 0 ? 'text-green-500' : 'text-red-500'}`}>
                      {item.expectedReturn > 0 ? '+' : ''}{item.expectedReturn.toFixed(2)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Exposure bar */}
              <AnimatedProgressBar 
                value={item.exposure}
                maxValue={maxExposure}
                color={getRiskGradient(item.risk)}
                currency={item.currency}
                theme={theme}
                height={48}
                animated={true}
                showValue={true}
              />

              {/* Correlation indicator */}
              {showCorrelations && (
                <div className="mt-2 flex items-center justify-between text-xs">
                  <span style={{ color: theme.textSecondary }}>
                    Correlation: {item.correlation.toFixed(2)}
                  </span>
                  {item.volatility && (
                    <span style={{ color: theme.textSecondary }}>
                      Volatility: {item.volatility.toFixed(1)}%
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Risk Distribution Summary */}
      <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4">
        {['low', 'medium', 'high', 'extreme'].map((riskLevel) => {
          const count = data.filter(item => item.risk === riskLevel).length;
          const totalExposure = data
            .filter(item => item.risk === riskLevel)
            .reduce((sum, item) => sum + item.exposure, 0);
          
          return (
            <div 
              key={riskLevel}
              className="p-4 rounded-lg border text-center"
              style={{ 
                backgroundColor: theme.surface,
                borderColor: theme.border
              }}
            >
              <RiskIndicator risk={riskLevel} theme={theme} />
              <div className="mt-2">
                <div className="text-2xl font-bold font-mono" style={{ color: theme.text }}>
                  {count}
                </div>
                <div className="text-sm" style={{ color: theme.textSecondary }}>
                  {totalExposure.toFixed(1)}% exposure
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Tooltip */}
      {showTooltips && hoveredItem && (
        <div 
          className="fixed z-50 max-w-80 p-4 rounded-lg border backdrop-blur-sm transition-all duration-200"
          style={{
            left: mousePosition.x,
            top: mousePosition.y,
            backgroundColor: theme.background,
            borderColor: theme.border,
            color: theme.text,
            boxShadow: '0 12px 24px rgba(0, 0, 0, 0.2)'
          }}
        >
          <div className="flex items-center justify-between mb-3 pb-2 border-b" style={{ borderColor: theme.border }}>
            <h3 className="font-semibold">{hoveredItem.currency}</h3>
            <RiskIndicator risk={hoveredItem.risk} theme={theme} />
          </div>
          
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-sm" style={{ color: theme.textSecondary }}>Portfolio Exposure:</span>
              <span className="font-mono font-bold">{hoveredItem.exposure.toFixed(1)}%</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sm" style={{ color: theme.textSecondary }}>Value at Risk:</span>
              <span className="font-mono font-bold text-red-500">${hoveredItem.var.toLocaleString()}</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sm" style={{ color: theme.textSecondary }}>Expected Return:</span>
              <span className={`font-mono font-bold ${hoveredItem.expectedReturn > 0 ? 'text-green-500' : 'text-red-500'}`}>
                {hoveredItem.expectedReturn > 0 ? '+' : ''}{hoveredItem.expectedReturn.toFixed(2)}%
              </span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sm" style={{ color: theme.textSecondary }}>Correlation:</span>
              <span className="font-mono text-sm">{hoveredItem.correlation.toFixed(2)}</span>
            </div>
            
            {hoveredItem.volatility && (
              <div className="flex justify-between items-center">
                <span className="text-sm" style={{ color: theme.textSecondary }}>Volatility:</span>
                <span className="font-mono text-sm">{hoveredItem.volatility.toFixed(1)}%</span>
              </div>
            )}
            
            {hoveredItem.lastUpdated && (
              <div className="flex justify-between items-center pt-2 border-t" style={{ borderColor: theme.border }}>
                <span className="text-xs" style={{ color: theme.textSecondary }}>Last Updated:</span>
                <span className="font-mono text-xs">{hoveredItem.lastUpdated}</span>
              </div>
            )}
          </div>
        </div>
      )}

      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
};