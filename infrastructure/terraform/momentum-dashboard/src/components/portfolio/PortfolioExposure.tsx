// Enhanced Portfolio & Risk - Real-time RDS data showcase
import React, { useState, useEffect } from 'react';
import { PieChart, BarChart, Bar, Cell, Pie, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { api } from '../../services/api';
import { 
  TrendingUp, 
  TrendingDown, 
  Activity, 
  DollarSign, 
  Target, 
  PieChart as PieChartIcon,
  BarChart3,
  Wallet,
  Globe,
  AlertTriangle,
  RefreshCw
} from 'lucide-react';

interface Position {
  currency_pair: string;
  net_units: number;
  trade_count: number;
  unrealized_pnl: number;
  profit_pips: number;
  direction: 'Long' | 'Short' | 'Neutral';
  margin_used: number;
}

interface Exposure {
  currency: string;
  net_exposure: number;
  usd_value: number;
  risk_percent: number;
  exposure_direction: 'Long' | 'Short' | 'Neutral';
}

interface PortfolioSummary {
  total_positions: number;
  total_unrealized_pnl: number;
  total_margin_used: number;
  currency_exposures: number;
}

export const PortfolioExposure: React.FC = () => {
  const [positions, setPositions] = useState<Position[]>([]);
  const [exposures, setExposures] = useState<Exposure[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'overview' | 'positions' | 'exposures'>('overview');
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

      // If all requests failed, show error
      if (!positionsRes.success && !exposuresRes.success && !summaryRes.success) {
        setError('Unable to connect to RDS data source. Check API Gateway connection.');
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

  // Prepare chart data
  const exposureChartData = exposures.map(exp => ({
    name: exp.currency,
    value: Math.abs(exp.usd_value),
    risk: exp.risk_percent,
    direction: exp.exposure_direction
  }));

  const positionChartData = positions.map(pos => ({
    name: pos.currency_pair,
    pnl: pos.unrealized_pnl,
    pips: pos.profit_pips,
    direction: pos.direction
  }));

  if (loading) {
    return (
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400 mr-3"></div>
          <span className="text-text-secondary-light dark:text-text-secondary-dark">Loading live RDS portfolio data...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="text-center">
          <div className="flex items-center justify-center mb-4">
            <AlertTriangle className="w-8 h-8 text-red-400 mr-2" />
            <div className="text-red-400 text-lg font-semibold">RDS Connection Issue</div>
          </div>
          <div className="text-text-secondary-light dark:text-text-secondary-dark mb-4">{error}</div>
          <button 
            onClick={fetchPortfolioData}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center mx-auto"
          >
            <RefreshCw className="w-4 h-4 mr-2" />
            Retry Connection
          </button>
          <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark mt-4">
            API Endpoint: https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Navigation */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Wallet className="w-6 h-6 text-blue-400" />
          <h1 className="text-2xl font-bold text-text-primary-light dark:text-text-primary-dark">Portfolio & Risk</h1>
          <div className="bg-green-500/20 text-green-300 px-2 py-1 rounded text-sm">
            Live RDS Data
          </div>
        </div>
        <div className="flex items-center space-x-4">
          <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
            Updated: {lastUpdated}
          </div>
          <button 
            onClick={fetchPortfolioData}
            className="p-2 text-text-secondary-light dark:text-text-secondary-dark hover:text-text-primary-light dark:hover:text-text-primary-dark"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Sub-navigation */}
      <div className="flex space-x-4 border-b border-border-light dark:border-border-dark">
        {[
          { id: 'overview', label: 'Overview', icon: <BarChart3 className="w-4 h-4" /> },
          { id: 'positions', label: 'Positions', icon: <Target className="w-4 h-4" /> },
          { id: 'exposures', label: 'Exposures', icon: <Globe className="w-4 h-4" /> }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveView(tab.id as any)}
            className={`flex items-center space-x-2 px-4 py-2 border-b-2 transition-colors ${
              activeView === tab.id
                ? 'border-blue-400 text-blue-400'
                : 'border-transparent text-text-secondary-light dark:text-text-secondary-dark hover:text-text-primary-light dark:hover:text-text-primary-dark'
            }`}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeView === 'overview' && (
        <div className="space-y-6">
          {/* Summary Cards */}
          {summary && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-4 border border-border-light dark:border-border-dark">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Total P&L</p>
                    <p className={`text-xl font-bold ${getDirectionColor('', summary.total_unrealized_pnl)}`}>
                      {formatCurrency(summary.total_unrealized_pnl)}
                    </p>
                  </div>
                  <DollarSign className={`w-8 h-8 ${getDirectionColor('', summary.total_unrealized_pnl)}`} />
                </div>
              </div>

              <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-4 border border-border-light dark:border-border-dark">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Active Positions</p>
                    <p className="text-xl font-bold text-text-primary-light dark:text-text-primary-dark">{summary.total_positions}</p>
                  </div>
                  <Target className="w-8 h-8 text-blue-400" />
                </div>
              </div>

              <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-4 border border-border-light dark:border-border-dark">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Margin Used</p>
                    <p className="text-xl font-bold text-text-primary-light dark:text-text-primary-dark">{formatCurrency(summary.total_margin_used)}</p>
                  </div>
                  <Activity className="w-8 h-8 text-yellow-400" />
                </div>
              </div>

              <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-4 border border-border-light dark:border-border-dark">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Currency Exposures</p>
                    <p className="text-xl font-bold text-text-primary-light dark:text-text-primary-dark">{summary.currency_exposures}</p>
                  </div>
                  <Globe className="w-8 h-8 text-purple-400" />
                </div>
              </div>
            </div>
          )}

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* P&L Chart */}
            {positionChartData.length > 0 && (
              <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
                <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark mb-4">Position P&L</h3>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={positionChartData}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="pnl" fill="#3B82F6" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Currency Exposure Pie Chart */}
            {exposureChartData.length > 0 && (
              <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
                <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark mb-4">Currency Exposure</h3>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={exposureChartData}
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      fill="#8884d8"
                      dataKey="value"
                      label={({ name, value }) => `${name}: $${value.toFixed(0)}`}
                    >
                      {exposureChartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.direction === 'Long' ? '#10B981' : '#EF4444'} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value) => formatCurrency(Number(value))} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Positions Tab */}
      {activeView === 'positions' && (
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
          <div className="flex items-center space-x-2 mb-4">
            <Target className="w-5 h-5 text-blue-400" />
            <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Currency Pair Positions</h3>
          </div>
          {positions.length === 0 ? (
            <p className="text-text-secondary-light dark:text-text-secondary-dark text-center py-8">No active positions</p>
          ) : (
            <div className="space-y-3">
              {positions.map((position, index) => (
                <div key={index} className="bg-background-light dark:bg-background-dark rounded-lg p-4 border border-border-light dark:border-border-dark">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2">
                      <div className={`flex items-center space-x-1 ${getDirectionColor(position.direction)}`}>
                        {getDirectionIcon(position.direction)}
                        <span className="font-semibold text-lg">{position.currency_pair}</span>
                      </div>
                      <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
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
                      <p className="text-text-secondary-light dark:text-text-secondary-dark">Net Units</p>
                      <p className="text-text-primary-light dark:text-text-primary-dark font-medium">{position.net_units.toLocaleString()}</p>
                    </div>
                    <div>
                      <p className="text-text-secondary-light dark:text-text-secondary-dark">Direction</p>
                      <p className={`font-medium ${getDirectionColor(position.direction)}`}>{position.direction}</p>
                    </div>
                    <div>
                      <p className="text-text-secondary-light dark:text-text-secondary-dark">Margin</p>
                      <p className="text-text-primary-light dark:text-text-primary-dark font-medium">{formatCurrency(position.margin_used)}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Exposures Tab */}
      {activeView === 'exposures' && (
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
          <div className="flex items-center space-x-2 mb-4">
            <Globe className="w-5 h-5 text-purple-400" />
            <h3 className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Currency Exposures</h3>
          </div>
          {exposures.length === 0 ? (
            <p className="text-text-secondary-light dark:text-text-secondary-dark text-center py-8">No currency exposures</p>
          ) : (
            <div className="space-y-3">
              {exposures.map((exposure, index) => (
                <div key={index} className="bg-background-light dark:bg-background-dark rounded-lg p-4 border border-border-light dark:border-border-dark">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2">
                      <div className={`flex items-center space-x-1 ${getDirectionColor(exposure.exposure_direction)}`}>
                        {getDirectionIcon(exposure.exposure_direction)}
                        <span className="font-semibold text-2xl">{exposure.currency}</span>
                      </div>
                      <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                        {exposure.risk_percent.toFixed(2)}% risk
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-semibold text-text-primary-light dark:text-text-primary-dark">{formatCurrency(exposure.usd_value)}</div>
                      <div className={`text-sm ${getDirectionColor(exposure.exposure_direction)}`}>
                        {exposure.net_exposure.toLocaleString()} units
                      </div>
                    </div>
                  </div>
                  {/* Risk indicator bar */}
                  <div className="mt-2">
                    <div className="w-full bg-gray-600 rounded-full h-2">
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
      )}
    </div>
  );
};