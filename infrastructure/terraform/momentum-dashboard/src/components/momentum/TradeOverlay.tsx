// Trade overlay component showing entry, stop loss, and take profit levels
import React from 'react';
import { ActiveTrade } from '../../types/momentum';

interface TradeOverlayProps {
  trade: ActiveTrade;
  currentPrice: number;
}

export const TradeOverlay: React.FC<TradeOverlayProps> = ({ trade, currentPrice }) => {
  // Calculate if we're in profit or loss
  const isLong = trade.position_size > 0;
  const pnlColor = trade.unrealized_pnl >= 0 ? '#A2C8A1' : '#CF4505';
  
  // Calculate position relative to entry
  const priceChange = currentPrice - trade.entry_price;
  const priceChangePercent = (priceChange / trade.entry_price) * 100;
  
  return (
    <div className="absolute inset-x-0 bottom-0 p-1 text-xs" style={{
      background: 'linear-gradient(to top, rgba(18, 18, 18, 0.9), transparent)',
      pointerEvents: 'none'
    }}>
      {/* Trade Status Bar */}
      <div className="flex items-center justify-between mb-1">
        <span className="truncate" style={{color: '#B6E6C4'}}>
          {trade.strategy}
        </span>
        <span style={{color: pnlColor}}>
          {trade.unrealized_pnl >= 0 ? '+' : ''}${trade.unrealized_pnl.toFixed(2)}
        </span>
      </div>
      
      {/* Price Levels Indicator */}
      <div className="flex items-center space-x-2 text-xs">
        <div className="flex items-center space-x-1">
          <div className="w-2 h-1 rounded-full" style={{background: '#32A0A8'}} />
          <span style={{color: '#B6E6C4'}}>
            Entry: {trade.entry_price.toFixed(5)}
          </span>
        </div>
        
        <div className="flex items-center space-x-1">
          <div className="w-2 h-1 rounded-full" style={{background: '#CF4505'}} />
          <span style={{color: '#B6E6C4'}}>
            SL: {trade.stop_loss.toFixed(5)}
          </span>
        </div>
        
        <div className="flex items-center space-x-1">
          <div className="w-2 h-1 rounded-full" style={{background: '#A2C8A1'}} />
          <span style={{color: '#B6E6C4'}}>
            TP: {trade.take_profit.toFixed(5)}
          </span>
        </div>
      </div>
      
      {/* Risk/Reward Bar */}
      <div className="mt-1 flex items-center text-xs">
        <span style={{color: '#B6E6C4'}}>R:R</span>
        <div className="mx-2 flex-1 h-1 bg-gray-600 rounded-full overflow-hidden">
          <div 
            className="h-full transition-all duration-300"
            style={{
              width: `${Math.min(100, Math.max(0, (trade.risk_reward_ratio / 3) * 100))}%`,
              background: trade.risk_reward_ratio >= 2 ? '#A2C8A1' : trade.risk_reward_ratio >= 1 ? '#FFE4B3' : '#CF4505'
            }}
          />
        </div>
        <span style={{color: '#B6E6C4'}}>
          1:{trade.risk_reward_ratio.toFixed(1)}
        </span>
      </div>
    </div>
  );
};