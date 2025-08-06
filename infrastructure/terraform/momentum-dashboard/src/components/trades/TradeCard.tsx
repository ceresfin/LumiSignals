// Enhanced Trade Card Component - PipStop Design System
import React from 'react';
import { CurrencyPair } from '../../types/momentum';
import { TrendingUp, TrendingDown, Minus, Clock, Target, Shield, Activity } from 'lucide-react';
import { TradeSetupGroup } from '../ui/TradeSetupTags';
import { Tooltip } from '../ui/Tooltip';
import { SparkleCallout } from '../ui/SparkleCallout';

interface TradeCardProps {
  pair: CurrencyPair;
  onClick: (pair: CurrencyPair) => void;
  compact?: boolean;
}

export const TradeCard: React.FC<TradeCardProps> = ({ 
  pair, 
  onClick, 
  compact = false 
}) => {
  const hasActiveTrades = pair.active_trades && pair.active_trades.length > 0;
  const totalPnL = pair.active_trades?.reduce((sum, trade) => sum + (trade.unrealized_pnl || 0), 0) || 0;
  
  // Use real trade data from RDS (now includes Target/Stop/R&R from Fargate OANDA collection)
  const tradeMetadata = pair.trade_metadata;
  const activeTrade = hasActiveTrades ? pair.active_trades[0] : null;
  
  const trade = tradeMetadata ? {
    entry_price: tradeMetadata.entry_price || 1.0850,
    target_price: tradeMetadata.take_profit_price, // Real OANDA Target price
    stop_price: tradeMetadata.stop_loss_price, // Real OANDA Stop Loss price
    current_price: tradeMetadata.current_price || tradeMetadata.entry_price || 1.0875,
    risk_reward_ratio: tradeMetadata.risk_reward_ratio, // Real calculated R:R ratio
    status: 'ACTIVE',
    time_opened: tradeMetadata.open_time ? new Date(tradeMetadata.open_time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : '14:35',
    position_size: Math.abs(tradeMetadata.current_units || 0),
    unrealized_pnl: tradeMetadata.unrealized_pnl || 0,
    pips_gained: tradeMetadata.pips_moved || 0, // Real pips moved from OANDA
    duration: tradeMetadata.trade_duration || '0m', // Real trade duration
    distance_from_entry: tradeMetadata.distance_to_entry || 0 // Real distance calculation
  } : {
    entry_price: 1.0850,
    target_price: 1.1100,
    stop_price: 1.0600,
    current_price: 1.0875,
    risk_reward_ratio: 2.0,
    status: 'NEUTRAL',
    time_opened: '--:--',
    position_size: 0,
    unrealized_pnl: 0,
    pips_gained: 0,
    duration: '0m',
    distance_from_entry: 0
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ACTIVE':
        return '#4CAF50';
      case 'PENDING':
        return '#FF9800';
      case 'STOPPED':
        return '#F44336';
      default:
        return '#B3B3B3';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'ACTIVE':
        return <Activity className="w-3 h-3" />;
      case 'PENDING':
        return <Clock className="w-3 h-3" />;
      case 'STOPPED':
        return <Shield className="w-3 h-3" />;
      default:
        return <Minus className="w-3 h-3" />;
    }
  };

  const getMomentumIcon = () => {
    if (pair.momentum.signal.includes('BULLISH')) {
      return <TrendingUp className="w-4 h-4 text-pipstop-success" />;
    }
    if (pair.momentum.signal.includes('BEARISH')) {
      return <TrendingDown className="w-4 h-4 text-pipstop-danger" />;
    }
    return <Minus className="w-4 h-4 text-text-secondary-light dark:text-text-secondary-dark" />;
  };

  const formatPrice = (price: number) => {
    if (price < 1) {
      return price.toFixed(5);
    }
    return price.toFixed(4);
  };

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : '';
    return `${sign}$${pnl.toFixed(2)}`;
  };

  return (
    <div className="group">
      {/* Optional Sparkle Callout for High R/R Trades */}
      {trade.risk_reward_ratio && trade.risk_reward_ratio >= 3.0 && (
        <SparkleCallout type="signal" className="mb-3">
          High R/R Signal: {pair.display_name || pair.pair.replace('_', '/')} • R/R {trade.risk_reward_ratio.toFixed(1)}
        </SparkleCallout>
      )}
      
      <div 
        className="
          bg-surface-light dark:bg-surface-dark
          border border-border-light dark:border-border-dark
          rounded-lg p-4 mb-4
          cursor-pointer transition-all duration-200
          shadow-lg shadow-black/10 dark:shadow-black/30
          hover:border-pipstop-primary
          hover:shadow-xl hover:shadow-pipstop-primary/20 dark:hover:shadow-pipstop-primary/15
          group-hover:transform group-hover:-translate-y-2
        "
        onClick={() => onClick(pair)}
      >
        {/* Trade Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">
              {pair.display_name || pair.pair.replace('_', '/')}
            </h3>
            <Tooltip content={`Momentum: ${pair.momentum.signal.replace('_', ' ')}`}>
              {getMomentumIcon()}
            </Tooltip>
          </div>
          
          <div className={`flex items-center gap-1 text-sm font-medium ${
            trade.unrealized_pnl >= 0 ? 'text-pipstop-success' : 'text-pipstop-danger'
          }`}>
            <div 
              className={`w-2 h-2 rounded-full ${
                trade.unrealized_pnl >= 0 ? 'bg-pipstop-success' : 'bg-pipstop-danger'
              }`}
            />
            <span className="text-xs font-medium text-text-secondary-light dark:text-text-secondary-dark">P&L:</span>
            <span>{formatPnL(trade.unrealized_pnl)}</span>
          </div>
        </div>

        {/* Primary Trading Levels - 2x2 Grid */}
        <div className="grid grid-cols-2 gap-3 mb-4 p-3 bg-elevated-light dark:bg-elevated-dark rounded-lg">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-pipstop-accent" />
            <span className="text-xs font-medium text-text-secondary-light dark:text-text-secondary-dark">ENTRY:</span>
            <span className="text-sm font-mono font-semibold text-text-primary-light dark:text-text-primary-dark">
              {trade.entry_price.toFixed(4)}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-pipstop-success" />
            <span className="text-xs font-medium text-text-secondary-light dark:text-text-secondary-dark">TARGET:</span>
            <span className="text-sm font-mono font-semibold text-pipstop-success">
              {trade.target_price ? trade.target_price.toFixed(4) : '--'}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-pipstop-danger" />
            <span className="text-xs font-medium text-text-secondary-light dark:text-text-secondary-dark">STOP:</span>
            <span className="text-sm font-mono font-semibold text-pipstop-danger">
              {trade.stop_price ? trade.stop_price.toFixed(4) : '--'}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-pipstop-primary" />
            <span className="text-xs font-medium text-text-secondary-light dark:text-text-secondary-dark">R/R:</span>
            <span className="text-sm font-mono font-semibold text-pipstop-primary">
              {trade.risk_reward_ratio ? trade.risk_reward_ratio.toFixed(1) : '--'}
            </span>
          </div>
        </div>

        {/* Performance Metrics - 2x2 Grid */}
        <div className="grid grid-cols-2 gap-4 py-3 border-t border-b border-border-light dark:border-border-dark">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Units:</span>
              <span className="text-sm font-semibold text-text-primary-light dark:text-text-primary-dark">
                {trade.position_size.toLocaleString()}
              </span>
            </div>
            
            <div className="flex items-center justify-between">
              <span className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Duration:</span>
              <span className="text-sm font-semibold text-text-primary-light dark:text-text-primary-dark">
                {trade.duration}
              </span>
            </div>
          </div>
          
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Pips:</span>
              <span className={`text-sm font-semibold ${
                trade.pips_gained >= 0 ? 'text-pipstop-success' : 'text-pipstop-danger'
              }`}>
                {trade.pips_gained >= 0 ? '+' : ''}{trade.pips_gained.toFixed(1)}
              </span>
            </div>
            
            <div className="flex items-center justify-between">
              <span className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Momentum:</span>
              <span className="text-sm font-semibold text-pipstop-accent">
                {activeTrade?.momentum_strength || tradeMetadata?.momentum_strength || 'NEUTRAL'}
              </span>
            </div>
          </div>
        </div>

        {/* Footer Info */}
        <div className="flex justify-between items-center text-xs text-text-secondary-light dark:text-text-secondary-dark mt-3">
          <div className="flex items-center gap-2">
            <span>Strategy:</span>
            <span className="font-medium text-text-primary-light dark:text-text-primary-dark">
              {activeTrade?.strategy_name || tradeMetadata?.strategy_name || 'Momentum'}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <span>Direction:</span>
            <span className={`font-medium ${
              (activeTrade?.direction || tradeMetadata?.direction) === 'Long' ? 'text-pipstop-success' : 'text-pipstop-danger'
            }`}>
              {activeTrade?.direction || tradeMetadata?.direction || 'Unknown'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TradeCard;