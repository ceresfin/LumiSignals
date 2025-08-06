import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useTheme } from '../../contexts/ThemeContext';

interface ChartData {
  timestamp: string;
  value: number;
  momentum: 'bullish' | 'bearish' | 'neutral';
}

interface DualModeChartProps {
  data: ChartData[];
  title: string;
  height?: number;
}

export const DualModeChart: React.FC<DualModeChartProps> = ({ data, title, height = 300 }) => {
  const { effectiveTheme } = useTheme();
  
  // Theme-aware chart configuration
  const chartTheme = {
    light: {
      background: '#ffffff',
      grid: '#f3f4f6',
      text: '#1f2937',
      axis: '#9ca3af',
      bullish: '#059669',
      bearish: '#dc2626',
      neutral: '#6b7280',
      tooltip: {
        background: '#ffffff',
        border: '#e5e7eb',
        text: '#1f2937'
      }
    },
    dark: {
      background: '#1f2937',
      grid: '#374151',
      text: '#f9fafb',
      axis: '#6b7280',
      bullish: '#10b981',
      bearish: '#f87171',
      neutral: '#9ca3af',
      tooltip: {
        background: '#1f2937',
        border: '#374151',
        text: '#f9fafb'
      }
    }
  };

  const theme = chartTheme[effectiveTheme];

  // Custom tooltip component
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div 
          className="p-3 rounded-lg border shadow-lg"
          style={{
            backgroundColor: theme.tooltip.background,
            borderColor: theme.tooltip.border,
            color: theme.tooltip.text
          }}
        >
          <p className="font-medium">{`Time: ${label}`}</p>
          <p className="text-sm">
            <span style={{ color: theme.bullish }}>●</span>
            {` Value: ${payload[0].value.toFixed(4)}`}
          </p>
          <p className="text-xs opacity-75">
            Momentum: {payload[0].payload.momentum}
          </p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="w-full">
      <h3 
        className="text-lg font-semibold mb-4"
        style={{ color: theme.text }}
      >
        {title}
      </h3>
      <div 
        className="rounded-lg border p-4"
        style={{
          backgroundColor: theme.background,
          borderColor: theme.grid
        }}
      >
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data}>
            <CartesianGrid 
              strokeDasharray="3 3" 
              stroke={theme.grid}
              opacity={0.7}
            />
            <XAxis 
              dataKey="timestamp" 
              stroke={theme.axis}
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis 
              stroke={theme.axis}
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Line 
              type="monotone" 
              dataKey="value" 
              stroke={theme.bullish}
              strokeWidth={2}
              dot={{ r: 4, fill: theme.bullish }}
              activeDot={{ r: 6, fill: theme.bullish }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};