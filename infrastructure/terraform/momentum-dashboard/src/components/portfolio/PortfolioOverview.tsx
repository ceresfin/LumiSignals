// Enhanced Portfolio Overview - Showcasing RDS Positions & Exposures Data
import React, { useState, useEffect } from 'react';
import { api } from '../../services/api';
import { 
  TrendingUp, 
  TrendingDown, 
  Activity, 
  DollarSign, 
  Target, 
  Clock, 
  Zap,
  AlertTriangle,
  CheckCircle,
  PieChart,
  BarChart3,
  Wallet,
  Globe
} from 'lucide-react';

interface Position {
  currency_pair: string;
  long_units: number;
  short_units: number;
  net_units: number;
  trade_count: number;
  long_trades: number;
  short_trades: number;
  average_entry: number;
  current_price: number;
  distance_pips: number;
  profit_pips: number;
  unrealized_pnl: number;
  margin_used: number;
  largest_position: number;
  concentration_percent: number;
  last_updated: string;
  direction: 'Long' | 'Short' | 'Neutral';
}

interface Exposure {
  currency: string;
  net_exposure: number;
  long_exposure: number;
  short_exposure: number;
  usd_value: number;
  risk_percent: number;
  last_updated: string;
  exposure_direction: 'Long' | 'Short' | 'Neutral';
}

interface PortfolioSummary {
  total_positions: number;
  total_unrealized_pnl: number;
  total_margin_used: number;
  currency_exposures: number;
  highest_risk_currency: {
    currency: string;
    risk_percent: number;
    usd_value: number;
    direction: string;
  } | null;
  largest_position: {
    currency_pair: string;
    net_units: number;
    unrealized_pnl: number;
    direction: string;
  } | null;
  last_updated: string;
}

