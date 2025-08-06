// Visual momentum strength indicator with multi-timeframe breakdown
import React from 'react';
import { MomentumSignal, MomentumData } from '../../types/momentum';

interface MomentumIndicatorProps {
  signal: MomentumSignal;
  score: number;
  confidence: number;
  compact?: boolean;
  showTimeframes?: boolean;
  timeframes?: MomentumData['timeframes'];
}

export const MomentumIndicator: React.FC<MomentumIndicatorProps> = ({
  signal,
  score,
  confidence,
  compact = false,
  showTimeframes = false,
  timeframes
}) => {
  // Normalize score to 0-100 range for visual display
  const normalizedScore = Math.abs(score);
  const isPositive = score >= 0;
  
  // Get color based on signal strength
  const getSignalColor = () => {
    switch (signal) {
      case 'STRONG_BULLISH':
        return { bg: 'bg-green-500', text: 'text-green-500', border: 'border-green-500' };
      case 'WEAK_BULLISH':
        return { bg: 'bg-green-400', text: 'text-green-400', border: 'border-green-400' };
      case 'NEUTRAL':
        return { bg: 'bg-gray-500', text: 'text-gray-500', border: 'border-gray-500' };
      case 'WEAK_BEARISH':
        return { bg: 'bg-red-400', text: 'text-red-400', border: 'border-red-400' };
      case 'STRONG_BEARISH':
        return { bg: 'bg-red-500', text: 'text-red-500', border: 'border-red-500' };
      default:
        return { bg: 'bg-gray-500', text: 'text-gray-500', border: 'border-gray-500' };
    }
  };

  const colors = getSignalColor();

  // Calculate gauge fill percentage (0-100)
  const fillPercentage = Math.min(100, (normalizedScore / 50) * 100);

  const getSignalText = () => {
    return signal.replace('_', ' ').toLowerCase()
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  if (compact) {
    return (
      <div className="flex items-center space-x-2">
        {/* Compact Gauge */}
        <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 ${colors.bg}`}
            style={{ width: `${fillPercentage}%` }}
          />
        </div>
        
        {/* Score */}
        <span className={`text-xs font-medium ${colors.text}`}>
          {score.toFixed(0)}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Main Momentum Gauge */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className={`font-medium ${colors.text}`}>
            {getSignalText()}
          </span>
          <span className="text-gray-400">
            {confidence * 100}% conf
          </span>
        </div>
        
        {/* Bidirectional Gauge */}
        <div className="relative h-3 bg-gray-700 rounded-full overflow-hidden">
          {/* Center line */}
          <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gray-500 z-10" />
          
          {/* Momentum bar */}
          {isPositive ? (
            <div 
              className={`absolute left-1/2 top-0 bottom-0 transition-all duration-500 ${colors.bg}`}
              style={{ width: `${fillPercentage / 2}%` }}
            />
          ) : (
            <div 
              className={`absolute right-1/2 top-0 bottom-0 transition-all duration-500 ${colors.bg}`}
              style={{ width: `${fillPercentage / 2}%` }}
            />
          )}
        </div>
        
        {/* Score and Range */}
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span>-100</span>
          <span className={`font-bold ${colors.text}`}>
            {score.toFixed(1)}
          </span>
          <span>+100</span>
        </div>
      </div>

      {/* Timeframe Breakdown */}
      {showTimeframes && timeframes && (
        <div className="grid grid-cols-5 gap-1">
          {Object.entries(timeframes).map(([timeframe, data]) => {
            const isUp = data.direction === 'bullish';
            const isStrong = data.strength === 'strong';
            
            return (
              <div
                key={timeframe}
                className={`text-xs text-center p-1 rounded transition-colors ${
                  isUp 
                    ? isStrong ? 'bg-green-600 text-white' : 'bg-green-500 text-white'
                    : isStrong ? 'bg-red-600 text-white' : 'bg-red-500 text-white'
                }`}
                title={`${timeframe}: ${data.direction} ${data.strength} (${(data.change_percent * 100).toFixed(2)}%)`}
              >
                <div className="font-medium">{timeframe}</div>
                <div className="text-xs opacity-90">
                  {isUp ? '↗' : '↘'}{isStrong ? '!' : ''}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Momentum Strength Dots */}
      <div className="flex items-center justify-center space-x-1">
        {[1, 2, 3, 4, 5].map((level) => {
          const isActive = normalizedScore >= (level * 20);
          return (
            <div
              key={level}
              className={`w-2 h-2 rounded-full transition-colors ${
                isActive ? colors.bg : 'bg-gray-600'
              }`}
            />
          );
        })}
      </div>
    </div>
  );
};