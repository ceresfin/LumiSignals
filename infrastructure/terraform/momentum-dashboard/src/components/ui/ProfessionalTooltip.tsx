import React, { useState, useEffect, useRef } from 'react';
import { AlertCircle, TrendingUp, TrendingDown, Clock, Activity, DollarSign } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext';

interface TooltipContentItem {
  label: string;
  value: string | number;
  color?: string;
  format?: 'currency' | 'percentage' | 'number' | 'text';
  icon?: React.ReactNode;
  trend?: 'up' | 'down' | 'neutral';
}

interface TooltipData {
  title: string;
  subtitle?: string;
  content: TooltipContentItem[];
  timestamp?: string;
  status?: 'success' | 'warning' | 'error' | 'info';
  category?: string;
}

interface ProfessionalTooltipProps {
  data: TooltipData;
  position: { x: number; y: number };
  visible: boolean;
  theme?: 'light' | 'dark';
  placement?: 'top' | 'bottom' | 'left' | 'right' | 'auto';
  maxWidth?: number;
  showArrow?: boolean;
  className?: string;
}

// Format value based on type
const formatValue = (value: string | number, format?: string): string => {
  if (typeof value === 'string') return value;
  
  switch (format) {
    case 'currency':
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 2
      }).format(value);
    case 'percentage':
      return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
    case 'number':
      return value.toLocaleString();
    case 'text':
    default:
      return value.toString();
  }
};

// Status indicator component
const StatusIndicator = ({ 
  status, 
  theme 
}: { 
  status: 'success' | 'warning' | 'error' | 'info';
  theme: any;
}) => {
  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'success':
        return { color: theme.bullishPrimary, icon: Activity, label: 'Active' };
      case 'warning':
        return { color: theme.goldLight, icon: AlertCircle, label: 'Warning' };
      case 'error':
        return { color: theme.bearishPrimary, icon: AlertCircle, label: 'Error' };
      case 'info':
      default:
        return { color: theme.neutralMedium, icon: Activity, label: 'Info' };
    }
  };

  const config = getStatusConfig(status);
  const Icon = config.icon;

  return (
    <div className="flex items-center gap-2">
      <div 
        className="w-2 h-2 rounded-full flex-shrink-0"
        style={{ 
          backgroundColor: config.color,
          boxShadow: `0 0 4px ${config.color}40`
        }}
      />
      <span className="text-xs font-medium" style={{ color: config.color }}>
        {config.label}
      </span>
    </div>
  );
};

// Trend arrow component
const TrendArrow = ({ 
  trend, 
  theme 
}: { 
  trend: 'up' | 'down' | 'neutral';
  theme: any;
}) => {
  switch (trend) {
    case 'up':
      return <TrendingUp className="w-3 h-3" style={{ color: theme.bullishPrimary }} />;
    case 'down':
      return <TrendingDown className="w-3 h-3" style={{ color: theme.bearishPrimary }} />;
    case 'neutral':
    default:
      return <div className="w-3 h-3" />;
  }
};

// Hook for tooltip positioning
const useTooltipPosition = (
  position: { x: number; y: number },
  placement: string,
  tooltipRef: React.RefObject<HTMLDivElement>
) => {
  const [adjustedPosition, setAdjustedPosition] = useState(position);

  useEffect(() => {
    if (!tooltipRef.current) return;

    const tooltip = tooltipRef.current;
    const rect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let newX = position.x;
    let newY = position.y;

    // Auto-adjust position to keep tooltip in viewport
    if (placement === 'auto') {
      // Check if tooltip would overflow right edge
      if (newX + rect.width > viewportWidth) {
        newX = position.x - rect.width - 10;
      }
      
      // Check if tooltip would overflow bottom edge
      if (newY + rect.height > viewportHeight) {
        newY = position.y - rect.height - 10;
      }
      
      // Ensure minimum distance from edges
      newX = Math.max(10, Math.min(newX, viewportWidth - rect.width - 10));
      newY = Math.max(10, Math.min(newY, viewportHeight - rect.height - 10));
    }

    setAdjustedPosition({ x: newX, y: newY });
  }, [position, placement, tooltipRef]);

  return adjustedPosition;
};

