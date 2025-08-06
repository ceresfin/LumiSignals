import React from 'react';
import { Target, TrendingUp, Shield, DollarSign, Clock, Activity, Hash, BarChart3 } from 'lucide-react';

interface TradeSetupTagProps {
  type: 'entry' | 'target' | 'stop' | 'pnl' | 'status' | 'time' | 'rr' | 'pips' | 'units' | 'duration' | 'distance';
  value: string | number;
  label?: string;
  className?: string;
}

export const TradeSetupTag: React.FC<TradeSetupTagProps> = ({ 
  type, 
  value, 
  label,
  className = ''
}) => {
  const getConfig = () => {
    switch (type) {
      case 'entry':
        return {
          icon: <TrendingUp className="w-3 h-3" />,
          label: label || 'ENTRY',
          bgClass: 'bg-pipstop-accent/20 border-pipstop-accent/40 text-gray-800',
          darkClass: 'dark:bg-pipstop-accent/10 dark:border-pipstop-accent/30 dark:text-gray-200'
        };
      case 'target':
        return {
          icon: <Target className="w-3 h-3" />,
          label: label || 'TARGET',
          bgClass: 'bg-pipstop-success/20 border-pipstop-success/40 text-pipstop-success',
          darkClass: 'dark:bg-pipstop-success/10 dark:border-pipstop-success/30 dark:text-pipstop-success'
        };
      case 'stop':
        return {
          icon: <Shield className="w-3 h-3" />,
          label: label || 'STOP',
          bgClass: 'bg-pipstop-danger/20 border-pipstop-danger/40 text-pipstop-danger',
          darkClass: 'dark:bg-pipstop-danger/10 dark:border-pipstop-danger/30 dark:text-pipstop-danger'
        };
      case 'pnl':
        const isPositive = typeof value === 'number' ? value >= 0 : parseFloat(value.toString()) >= 0;
        return {
          icon: <DollarSign className="w-3 h-3" />,
          label: label || 'P&L',
          bgClass: isPositive 
            ? 'bg-pipstop-success/20 border-pipstop-success/40 text-pipstop-success'
            : 'bg-pipstop-danger/20 border-pipstop-danger/40 text-pipstop-danger',
          darkClass: isPositive
            ? 'dark:bg-pipstop-success/10 dark:border-pipstop-success/30 dark:text-pipstop-success'
            : 'dark:bg-pipstop-danger/10 dark:border-pipstop-danger/30 dark:text-pipstop-danger'
        };
      case 'status':
        return {
          icon: <Activity className="w-3 h-3" />,
          label: label || 'STATUS',
          bgClass: 'bg-pipstop-info/20 border-pipstop-info/40 text-pipstop-info',
          darkClass: 'dark:bg-pipstop-info/10 dark:border-pipstop-info/30 dark:text-pipstop-info'
        };
      case 'time':
        return {
          icon: <Clock className="w-3 h-3" />,
          label: label || 'TIME',
          bgClass: 'bg-text-secondary-light/20 border-text-secondary-light/40 text-text-secondary-light',
          darkClass: 'dark:bg-text-secondary-dark/10 dark:border-text-secondary-dark/30 dark:text-text-secondary-dark'
        };
      case 'rr':
        return {
          icon: <Target className="w-3 h-3" />,
          label: label || 'R/R',
          bgClass: 'bg-pipstop-primary/20 border-pipstop-primary/40 text-pipstop-primary',
          darkClass: 'dark:bg-pipstop-primary/10 dark:border-pipstop-primary/30 dark:text-pipstop-primary'
        };
      case 'pips':
        const pipsValue = typeof value === 'number' ? value : parseFloat(value.toString()) || 0;
        return {
          icon: <BarChart3 className="w-3 h-3" />,
          label: label || 'PIPS',
          bgClass: pipsValue >= 0 
            ? 'bg-pipstop-success/20 border-pipstop-success/40 text-pipstop-success'
            : 'bg-pipstop-danger/20 border-pipstop-danger/40 text-pipstop-danger',
          darkClass: pipsValue >= 0
            ? 'dark:bg-pipstop-success/10 dark:border-pipstop-success/30 dark:text-pipstop-success'
            : 'dark:bg-pipstop-danger/10 dark:border-pipstop-danger/30 dark:text-pipstop-danger'
        };
      case 'units':
        return {
          icon: <Hash className="w-3 h-3" />,
          label: label || 'UNITS',
          bgClass: 'bg-text-secondary-light/20 border-text-secondary-light/40 text-text-secondary-light',
          darkClass: 'dark:bg-text-secondary-dark/10 dark:border-text-secondary-dark/30 dark:text-text-secondary-dark'
        };
      case 'duration':
        return {
          icon: <Clock className="w-3 h-3" />,
          label: label || 'DURATION',
          bgClass: 'bg-pipstop-info/20 border-pipstop-info/40 text-pipstop-info',
          darkClass: 'dark:bg-pipstop-info/10 dark:border-pipstop-info/30 dark:text-pipstop-info'
        };
      case 'distance':
        const distanceValue = typeof value === 'string' ? parseFloat(value) : value;
        return {
          icon: <TrendingUp className="w-3 h-3" />,
          label: label || 'DISTANCE',
          bgClass: distanceValue >= 0 
            ? 'bg-pipstop-success/20 border-pipstop-success/40 text-pipstop-success'
            : 'bg-pipstop-danger/20 border-pipstop-danger/40 text-pipstop-danger',
          darkClass: distanceValue >= 0
            ? 'dark:bg-pipstop-success/10 dark:border-pipstop-success/30 dark:text-pipstop-success'
            : 'dark:bg-pipstop-danger/10 dark:border-pipstop-danger/30 dark:text-pipstop-danger'
        };
      default:
        return {
          icon: <Activity className="w-3 h-3" />,
          label: label || 'INFO',
          bgClass: 'bg-text-secondary-light/20 border-text-secondary-light/40 text-text-secondary-light',
          darkClass: 'dark:bg-text-secondary-dark/10 dark:border-text-secondary-dark/30 dark:text-text-secondary-dark'
        };
    }
  };

  const config = getConfig();
  const formatValue = (val: string | number) => {
    if (type === 'pnl' && typeof val === 'number') {
      return val >= 0 ? `+$${val.toFixed(2)}` : `-$${Math.abs(val).toFixed(2)}`;
    }
    if (type === 'pips' && typeof val === 'number') {
      return val >= 0 ? `+${val.toFixed(1)}` : `${val.toFixed(1)}`;
    }
    if (type === 'units' && typeof val === 'number') {
      return Math.abs(val).toLocaleString(); // Format with commas, always positive display
    }
    if (type === 'distance' && typeof val === 'number') {
      return val >= 0 ? `+${val.toFixed(1)} pips` : `${val.toFixed(1)} pips`;
    }
    return val.toString();
  };

  return (
    <div className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md border transition-all duration-200 ${config.bgClass} ${config.darkClass} ${className}`}>
      {config.icon}
      <span className="font-semibold uppercase tracking-wide">{config.label}:</span>
      <span className="font-mono">{formatValue(value)}</span>
    </div>
  );
};

export const TradeSetupGroup: React.FC<{ 
  entry: number; 
  target?: number; 
  stop?: number; 
  pnl?: number;
  rr?: number;
  status?: string;
  time?: string;
  pips?: number;
  units?: number;
  duration?: string;
  distance?: number;
  className?: string;
}> = ({ 
  entry, 
  target, 
  stop, 
  pnl, 
  rr,
  status,
  time,
  pips,
  units,
  duration,
  distance,
  className = ''
}) => {
  return (
    <div className={`flex flex-wrap gap-2 ${className}`}>
      <TradeSetupTag type="entry" value={entry} />
      {target && <TradeSetupTag type="target" value={target} />}
      {stop && <TradeSetupTag type="stop" value={stop} />}
      {rr && <TradeSetupTag type="rr" value={rr} />}
      {pips !== undefined && <TradeSetupTag type="pips" value={pips} />}
      {units !== undefined && <TradeSetupTag type="units" value={units} />}
      {pnl !== undefined && <TradeSetupTag type="pnl" value={pnl} />}
      {status && <TradeSetupTag type="status" value={status} />}
      {duration && <TradeSetupTag type="duration" value={duration} />}
    </div>
  );
};

export default TradeSetupTag;