const PortfolioOverview: React.FC = () => {
  const [positions, setPositions] = useState<Position[]>([]);
  const [exposures, setExposures] = useState<Exposure[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>('');

  const fetchPortfolioData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [positionsRes, exposuresRes, summaryRes] = await Promise.all([
        api.getPositionsFromRDS(),
        api.getExposuresFromRDS(),
        api.getPortfolioSummaryFromRDS()
      ]);

      if (positionsRes.success) {
        setPositions(positionsRes.data || []);
      }

      if (exposuresRes.success) {
        setExposures(exposuresRes.data || []);
      }

      if (summaryRes.success) {
        setSummary(summaryRes.data);
      }

      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch portfolio data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolioData();
    const interval = setInterval(fetchPortfolioData, 30000); // Refresh every 30 seconds
    return () => clearInterval(interval);
  }, []);

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(amount);
  };

  const formatPips = (pips: number) => {
    return `${pips > 0 ? '+' : ''}${pips.toFixed(1)} pips`;
  };

  const getDirectionColor = (direction: string, pnl?: number) => {
    if (pnl !== undefined) {
      return pnl > 0 ? 'text-green-400' : pnl < 0 ? 'text-red-400' : 'text-gray-400';
    }
    switch (direction) {
      case 'Long': return 'text-green-400';
      case 'Short': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getDirectionIcon = (direction: string) => {
    switch (direction) {
      case 'Long': return <TrendingUp className="w-4 h-4" />;
      case 'Short': return <TrendingDown className="w-4 h-4" />;
      default: return <Activity className="w-4 h-4" />;
    }
  };

  if (loading) {
    return (
      <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-lg p-6">
        <div className="flex items-center justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
          <span className="ml-3 text-slate-300">Loading portfolio data...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-6">
        <div className="flex items-center">
          <AlertTriangle className="w-5 h-5 text-red-400 mr-2" />
          <span className="text-red-300">Error: {error}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Wallet className="w-6 h-6 text-blue-400" />
          <h2 className="text-2xl font-bold text-white">Portfolio Overview</h2>
          <div className="bg-green-500/20 text-green-300 px-2 py-1 rounded text-sm">
            Live RDS Data
          </div>
        </div>
        <div className="text-sm text-slate-400">
          Last updated: {lastUpdated}
        </div>
      </div>

      {/* Portfolio Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-400">Total P&L</p>
                <p className={`text-xl font-bold ${getDirectionColor('', summary.total_unrealized_pnl)}`}>
                  {formatCurrency(summary.total_unrealized_pnl)}
                </p>
              </div>
              <DollarSign className={`w-8 h-8 ${getDirectionColor('', summary.total_unrealized_pnl)}`} />
            </div>
          </div>

          <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-400">Active Positions</p>
                <p className="text-xl font-bold text-white">{summary.total_positions}</p>
              </div>
              <Target className="w-8 h-8 text-blue-400" />
            </div>
          </div>

          <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-400">Margin Used</p>
                <p className="text-xl font-bold text-white">{formatCurrency(summary.total_margin_used)}</p>
              </div>
              <Activity className="w-8 h-8 text-yellow-400" />
            </div>
          </div>

          <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-400">Currency Exposures</p>
                <p className="text-xl font-bold text-white">{summary.currency_exposures}</p>
              </div>
              <Globe className="w-8 h-8 text-purple-400" />
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Positions Table */}
        <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-lg">
          <div className="p-4 border-b border-slate-700/50">
            <div className="flex items-center space-x-2">
              <BarChart3 className="w-5 h-5 text-blue-400" />
              <h3 className="text-lg font-semibold text-white">Currency Pair Positions</h3>
            </div>
          </div>
          <div className="p-4">
            {positions.length === 0 ? (
              <p className="text-slate-400 text-center py-4">No active positions</p>
            ) : (
              <div className="space-y-3">
                {positions.map((position, index) => (
                  <div key={index} className="bg-slate-800/50 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center space-x-2">
                        <div className={`flex items-center space-x-1 ${getDirectionColor(position.direction)}`}>
                          {getDirectionIcon(position.direction)}
                          <span className="font-semibold">{position.currency_pair}</span>
                        </div>
                        <div className="text-sm text-slate-400">
                          {position.trade_count} trade{position.trade_count !== 1 ? 's' : ''}
                        </div>
                      </div>
                      <div className={`text-right ${getDirectionColor('', position.unrealized_pnl)}`}>
                        <div className="font-semibold">{formatCurrency(position.unrealized_pnl)}</div>
                        <div className="text-sm">{formatPips(position.profit_pips)}</div>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-4 text-sm">
                      <div>
                        <p className="text-slate-400">Net Units</p>
                        <p className="text-white">{position.net_units.toLocaleString()}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Avg Entry</p>
                        <p className="text-white">{position.average_entry.toFixed(5)}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Margin</p>
                        <p className="text-white">{formatCurrency(position.margin_used)}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Currency Exposures */}
        <div className="bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-lg">
          <div className="p-4 border-b border-slate-700/50">
            <div className="flex items-center space-x-2">
              <PieChart className="w-5 h-5 text-purple-400" />
              <h3 className="text-lg font-semibold text-white">Currency Exposures</h3>
            </div>
          </div>
          <div className="p-4">
            {exposures.length === 0 ? (
              <p className="text-slate-400 text-center py-4">No currency exposures</p>
            ) : (
              <div className="space-y-3">
                {exposures.map((exposure, index) => (
                  <div key={index} className="bg-slate-800/50 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center space-x-2">
                        <div className={`flex items-center space-x-1 ${getDirectionColor(exposure.exposure_direction)}`}>
                          {getDirectionIcon(exposure.exposure_direction)}
                          <span className="font-semibold text-lg">{exposure.currency}</span>
                        </div>
                        <div className="text-sm text-slate-400">
                          {exposure.risk_percent.toFixed(2)}% risk
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold text-white">{formatCurrency(exposure.usd_value)}</div>
                        <div className={`text-sm ${getDirectionColor(exposure.exposure_direction)}`}>
                          {exposure.net_exposure.toLocaleString()} units
                        </div>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <p className="text-slate-400">Long Exposure</p>
                        <p className="text-green-400">{exposure.long_exposure.toLocaleString()}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Short Exposure</p>
                        <p className="text-red-400">{exposure.short_exposure.toLocaleString()}</p>
                      </div>
                    </div>
                    {/* Risk indicator bar */}
                    <div className="mt-2">
                      <div className="w-full bg-slate-700 rounded-full h-2">
                        <div 
                          className={`h-2 rounded-full ${
                            exposure.risk_percent > 2 ? 'bg-red-500' : 
                            exposure.risk_percent > 1 ? 'bg-yellow-500' : 'bg-green-500'
                          }`}
                          style={{ width: `${Math.min(exposure.risk_percent * 20, 100)}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Largest Position & Highest Risk Highlights */}
      {summary && (summary.largest_position || summary.highest_risk_currency) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {summary.largest_position && (
            <div className="bg-blue-900/20 border border-blue-500/30 rounded-lg p-4">
              <div className="flex items-center space-x-2 mb-2">
                <Target className="w-5 h-5 text-blue-400" />
                <h4 className="font-semibold text-blue-300">Largest Position</h4>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-white font-semibold">{summary.largest_position.currency_pair}</p>
                  <p className="text-slate-400">{summary.largest_position.net_units.toLocaleString()} units</p>
                </div>
                <div className="text-right">
                  <p className={`font-semibold ${getDirectionColor('', summary.largest_position.unrealized_pnl)}`}>
                    {formatCurrency(summary.largest_position.unrealized_pnl)}
                  </p>
                  <p className={`text-sm ${getDirectionColor(summary.largest_position.direction)}`}>
                    {summary.largest_position.direction}
                  </p>
                </div>
              </div>
            </div>
          )}

          {summary.highest_risk_currency && (
            <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4">
              <div className="flex items-center space-x-2 mb-2">
                <AlertTriangle className="w-5 h-5 text-red-400" />
                <h4 className="font-semibold text-red-300">Highest Risk Currency</h4>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-white font-semibold">{summary.highest_risk_currency.currency}</p>
                  <p className="text-slate-400">{summary.highest_risk_currency.risk_percent.toFixed(2)}% of portfolio</p>
                </div>
                <div className="text-right">
                  <p className="font-semibold text-white">
                    {formatCurrency(summary.highest_risk_currency.usd_value)}
                  </p>
                  <p className={`text-sm ${getDirectionColor(summary.highest_risk_currency.direction)}`}>
                    {summary.highest_risk_currency.direction} Exposure
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default PortfolioOverview;