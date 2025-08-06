// Modern PipStop-themed currency pair card with enhanced readability
import React from 'react';
import { CurrencyPair } from '../../types/momentum';
import { TrendingUp, TrendingDown, Minus, Target, Award, Activity, BarChart3 } from 'lucide-react';
import { Tooltip } from '../ui/Tooltip';
import { SparkleCallout } from '../ui/SparkleCallout';

interface PairCardProps {
  pair: CurrencyPair;
  onClick: (pair: CurrencyPair) => void;
  compact?: boolean;
}

export const PairCard: React.FC<PairCardProps> = ({ 
  pair, 
  onClick, 
  compact = false 
}) => {
  const hasActiveTrades = pair.active_trades && pair.active_trades.length > 0;
  const totalPnL = pair.active_trades?.reduce((sum, trade) => sum + trade.unrealized_pnl, 0) || 0;
  
  // Get signal styling using PipStop theme colors
  const getSignalStyling = () => {
    switch (pair.momentum.signal) {
      case 'STRONG_BULLISH':
        return {
          tagBg: 'bg-pipstop-success text-green-900',
          cardBorder: 'border-pipstop-success/50',
          icon: <TrendingUp className="w-4 h-4 text-pipstop-success" />,
          label: 'Strong Bullish',
          confidence: pair.momentum.confidence
        };
      case 'WEAK_BULLISH':
        return {
          tagBg: 'bg-pipstop-success/70 text-green-800',
          cardBorder: 'border-pipstop-success/30',
          icon: <TrendingUp className="w-4 h-4 text-pipstop-success/80" />,
          label: 'Weak Bullish',
          confidence: pair.momentum.confidence
        };
      case 'NEUTRAL':
        return {
          tagBg: 'bg-text-muted-light dark:bg-text-muted-dark text-text-primary-light dark:text-text-primary-dark',
          cardBorder: 'border-border-light dark:border-border-dark',
          icon: <Minus className="w-4 h-4 text-text-secondary-light dark:text-text-secondary-dark" />,
          label: 'Neutral',
          confidence: pair.momentum.confidence
        };
      case 'WEAK_BEARISH':
        return {
          tagBg: 'bg-pipstop-danger/70 text-red-800',
          cardBorder: 'border-pipstop-danger/30',
          icon: <TrendingDown className="w-4 h-4 text-pipstop-danger/80" />,
          label: 'Weak Bearish',
          confidence: pair.momentum.confidence
        };
      case 'STRONG_BEARISH':
        return {
          tagBg: 'bg-pipstop-danger text-red-900',
          cardBorder: 'border-pipstop-danger/50',
          icon: <TrendingDown className="w-4 h-4 text-pipstop-danger" />,
          label: 'Strong Bearish',
          confidence: pair.momentum.confidence
        };
      default:
        return {
          tagBg: 'bg-text-muted-light dark:bg-text-muted-dark text-text-primary-light dark:text-text-primary-dark',
          cardBorder: 'border-border-light dark:border-border-dark',
          icon: <Minus className="w-4 h-4 text-text-secondary-light dark:text-text-secondary-dark" />,
          label: 'Unknown',
          confidence: pair.momentum.confidence
        };
    }
  };

  const styling = getSignalStyling();
  
  const formatPrice = (price: number) => {
    if (price < 1) {
      return price.toFixed(5);
    }
    return price.toFixed(4);
  };

  const formatPercent = (value: number) => {
    return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
  };

  // Calculate if this is a high-confidence signal worthy of sparkle callout
  const isHighConfidence = pair.momentum.confidence >= 85;
  const isStrongSignal = pair.momentum.signal.includes('STRONG');
  const showSparkle = isHighConfidence && isStrongSignal;

  return (
    <div className="group">
      {/* Optional Sparkle Callout for High-Confidence Strong Signals */}
      {showSparkle && (
        <SparkleCallout type="signal" className="mb-3">
          <div className="flex items-center justify-between w-full">
            <div>
              <span className="font-semibold">{pair.display_name}</span>
              <span className="mx-2">•</span>
              <span>{styling.label}</span>
            </div>
            <div className="text-right">
              <span className="text-xs opacity-90">Confidence: </span>
              <span className="font-bold">{pair.momentum.confidence.toFixed(0)}%</span>
            </div>
          </div>
        </SparkleCallout>
      )}
      
      <div 
        className={`
          bg-surface-light dark:bg-surface-dark
          border-2 ${styling.cardBorder}
          rounded-xl p-4
          cursor-pointer transition-all duration-200
          hover:border-pipstop-primary hover:shadow-lg hover:shadow-pipstop-primary/10
          group-hover:transform group-hover:-translate-y-1
          ${compact ? 'min-h-[160px]' : 'min-h-[180px]'}
        `}
        onClick={() => onClick(pair)}
      >
        {/* Header Row */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold text-text-primary-light dark:text-text-primary-dark">
              {pair.display_name}
            </h3>
            {pair.is_major && (
              <Tooltip content="Major Currency Pair">
                <div className="w-2 h-2 rounded-full bg-pipstop-primary"></div>
              </Tooltip>
            )}
          </div>
          
          <div className="flex items-center gap-2">
            <Tooltip content={`Market Rank: #${pair.momentum.rank} of 28`}>
              <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-elevated-light dark:bg-elevated-dark">
                <Award className="w-3 h-3 text-pipstop-primary" />
                <span className="text-xs font-semibold text-text-primary-light dark:text-text-primary-dark">
                  #{pair.momentum.rank}
                </span>
              </div>
            </Tooltip>
          </div>
        </div>

        {/* Price and Change Row */}
        <div className="flex items-baseline justify-between mb-3">
          <div>
            <div className="text-xl font-semibold text-text-primary-light dark:text-text-primary-dark">
              {formatPrice(pair.current_price)}
            </div>
            {pair.daily_change_percent !== undefined && (
              <div className={`text-sm font-medium ${
                pair.daily_change_percent >= 0 ? 'text-pipstop-success' : 'text-pipstop-danger'
              }`}>
                {formatPercent(pair.daily_change_percent)}
              </div>
            )}
          </div>
          
          {hasActiveTrades && (
            <Tooltip content={`${pair.active_trades.length} Active Trade${pair.active_trades.length > 1 ? 's' : ''}`}>
              <div className="flex items-center gap-1 text-pipstop-warning">
                <Activity className="w-4 h-4" />
                <span className="text-sm font-medium">{pair.active_trades.length}</span>
              </div>
            </Tooltip>
          )}
        </div>

        {/* Signal and Confidence Row */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {styling.icon}
            <span className={`text-xs px-2 py-1 rounded-full font-medium ${styling.tagBg}`}>
              {styling.label}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Confidence:</span>
            <div className="flex items-center gap-1">
              <div className="w-16 h-2 bg-elevated-light dark:bg-elevated-dark rounded-full overflow-hidden">
                <div 
                  className="h-full bg-gradient-to-r from-pipstop-primary to-pipstop-secondary transition-all duration-300"
                  style={{ width: `${pair.momentum.confidence}%` }}
                />
              </div>
              <span className="text-xs font-semibold text-text-primary-light dark:text-text-primary-dark">
                {pair.momentum.confidence.toFixed(0)}%
              </span>
            </div>
          </div>
        </div>

        {/* Mini Chart Placeholder */}
        <div className="mb-3 h-8 bg-elevated-light dark:bg-elevated-dark rounded flex items-center justify-center">
          <div className="flex items-center gap-1 text-text-secondary-light dark:text-text-secondary-dark">
            <BarChart3 className="w-3 h-3" />
            <span className="text-xs">Momentum Trend</span>
          </div>
        </div>

        {/* Bottom Stats Row */}
        <div className="flex items-center justify-between text-xs text-text-secondary-light dark:text-text-secondary-dark">
          <div className="flex items-center gap-4">
            <Tooltip content="Composite Momentum Score">
              <div className="flex items-center gap-1">
                <span>Score:</span>
                <span className="font-semibold text-text-primary-light dark:text-text-primary-dark">
                  {pair.momentum.composite_score.toFixed(1)}
                </span>
              </div>
            </Tooltip>
          </div>
          
          {hasActiveTrades && (
            <div className="flex items-center gap-1">
              <span>P&L:</span>
              <span className={`font-semibold ${
                totalPnL >= 0 ? 'text-pipstop-success' : 'text-pipstop-danger'
              }`}>
                ${totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};