export const ProfessionalTooltip: React.FC<ProfessionalTooltipProps> = ({
  data,
  position,
  visible,
  theme: themeProp,
  placement = 'auto',
  maxWidth = 320,
  showArrow = true,
  className = ''
}) => {
  const { effectiveTheme } = useTheme();
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);
  
  const theme = {
    light: {
      background: '#ffffff',
      surface: '#f9fafb',
      text: '#1f2937',
      textSecondary: '#6b7280',
      textMuted: '#9ca3af',
      border: '#e5e7eb',
      bullishPrimary: '#047857',
      bearishPrimary: '#991b1b',
      goldLight: '#a68b4a',
      neutralMedium: '#6b7280',
      shadow: '0 12px 24px rgba(0, 0, 0, 0.15)'
    },
    dark: {
      background: '#1e1e1e',
      surface: '#2c2c2c',
      text: '#f1f1f1',
      textSecondary: '#b3b3b3',
      textMuted: '#8a8a8a',
      border: '#3b3b3b',
      bullishPrimary: '#34d399',
      bearishPrimary: '#f87171',
      goldLight: '#c2a565',
      neutralMedium: '#d1d5db',
      shadow: '0 12px 24px rgba(0, 0, 0, 0.4)'
    }
  }[themeProp || effectiveTheme];

  const adjustedPosition = useTooltipPosition(position, placement, tooltipRef);

  useEffect(() => {
    if (visible) {
      setIsVisible(true);
    } else {
      const timer = setTimeout(() => setIsVisible(false), 200);
      return () => clearTimeout(timer);
    }
  }, [visible]);

  if (!isVisible) return null;

  const getArrowStyle = () => {
    if (!showArrow) return {};
    
    const arrowSize = 8;
    const arrowOffset = 20;
    
    switch (placement) {
      case 'top':
        return {
          '&::before': {
            content: '""',
            position: 'absolute',
            bottom: `-${arrowSize}px`,
            left: `${arrowOffset}px`,
            width: 0,
            height: 0,
            borderLeft: `${arrowSize}px solid transparent`,
            borderRight: `${arrowSize}px solid transparent`,
            borderTop: `${arrowSize}px solid ${theme.background}`,
          }
        };
      case 'bottom':
        return {
          '&::before': {
            content: '""',
            position: 'absolute',
            top: `-${arrowSize}px`,
            left: `${arrowOffset}px`,
            width: 0,
            height: 0,
            borderLeft: `${arrowSize}px solid transparent`,
            borderRight: `${arrowSize}px solid transparent`,
            borderBottom: `${arrowSize}px solid ${theme.background}`,
          }
        };
      default:
        return {};
    }
  };

  return (
    <div
      ref={tooltipRef}
      className={`fixed z-50 transition-all duration-200 ${className}`}
      style={{
        left: adjustedPosition.x,
        top: adjustedPosition.y,
        maxWidth: `${maxWidth}px`,
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
        pointerEvents: 'none'
      }}
    >
      <div
        className="relative p-4 rounded-lg border backdrop-blur-sm"
        style={{
          backgroundColor: theme.background,
          borderColor: theme.border,
          boxShadow: theme.shadow,
          color: theme.text
        }}
      >
        {/* Arrow */}
        {showArrow && placement === 'auto' && (
          <div
            className="absolute top-0 left-5 w-0 h-0 transform -translate-y-full"
            style={{
              borderLeft: '6px solid transparent',
              borderRight: '6px solid transparent',
              borderBottom: `6px solid ${theme.background}`,
            }}
          />
        )}

        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1">
            <h3 className="text-sm font-semibold mb-1" style={{ color: theme.text }}>
              {data.title}
            </h3>
            {data.subtitle && (
              <p className="text-xs" style={{ color: theme.textSecondary }}>
                {data.subtitle}
              </p>
            )}
          </div>
          
          {data.status && (
            <StatusIndicator status={data.status} theme={theme} />
          )}
        </div>

        {/* Category Badge */}
        {data.category && (
          <div className="mb-3">
            <span 
              className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium"
              style={{
                backgroundColor: `${theme.neutralMedium}20`,
                color: theme.neutralMedium
              }}
            >
              {data.category}
            </span>
          </div>
        )}

        {/* Content */}
        <div className="space-y-2">
          {data.content.map((item, index) => (
            <div key={index} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {item.icon && (
                  <div className="flex-shrink-0" style={{ color: theme.textSecondary }}>
                    {item.icon}
                  </div>
                )}
                <span className="text-sm" style={{ color: theme.textSecondary }}>
                  {item.label}:
                </span>
              </div>
              
              <div className="flex items-center gap-2">
                {item.trend && <TrendArrow trend={item.trend} theme={theme} />}
                <span 
                  className="text-sm font-mono font-semibold"
                  style={{ 
                    color: item.color || theme.text,
                    fontWeight: '600'
                  }}
                >
                  {formatValue(item.value, item.format)}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Timestamp */}
        {data.timestamp && (
          <div className="mt-3 pt-3 border-t" style={{ borderColor: theme.border }}>
            <div className="flex items-center gap-2 text-xs" style={{ color: theme.textMuted }}>
              <Clock className="w-3 h-3" />
              <span>{data.timestamp}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Hook for easy tooltip management
export const useTooltip = () => {
  const [tooltipData, setTooltipData] = useState<TooltipData | null>(null);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [visible, setVisible] = useState(false);

  const showTooltip = (data: TooltipData, mouseEvent: React.MouseEvent) => {
    setTooltipData(data);
    setPosition({
      x: mouseEvent.clientX + 10,
      y: mouseEvent.clientY - 10
    });
    setVisible(true);
  };

  const hideTooltip = () => {
    setVisible(false);
  };

  const updatePosition = (mouseEvent: React.MouseEvent) => {
    setPosition({
      x: mouseEvent.clientX + 10,
      y: mouseEvent.clientY - 10
    });
  };

  return {
    tooltipData,
    position,
    visible,
    showTooltip,
    hideTooltip,
    updatePosition
  };
};

// Predefined tooltip templates for common use cases
export const tooltipTemplates = {
  currency: (currency: string, strength: number, trend: string, volatility: number): TooltipData => ({
    title: currency,
    subtitle: 'Currency Analysis',
    category: 'Forex',
    status: trend === 'strengthening' ? 'success' : trend === 'weakening' ? 'warning' : 'info',
    content: [
      { label: 'Strength', value: strength, format: 'percentage', trend: trend === 'strengthening' ? 'up' : trend === 'weakening' ? 'down' : 'neutral' },
      { label: 'Volatility', value: volatility, format: 'percentage', icon: <Activity className="w-3 h-3" /> },
      { label: 'Trend', value: trend, format: 'text' }
    ],
    timestamp: new Date().toLocaleString()
  }),

  strategy: (name: string, performance: number, winRate: number, trades: number): TooltipData => ({
    title: name,
    subtitle: 'Strategy Performance',
    category: 'Trading',
    status: performance > 0 ? 'success' : 'error',
    content: [
      { label: 'Performance', value: performance, format: 'percentage', trend: performance > 0 ? 'up' : 'down' },
      { label: 'Win Rate', value: winRate, format: 'percentage' },
      { label: 'Trades', value: trades, format: 'number' }
    ],
    timestamp: new Date().toLocaleString()
  }),

  risk: (currency: string, exposure: number, var: number, expectedReturn: number): TooltipData => ({
    title: currency,
    subtitle: 'Risk Analysis',
    category: 'Risk Management',
    status: exposure > 30 ? 'warning' : 'info',
    content: [
      { label: 'Exposure', value: exposure, format: 'percentage' },
      { label: 'Value at Risk', value: var, format: 'currency', icon: <DollarSign className="w-3 h-3" /> },
      { label: 'Expected Return', value: expectedReturn, format: 'percentage', trend: expectedReturn > 0 ? 'up' : 'down' }
    ],
    timestamp: new Date().toLocaleString()
  })
};

// Example usage component
export const TooltipExample: React.FC = () => {
  const { tooltipData, position, visible, showTooltip, hideTooltip, updatePosition } = useTooltip();

  const handleMouseMove = (e: React.MouseEvent) => {
    const data = tooltipTemplates.currency('USD', 75.2, 'strengthening', 12.3);
    showTooltip(data, e);
  };

  return (
    <div className="p-8">
      <div 
        className="inline-block p-4 bg-blue-100 rounded-lg cursor-pointer"
        onMouseMove={handleMouseMove}
        onMouseLeave={hideTooltip}
      >
        Hover me for tooltip
      </div>
      
      {tooltipData && (
        <ProfessionalTooltip 
          data={tooltipData}
          position={position}
          visible={visible}
          placement="auto"
          showArrow={true}
        />
      )}
    </div>
  );
};