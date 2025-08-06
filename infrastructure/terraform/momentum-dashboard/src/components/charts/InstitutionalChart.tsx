import React, { useMemo, useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';
import { useTheme } from '../../contexts/ThemeContext';
import { TrendingUp, TrendingDown, Activity, BarChart3, Settings, Download } from 'lucide-react';

interface ChartData {
  timestamp: string;
  value: number;
  volume?: number;
  high?: number;
  low?: number;
  open?: number;
  close?: number;
}

interface InstitutionalChartProps {
  data: ChartData[];
  title: string;
  subtitle?: string;
  type: 'line' | 'area' | 'candlestick' | 'volume';
  height?: number;
  showControls?: boolean;
  showGrid?: boolean;
  animated?: boolean;
  precision?: number;
}

// Professional chart theme configuration
const getChartTheme = (effectiveTheme: 'light' | 'dark') => ({
  light: {
    background: '#FFFFFF',
    surface: '#F9F9F9',
    grid: '#F3F4F6',
    text: '#1D1E1F',
    textSecondary: '#6B7280',
    textMuted: '#9CA3AF',
    border: '#E5E5E5',
    positive: '#059669',
    negative: '#DC2626',
    accent: '#3B82F6',
    volume: '#8B5CF6',
    tooltip: {
      background: '#FFFFFF',
      border: '#E5E5E5',
      shadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
    }
  },
  dark: {
    background: '#1E1E1E',
    surface: '#2C2C2C',
    grid: '#374151',
    text: '#F1F1F1',
    textSecondary: '#B3B3B3',
    textMuted: '#8A8A8A',
    border: '#3B3B3B',
    positive: '#10B981',
    negative: '#F87171',
    accent: '#60A5FA',
    volume: '#A78BFA',
    tooltip: {
      background: '#1E1E1E',
      border: '#3B3B3B',
      shadow: '0 4px 6px -1px rgba(0, 0, 0, 0.3)'
    }
  }
})[effectiveTheme];

// Custom tooltip component
const CustomTooltip = ({ active, payload, label, theme, precision = 4 }: any) => {
  if (!active || !payload || !payload.length) return null;

  const data = payload[0].payload;
  const value = payload[0].value;
  const trend = data.close > data.open ? 'up' : 'down';

  return (
    <div 
      className="p-4 rounded-lg border backdrop-blur-sm"
      style={{
        backgroundColor: theme.tooltip.background,
        borderColor: theme.tooltip.border,
        boxShadow: theme.tooltip.shadow,
        color: theme.text
      }}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="text-sm font-medium">{label}</div>
        {data.close && (
          <div className={`flex items-center gap-1 text-xs ${
            trend === 'up' ? 'text-green-500' : 'text-red-500'
          }`}>
            {trend === 'up' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
            <span>{((data.close - data.open) / data.open * 100).toFixed(2)}%</span>
          </div>
        )}
      </div>
      
      <div className="space-y-1">
        {data.open && (
          <div className="flex justify-between gap-4 text-sm">
            <span style={{ color: theme.textSecondary }}>Open:</span>
            <span className="font-mono">{data.open.toFixed(precision)}</span>
          </div>
        )}
        {data.high && (
          <div className="flex justify-between gap-4 text-sm">
            <span style={{ color: theme.textSecondary }}>High:</span>
            <span className="font-mono" style={{ color: theme.positive }}>{data.high.toFixed(precision)}</span>
          </div>
        )}
        {data.low && (
          <div className="flex justify-between gap-4 text-sm">
            <span style={{ color: theme.textSecondary }}>Low:</span>
            <span className="font-mono" style={{ color: theme.negative }}>{data.low.toFixed(precision)}</span>
          </div>
        )}
        {data.close && (
          <div className="flex justify-between gap-4 text-sm">
            <span style={{ color: theme.textSecondary }}>Close:</span>
            <span className="font-mono font-medium">{data.close.toFixed(precision)}</span>
          </div>
        )}
        {data.volume && (
          <div className="flex justify-between gap-4 text-sm">
            <span style={{ color: theme.textSecondary }}>Volume:</span>
            <span className="font-mono" style={{ color: theme.volume }}>{data.volume.toLocaleString()}</span>
          </div>
        )}
        {!data.close && (
          <div className="flex justify-between gap-4 text-sm">
            <span style={{ color: theme.textSecondary }}>Value:</span>
            <span className="font-mono font-medium">{value.toFixed(precision)}</span>
          </div>
        )}
      </div>
    </div>
  );
};

// Chart controls component
const ChartControls = ({ theme, onExport }: { theme: any; onExport: () => void }) => (
  <div className="flex items-center gap-2">
    <button
      onClick={onExport}
      className="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
      style={{ color: theme.textSecondary }}
      title="Export chart"
    >
      <Download className="w-4 h-4" />
    </button>
    <button
      className="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
      style={{ color: theme.textSecondary }}
      title="Chart settings"
    >
      <Settings className="w-4 h-4" />
    </button>
  </div>
);

export const InstitutionalChart: React.FC<InstitutionalChartProps> = ({
  data,
  title,
  subtitle,
  type,
  height = 400,
  showControls = true,
  showGrid = true,
  animated = true,
  precision = 4
}) => {
  const { effectiveTheme } = useTheme();
  const [isAnimated, setIsAnimated] = useState(animated);
  const theme = useMemo(() => getChartTheme(effectiveTheme), [effectiveTheme]);

  // Calculate trend and performance metrics
  const metrics = useMemo(() => {
    if (!data || data.length === 0) return null;
    
    const first = data[0];
    const last = data[data.length - 1];
    const change = last.value - first.value;
    const percentChange = ((last.value - first.value) / first.value) * 100;
    const trend = change > 0 ? 'up' : 'down';
    
    return {
      current: last.value,
      change,
      percentChange,
      trend,
      high: Math.max(...data.map(d => d.high || d.value)),
      low: Math.min(...data.map(d => d.low || d.value)),
    };
  }, [data]);

  const handleExport = () => {
    // Implementation for chart export
    console.log('Exporting chart...');
  };

  useEffect(() => {
    if (animated) {
      setIsAnimated(false);
      const timer = setTimeout(() => setIsAnimated(true), 100);
      return () => clearTimeout(timer);
    }
  }, [effectiveTheme, animated]);

  const renderChart = () => {
    const commonProps = {
      width: '100%',
      height,
      data,
      margin: { top: 20, right: 30, left: 20, bottom: 20 }
    };

    switch (type) {
      case 'area':
        return (
          <ResponsiveContainer {...commonProps}>
            <AreaChart data={data}>
              {showGrid && (
                <CartesianGrid 
                  strokeDasharray="3 3" 
                  stroke={theme.grid}
                  opacity={0.7}
                />
              )}
              <XAxis 
                dataKey="timestamp" 
                stroke={theme.textMuted}
                fontSize={12}
                tickLine={false}
                axisLine={false}
              />
              <YAxis 
                stroke={theme.textMuted}
                fontSize={12}
                tickLine={false}
                axisLine={false}
                domain={['dataMin * 0.999', 'dataMax * 1.001']}
              />
              <Tooltip 
                content={<CustomTooltip theme={theme} precision={precision} />}
                cursor={{ stroke: theme.accent, strokeWidth: 1, strokeDasharray: '3 3' }}
              />
              <Area 
                type="monotone" 
                dataKey="value" 
                stroke={theme.accent}
                strokeWidth={2}
                fill={theme.accent}
                fillOpacity={0.1}
                isAnimationActive={isAnimated}
                animationDuration={800}
                animationBegin={0}
              />
            </AreaChart>
          </ResponsiveContainer>
        );

      case 'line':
      default:
        return (
          <ResponsiveContainer {...commonProps}>
            <LineChart data={data}>
              {showGrid && (
                <CartesianGrid 
                  strokeDasharray="3 3" 
                  stroke={theme.grid}
                  opacity={0.7}
                />
              )}
              <XAxis 
                dataKey="timestamp" 
                stroke={theme.textMuted}
                fontSize={12}
                tickLine={false}
                axisLine={false}
              />
              <YAxis 
                stroke={theme.textMuted}
                fontSize={12}
                tickLine={false}
                axisLine={false}
                domain={['dataMin * 0.999', 'dataMax * 1.001']}
              />
              <Tooltip 
                content={<CustomTooltip theme={theme} precision={precision} />}
                cursor={{ stroke: theme.accent, strokeWidth: 1, strokeDasharray: '3 3' }}
              />
              <Line 
                type="monotone" 
                dataKey="value" 
                stroke={theme.accent}
                strokeWidth={2}
                dot={{ r: 4, fill: theme.accent }}
                activeDot={{ r: 6, fill: theme.accent }}
                isAnimationActive={isAnimated}
                animationDuration={800}
                animationBegin={0}
              />
            </LineChart>
          </ResponsiveContainer>
        );
    }
  };

  if (!data || data.length === 0) {
    return (
      <div 
        className="rounded-lg border p-8 text-center"
        style={{ 
          backgroundColor: theme.background,
          borderColor: theme.border,
          color: theme.textMuted
        }}
      >
        <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p>No data available</p>
      </div>
    );
  }

  return (
    <div 
      className="rounded-lg border transition-all duration-300 hover:shadow-lg"
      style={{ 
        backgroundColor: theme.background,
        borderColor: theme.border 
      }}
    >
      {/* Chart Header */}
      <div className="flex items-start justify-between p-6 border-b" style={{ borderColor: theme.border }}>
        <div className="flex-1">
          <h3 className="text-lg font-semibold mb-1" style={{ color: theme.text }}>
            {title}
          </h3>
          {subtitle && (
            <p className="text-sm" style={{ color: theme.textSecondary }}>
              {subtitle}
            </p>
          )}
          
          {/* Metrics */}
          {metrics && (
            <div className="flex items-center gap-4 mt-3">
              <div className="flex items-center gap-2">
                <span className="text-2xl font-bold font-mono" style={{ color: theme.text }}>
                  {metrics.current.toFixed(precision)}
                </span>
                <div className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${
                  metrics.trend === 'up' 
                    ? 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-400' 
                    : 'bg-red-100 dark:bg-red-900/20 text-red-700 dark:text-red-400'
                }`}>
                  {metrics.trend === 'up' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  <span>{metrics.percentChange.toFixed(2)}%</span>
                </div>
              </div>
              
              <div className="flex items-center gap-4 text-sm" style={{ color: theme.textSecondary }}>
                <div>
                  <span className="opacity-75">H:</span>
                  <span className="font-mono ml-1" style={{ color: theme.positive }}>
                    {metrics.high.toFixed(precision)}
                  </span>
                </div>
                <div>
                  <span className="opacity-75">L:</span>
                  <span className="font-mono ml-1" style={{ color: theme.negative }}>
                    {metrics.low.toFixed(precision)}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
        
        {showControls && <ChartControls theme={theme} onExport={handleExport} />}
      </div>
      
      {/* Chart Body */}
      <div className="p-6">
        {renderChart()}
      </div>
    </div>
  );
};