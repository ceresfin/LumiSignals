// Sparkline chart component for mini momentum visualization
import React, { useEffect, useRef } from 'react';
import { PriceData, ActiveTrade } from '../../types/momentum';

interface SparklineChartProps {
  data: PriceData[];
  trades?: ActiveTrade[];
  height?: number;
  showVolume?: boolean;
  color?: string;
}

export const SparklineChart: React.FC<SparklineChartProps> = ({
  data,
  trades = [],
  height = 60,
  showVolume = false,
  color = '#A2C8A1'
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const canvasHeight = canvas.height;

    // Clear canvas
    ctx.clearRect(0, 0, width, canvasHeight);

    // Prepare data
    const prices = data.map(d => d.close);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = maxPrice - minPrice;

    if (priceRange === 0) return;

    // Calculate points
    const points = data.map((point, index) => ({
      x: (index / (data.length - 1)) * width,
      y: canvasHeight - ((point.close - minPrice) / priceRange) * canvasHeight
    }));

    // Draw price line
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();

    points.forEach((point, index) => {
      if (index === 0) {
        ctx.moveTo(point.x, point.y);
      } else {
        ctx.lineTo(point.x, point.y);
      }
    });

    ctx.stroke();

    // Add gradient fill
    if (points.length > 1) {
      const gradient = ctx.createLinearGradient(0, 0, 0, canvasHeight);
      gradient.addColorStop(0, `${color}40`); // 25% opacity
      gradient.addColorStop(1, `${color}00`); // 0% opacity

      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.moveTo(points[0].x, canvasHeight);
      
      points.forEach((point, index) => {
        if (index === 0) {
          ctx.lineTo(point.x, point.y);
        } else {
          ctx.lineTo(point.x, point.y);
        }
      });
      
      ctx.lineTo(points[points.length - 1].x, canvasHeight);
      ctx.closePath();
      ctx.fill();
    }

    // Draw trade entry points
    trades.forEach(trade => {
      const entryY = canvasHeight - ((trade.entry_price - minPrice) / priceRange) * canvasHeight;
      
      // Entry point
      ctx.fillStyle = '#32A0A8';
      ctx.beginPath();
      ctx.arc(width * 0.1, entryY, 3, 0, 2 * Math.PI);
      ctx.fill();

      // Stop loss line
      const slY = canvasHeight - ((trade.stop_loss - minPrice) / priceRange) * canvasHeight;
      ctx.strokeStyle = '#CF4505';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(0, slY);
      ctx.lineTo(width, slY);
      ctx.stroke();

      // Take profit line
      const tpY = canvasHeight - ((trade.take_profit - minPrice) / priceRange) * canvasHeight;
      ctx.strokeStyle = '#A2C8A1';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(0, tpY);
      ctx.lineTo(width, tpY);
      ctx.stroke();

      // Reset line dash
      ctx.setLineDash([]);
    });

    // Show current price point
    if (points.length > 0) {
      const lastPoint = points[points.length - 1];
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(lastPoint.x, lastPoint.y, 2, 0, 2 * Math.PI);
      ctx.fill();
    }

  }, [data, trades, height, color]);

  // Handle no data case
  if (data.length === 0) {
    return (
      <div 
        className="flex items-center justify-center rounded"
        style={{ 
          height, 
          background: 'rgba(44, 44, 44, 0.3)',
          color: '#B6E6C4'
        }}
      >
        <span className="text-xs opacity-60">No data</span>
      </div>
    );
  }

  // Calculate price change for color
  const priceChange = data.length > 1 ? data[data.length - 1].close - data[0].close : 0;
  const chartColor = priceChange >= 0 ? '#A2C8A1' : '#CF4505';

  return (
    <div className="relative" style={{ height }}>
      <canvas
        ref={canvasRef}
        width={200}
        height={height}
        className="w-full h-full"
        style={{ imageRendering: 'crisp-edges' }}
      />
      
      {/* Price change indicator */}
      <div className="absolute top-1 right-1 text-xs font-medium" style={{
        color: chartColor,
        textShadow: '0 0 4px rgba(0,0,0,0.8)'
      }}>
        {priceChange >= 0 ? '+' : ''}{((priceChange / data[0].close) * 100).toFixed(2)}%
      </div>
      
      {/* Trade count indicator */}
      {trades.length > 0 && (
        <div className="absolute bottom-1 left-1 text-xs" style={{
          background: 'rgba(50, 160, 168, 0.8)',
          color: '#F7F2E6',
          padding: '1px 4px',
          borderRadius: '2px',
          fontSize: '10px'
        }}>
          {trades.length} trade{trades.length > 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
};