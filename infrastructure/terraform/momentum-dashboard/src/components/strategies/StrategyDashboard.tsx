// LumiSignals Strategy Dashboard - Shows all 10 Active Trading Strategies
import React, { useState } from 'react';
import { useStrategyData } from '../../hooks/useStrategyData';
import { TradingStrategy, StrategySignal } from '../../types/momentum';
import { 
  TrendingUp, 
  TrendingDown, 
  Activity, 
  DollarSign, 
  Target, 
  Clock, 
  Zap,
  CheckCircle,
  AlertCircle,
  PauseCircle
} from 'lucide-react';

const StrategyDashboard: React.FC = () => {
  const { strategies, signals, loading, error, connected, lastUpdated } = useStrategyData();
  const [selectedStrategy, setSelectedStrategy] = useState<TradingStrategy | null>(null);

  const getStrategyTypeColor = (type: string) => {
    switch (type) {
      case 'PC': return 'bg-blue-500/20 text-blue-300 border-blue-500/30';
      case 'QC': return 'bg-green-500/20 text-green-300 border-green-500/30';
      case 'DC': return 'bg-purple-500/20 text-purple-300 border-purple-500/30';
      default: return 'bg-gray-500/20 text-gray-300 border-gray-500/30';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'ACTIVE': return <CheckCircle className="w-4 h-4 text-green-400" />;
      case 'PAUSED': return <PauseCircle className="w-4 h-4 text-yellow-400" />;
      case 'DISABLED': return <AlertCircle className="w-4 h-4 text-red-400" />;
      default: return <Activity className="w-4 h-4 text-gray-400" />;
    }
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(amount);
  };

  const getStrategySignals = (strategyId: string) => {
    return (signals || []).filter(signal => signal.strategy_id === strategyId);
  };

  const totalPnL = strategies.reduce((sum, strategy) => sum + strategy.profit_loss, 0);
  const totalPositions = strategies.reduce((sum, strategy) => sum + strategy.current_positions, 0);
  const avgWinRate = strategies.reduce((sum, strategy) => sum + strategy.win_rate, 0) / strategies.length;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-96">
        <div className="flex items-center space-x-3">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
          <span className="text-gray-300">Loading strategy data...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header Card */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-3xl font-bold text-text-primary-light dark:text-text-primary-dark mb-2">Trading Strategies</h2>
            <div className="flex items-center gap-4 text-sm text-text-secondary-light dark:text-text-secondary-dark">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${
                  connected ? 'bg-pipstop-success animate-pulse' : 'bg-pipstop-danger'
                }`} />
                <span>{connected ? 'Live Data' : 'Mock Data'}</span>
              </div>
              <span>•</span>
              <span>{strategies.length} Active Strategies</span>
              {lastUpdated && (
                <>
                  <span>•</span>
                  <span>Updated {new Date(lastUpdated).toLocaleTimeString()}</span>
                </>
              )}
            </div>
          </div>
          
          {/* Summary Metrics Cards */}
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Total P&L</div>
              <div className={`text-lg font-bold ${
                totalPnL >= 0 ? 'text-pipstop-success' : 'text-pipstop-danger'
              }`}>
                {formatCurrency(totalPnL)}
              </div>
            </div>
            <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Active Positions</div>
              <div className="text-lg font-bold text-pipstop-primary">{totalPositions}</div>
            </div>
            <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Avg Win Rate</div>
              <div className="text-lg font-bold text-pipstop-success">{(avgWinRate * 100).toFixed(1)}%</div>
            </div>
          </div>
        </div>
      </div>

      {/* Strategy Cards Grid */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="flex items-center gap-2 mb-6">
          <Zap className="w-5 h-5 text-pipstop-primary" />
          <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Active Strategies</h3>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {strategies.map((strategy) => {
            const strategySignals = getStrategySignals(strategy.id);
            const hasActiveSignal = strategySignals.length > 0;
            
            return (
              <div
                key={strategy.id}
                className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-4 border border-border-light dark:border-border-dark hover:border-pipstop-primary hover:shadow-lg hover:shadow-pipstop-primary/10 transition-all duration-200 cursor-pointer group"
                onClick={() => setSelectedStrategy(strategy)}
              >
                {/* Strategy Header Card */}
                <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-3 mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(strategy.status)}
                      <span className={`text-xs px-2 py-1 rounded-full font-medium ${getStrategyTypeColor(strategy.type)}`}>
                        {strategy.type}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 text-xs text-text-secondary-light dark:text-text-secondary-dark">
                      <Clock className="w-3 h-3" />
                      <span>{strategy.timeframe}</span>
                    </div>
                  </div>
                  
                  <h4 className="font-semibold text-text-primary-light dark:text-text-primary-dark text-sm leading-tight">
                    {strategy.name}
                  </h4>
                </div>

                {/* Performance Metrics Card */}
                <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-3 mb-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="text-center">
                      <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">P&L</div>
                      <div className={`text-sm font-bold ${
                        strategy.profit_loss >= 0 ? 'text-pipstop-success' : 'text-pipstop-danger'
                      }`}>
                        {formatCurrency(strategy.profit_loss)}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Win Rate</div>
                      <div className="text-sm font-bold text-pipstop-success">
                        {(strategy.win_rate * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Positions</div>
                      <div className="text-sm font-bold text-pipstop-primary">
                        {strategy.current_positions}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">R:R Ratio</div>
                      <div className="text-sm font-bold text-pipstop-secondary">
                        {strategy.expected_rr_ratio}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Active Signal Card */}
                {hasActiveSignal && (
                  <div className="bg-pipstop-warning/10 border border-pipstop-warning/30 rounded-lg p-3 mb-4">
                    <div className="flex items-center gap-2">
                      <Zap className="w-4 h-4 text-pipstop-warning" />
                      <span className="text-sm font-medium text-pipstop-warning">
                        {strategySignals.length} Active Signal{strategySignals.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </div>
                )}

                {/* Strategy Stats Card */}
                <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-3">
                  <div className="flex justify-between text-xs text-text-secondary-light dark:text-text-secondary-dark">
                    <span>Trades: {strategy.total_trades}</span>
                    <span>Risk: ${strategy.risk_per_trade}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Active Signals Section */}
      {signals && signals.length > 0 && (
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
          <div className="flex items-center gap-2 mb-6">
            <Activity className="w-5 h-5 text-pipstop-primary" />
            <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Active Trading Signals</h3>
            <span className="px-2 py-1 bg-pipstop-primary/10 text-pipstop-primary text-xs font-medium rounded-full">
              {signals?.length || 0}
            </span>
          </div>
          
          <div className="space-y-4">
            {(signals || []).map((signal, index) => (
              <div
                key={index}
                className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-4 border border-border-light dark:border-border-dark"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    {/* Signal Type Card */}
                    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${
                      signal.signal_type === 'BUY' 
                        ? 'bg-pipstop-success/10 text-pipstop-success border border-pipstop-success/30' 
                        : 'bg-pipstop-danger/10 text-pipstop-danger border border-pipstop-danger/30'
                    }`}>
                      {signal.signal_type === 'BUY' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                      <span className="font-bold text-sm">{signal.signal_type}</span>
                    </div>
                    
                    {/* Strategy Info Card */}
                    <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-3">
                      <div className="font-medium text-text-primary-light dark:text-text-primary-dark mb-1">{signal.strategy_name}</div>
                      <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark space-x-3">
                        <span>Entry: {signal.entry_price.toFixed(5)}</span>
                        <span>SL: {signal.stop_loss.toFixed(5)}</span>
                        <span>TP: {signal.take_profit.toFixed(5)}</span>
                      </div>
                    </div>
                  </div>
                  
                  {/* Performance Metrics Card */}
                  <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-3 text-right">
                    <div className="text-sm font-medium text-pipstop-secondary mb-1">R:R {signal.risk_reward_ratio.toFixed(1)}</div>
                    <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark">{(signal.confidence * 100).toFixed(0)}% confidence</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Strategy Type Performance Summary */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="flex items-center gap-2 mb-6">
          <Target className="w-5 h-5 text-pipstop-primary" />
          <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Strategy Type Performance</h3>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 mb-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark mb-1">Penny Curve (PC)</div>
                  <div className="text-xl font-bold text-pipstop-primary">
                    {strategies.filter(s => s.type === 'PC').length} Strategies
                  </div>
                </div>
                <div className="w-12 h-12 bg-pipstop-primary/10 rounded-lg flex items-center justify-center">
                  <span className="text-pipstop-primary font-bold">PC</span>
                </div>
              </div>
            </div>
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Combined P&L</div>
              <div className="text-lg font-bold text-pipstop-success">
                {formatCurrency(strategies.filter(s => s.type === 'PC').reduce((sum, s) => sum + s.profit_loss, 0))}
              </div>
            </div>
          </div>

          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 mb-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark mb-1">Quarter Curve (QC)</div>
                  <div className="text-xl font-bold text-pipstop-secondary">
                    {strategies.filter(s => s.type === 'QC').length} Strategies
                  </div>
                </div>
                <div className="w-12 h-12 bg-pipstop-secondary/10 rounded-lg flex items-center justify-center">
                  <span className="text-pipstop-secondary font-bold">QC</span>
                </div>
              </div>
            </div>
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Combined P&L</div>
              <div className="text-lg font-bold text-pipstop-success">
                {formatCurrency(strategies.filter(s => s.type === 'QC').reduce((sum, s) => sum + s.profit_loss, 0))}
              </div>
            </div>
          </div>

          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 mb-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark mb-1">Dime Curve (DC)</div>
                  <div className="text-xl font-bold text-pipstop-accent">
                    {strategies.filter(s => s.type === 'DC').length} Strategies
                  </div>
                </div>
                <div className="w-12 h-12 bg-pipstop-accent/10 rounded-lg flex items-center justify-center">
                  <span className="text-pipstop-accent font-bold">DC</span>
                </div>
              </div>
            </div>
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Combined P&L</div>
              <div className="text-lg font-bold text-pipstop-success">
                {formatCurrency(strategies.filter(s => s.type === 'DC').reduce((sum, s) => sum + s.profit_loss, 0))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default StrategyDashboard;