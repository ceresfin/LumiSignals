// Market Regimes & Macro Analysis - Tab 4 of the pilot's cockpit
import React, { useState, useMemo } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  AlertCircle, 
  Calendar, 
  Globe,
  Activity,
  DollarSign,
  BarChart3,
  RefreshCw,
  Filter
} from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, BarChart, Bar } from 'recharts';

interface SentimentData {
  currency: string;
  sentiment_score: number;  // -100 to +100
  fear_greed_index: number;  // 0 to 100
  trend: 'bullish' | 'bearish' | 'neutral';
  volume_sentiment: number;
  news_sentiment: number;
  retail_sentiment: number;
}

interface EconomicEvent {
  id: string;
  time: string;
  currency: string;
  impact: 'low' | 'medium' | 'high';
  event_name: string;
  forecast: string;
  previous: string;
  actual?: string;
  surprise?: number;  // Actual vs Forecast difference
}

interface MarketRegimeData {
  regime: 'risk_on' | 'risk_off' | 'neutral';
  confidence: number;  // 0-100
  duration_hours: number;
  volatility_index: number;
  correlation_breakdown: boolean;  // Are correlations breaking down?
  flight_to_quality: boolean;
}

// Mock data - in production this would come from your APIs
const mockSentimentData: SentimentData[] = [
  { currency: 'USD', sentiment_score: 23, fear_greed_index: 68, trend: 'bullish', volume_sentiment: 15, news_sentiment: 28, retail_sentiment: 26 },
  { currency: 'EUR', sentiment_score: 8, fear_greed_index: 55, trend: 'neutral', volume_sentiment: 5, news_sentiment: 12, retail_sentiment: 7 },
  { currency: 'JPY', sentiment_score: -18, fear_greed_index: 32, trend: 'bearish', volume_sentiment: -22, news_sentiment: -15, retail_sentiment: -17 },
  { currency: 'GBP', sentiment_score: -5, fear_greed_index: 47, trend: 'neutral', volume_sentiment: -8, news_sentiment: -3, retail_sentiment: -4 },
  { currency: 'CHF', sentiment_score: 12, fear_greed_index: 58, trend: 'bullish', volume_sentiment: 8, news_sentiment: 18, retail_sentiment: 10 },
  { currency: 'AUD', sentiment_score: 31, fear_greed_index: 72, trend: 'bullish', volume_sentiment: 35, news_sentiment: 28, retail_sentiment: 30 },
  { currency: 'NZD', sentiment_score: 25, fear_greed_index: 69, trend: 'bullish', volume_sentiment: 22, news_sentiment: 29, retail_sentiment: 24 },
  { currency: 'CAD', sentiment_score: 4, fear_greed_index: 52, trend: 'neutral', volume_sentiment: 1, news_sentiment: 8, retail_sentiment: 3 }
];

const mockEconomicEvents: EconomicEvent[] = [
  {
    id: '1',
    time: '2025-01-15T09:30:00Z',
    currency: 'USD',
    impact: 'high',
    event_name: 'Non-Farm Payrolls',
    forecast: '180K',
    previous: '175K',
    actual: '195K',
    surprise: 15000
  },
  {
    id: '2',
    time: '2025-01-15T13:00:00Z',
    currency: 'EUR',
    impact: 'medium',
    event_name: 'ECB Interest Rate Decision',
    forecast: '4.50%',
    previous: '4.50%'
  },
  {
    id: '3',
    time: '2025-01-15T15:30:00Z',
    currency: 'GBP',
    impact: 'high',
    event_name: 'BoE Governor Speech',
    forecast: 'N/A',
    previous: 'N/A'
  },
  {
    id: '4',
    time: '2025-01-16T00:30:00Z',
    currency: 'JPY',
    impact: 'medium',
    event_name: 'CPI YoY',
    forecast: '2.8%',
    previous: '2.9%'
  }
];

const mockMarketRegime: MarketRegimeData = {
  regime: 'risk_on',
  confidence: 78,
  duration_hours: 14.5,
  volatility_index: 23.4,
  correlation_breakdown: false,
  flight_to_quality: false
};

export const MarketRegimes: React.FC = () => {
  const [selectedTimeframe, setSelectedTimeframe] = useState<'1h' | '4h' | '1d' | '1w'>('1d');
  const [showUpcomingOnly, setShowUpcomingOnly] = useState(true);

  // Filter upcoming events
  const upcomingEvents = useMemo(() => {
    const now = new Date();
    return mockEconomicEvents.filter(event => {
      const eventTime = new Date(event.time);
      return showUpcomingOnly ? eventTime > now : true;
    }).sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());
  }, [showUpcomingOnly]);

  // Calculate overall market sentiment
  const overallSentiment = useMemo(() => {
    const avgSentiment = mockSentimentData.reduce((sum, curr) => sum + curr.sentiment_score, 0) / mockSentimentData.length;
    const avgFearGreed = mockSentimentData.reduce((sum, curr) => sum + curr.fear_greed_index, 0) / mockSentimentData.length;
    
    return {
      sentiment: avgSentiment,
      fearGreed: avgFearGreed,
      trend: avgSentiment > 10 ? 'bullish' : avgSentiment < -10 ? 'bearish' : 'neutral'
    };
  }, []);

  const getSentimentColor = (sentiment: number) => {
    if (sentiment > 20) return '#A2C8A1';
    if (sentiment > 0) return '#B6E6C4';
    if (sentiment > -20) return '#FFE4B3';
    return '#CF4505';
  };

  const getFearGreedColor = (index: number) => {
    if (index > 75) return '#CF4505';  // Extreme Greed
    if (index > 55) return '#A2C8A1';  // Greed
    if (index > 45) return '#B6E6C4';  // Neutral
    if (index > 25) return '#FFE4B3';  // Fear
    return '#CF4505';  // Extreme Fear
  };

  const getImpactColor = (impact: string) => {
    switch (impact) {
      case 'high': return '#CF4505';
      case 'medium': return '#FFE4B3';
      case 'low': return '#B6E6C4';
      default: return '#B6E6C4';
    }
  };

  const getRegimeColor = (regime: string) => {
    switch (regime) {
      case 'risk_on': return '#A2C8A1';
      case 'risk_off': return '#CF4505';
      case 'neutral': return '#B6E6C4';
      default: return '#B6E6C4';
    }
  };

  const formatEventTime = (timeString: string) => {
    const date = new Date(timeString);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  };

  return (
    <div className="space-y-6">
      {/* Header Card */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-3xl font-bold text-text-primary-light dark:text-text-primary-dark mb-2">Market Regimes</h2>
            <div className="flex items-center gap-2 text-sm text-text-secondary-light dark:text-text-secondary-dark">
              <Activity className="w-4 h-4 text-pipstop-primary" />
              <span>Real-time sentiment & economic data analysis</span>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-1">
              <select 
                value={selectedTimeframe}
                onChange={(e) => setSelectedTimeframe(e.target.value as any)}
                className="px-3 py-2 bg-transparent text-text-primary-light dark:text-text-primary-dark text-sm font-medium focus:outline-none"
              >
                <option value="1h">1 Hour</option>
                <option value="4h">4 Hours</option>
                <option value="1d">1 Day</option>
                <option value="1w">1 Week</option>
              </select>
            </div>
            
            <button className="p-3 bg-elevated-light dark:bg-elevated-dark border border-border-light dark:border-border-dark text-text-primary-light dark:text-text-primary-dark rounded-lg hover:bg-pipstop-primary hover:text-white hover:border-pipstop-primary transition-all duration-200">
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Market Status Cards */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="flex items-center gap-2 mb-6">
          <Globe className="w-5 h-5 text-pipstop-primary" />
          <span className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Market Status</span>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-2">Market Regime</div>
              <div className="text-xl font-bold" style={{ color: getRegimeColor(mockMarketRegime.regime) }}>
                {mockMarketRegime.regime.replace('_', ' ').toUpperCase()}
              </div>
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mt-1">
                {mockMarketRegime.confidence}% confidence
              </div>
            </div>
          </div>

          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-2">Overall Sentiment</div>
              <div className="text-xl font-bold" style={{ color: getSentimentColor(overallSentiment.sentiment) }}>
                {overallSentiment.sentiment.toFixed(1)}
              </div>
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mt-1 capitalize">
                {overallSentiment.trend}
              </div>
            </div>
          </div>

          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-2">Fear & Greed Index</div>
              <div className="text-xl font-bold" style={{ color: getFearGreedColor(overallSentiment.fearGreed) }}>
                {overallSentiment.fearGreed.toFixed(0)}
              </div>
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mt-1">
                {overallSentiment.fearGreed > 75 ? 'Extreme Greed' : 
                 overallSentiment.fearGreed > 55 ? 'Greed' :
                 overallSentiment.fearGreed > 45 ? 'Neutral' :
                 overallSentiment.fearGreed > 25 ? 'Fear' : 'Extreme Fear'}
              </div>
            </div>
          </div>

          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-2">Volatility Index</div>
              <div className="text-xl font-bold text-text-primary-light dark:text-text-primary-dark">
                {mockMarketRegime.volatility_index.toFixed(1)}
              </div>
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mt-1">
                {mockMarketRegime.volatility_index > 30 ? 'High' : 
                 mockMarketRegime.volatility_index > 20 ? 'Medium' : 'Low'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Analysis Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Currency Sentiment Analysis */}
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
          <div className="flex items-center gap-2 mb-6">
            <BarChart3 className="w-5 h-5 text-pipstop-primary" />
            <span className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Currency Sentiment</span>
          </div>
          
          <div className="space-y-3">
            {mockSentimentData.map((currency) => (
              <div key={currency.currency} className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-4 border border-border-light dark:border-border-dark">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="bg-surface-light dark:bg-surface-dark rounded px-3 py-1">
                      <span className="font-bold text-sm text-text-primary-light dark:text-text-primary-dark">
                        {currency.currency}
                      </span>
                    </div>
                    <div className="flex items-center">
                      {currency.trend === 'bullish' ? (
                        <TrendingUp className="w-4 h-4 text-pipstop-success" />
                      ) : currency.trend === 'bearish' ? (
                        <TrendingDown className="w-4 h-4 text-pipstop-danger" />
                      ) : (
                        <Activity className="w-4 h-4 text-text-secondary-light dark:text-text-secondary-dark" />
                      )}
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-4">
                    <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-2 text-center">
                      <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">Sentiment</div>
                      <div className="text-sm font-bold" style={{ color: getSentimentColor(currency.sentiment_score) }}>
                        {currency.sentiment_score.toFixed(0)}
                      </div>
                    </div>
                    <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-2 text-center">
                      <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-1">F&G Index</div>
                      <div className="text-sm font-bold" style={{ color: getFearGreedColor(currency.fear_greed_index) }}>
                        {currency.fear_greed_index.toFixed(0)}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Economic Calendar */}
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2">
              <Calendar className="w-5 h-5 text-pipstop-primary" />
              <span className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Economic Calendar</span>
            </div>
            <label className="flex items-center gap-2 text-sm text-text-secondary-light dark:text-text-secondary-dark">
              <input
                type="checkbox"
                checked={showUpcomingOnly}
                onChange={(e) => setShowUpcomingOnly(e.target.checked)}
                className="rounded"
              />
              <span>Upcoming only</span>
            </label>
          </div>
          
          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-4 border border-border-light dark:border-border-dark">
            <div className="space-y-3 max-h-80 overflow-y-auto">
              {upcomingEvents.map((event) => (
                <div key={event.id} className="bg-surface-light dark:bg-surface-dark rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-text-primary-light dark:text-text-primary-dark">
                        {formatEventTime(event.time)}
                      </span>
                      <span className="text-xs px-2 py-1 rounded font-medium" style={{
                        background: getImpactColor(event.impact),
                        color: '#121212'
                      }}>
                        {event.impact.toUpperCase()}
                      </span>
                    </div>
                    <div className="bg-elevated-light dark:bg-elevated-dark rounded px-2 py-1">
                      <span className="font-bold text-sm text-text-primary-light dark:text-text-primary-dark">
                        {event.currency}
                      </span>
                    </div>
                  </div>
                  
                  <div className="text-sm text-text-primary-light dark:text-text-primary-dark mb-3">
                    {event.event_name}
                  </div>
                  
                  <div className="flex items-center gap-4 text-xs">
                    <div className="bg-elevated-light dark:bg-elevated-dark rounded px-2 py-1">
                      <span className="text-text-secondary-light dark:text-text-secondary-dark">Forecast: </span>
                      <span className="text-text-primary-light dark:text-text-primary-dark font-medium">{event.forecast}</span>
                    </div>
                    <div className="bg-elevated-light dark:bg-elevated-dark rounded px-2 py-1">
                      <span className="text-text-secondary-light dark:text-text-secondary-dark">Previous: </span>
                      <span className="text-text-primary-light dark:text-text-primary-dark font-medium">{event.previous}</span>
                    </div>
                    {event.actual && (
                      <div className="bg-elevated-light dark:bg-elevated-dark rounded px-2 py-1">
                        <span className="text-text-secondary-light dark:text-text-secondary-dark">Actual: </span>
                        <span className="font-medium" style={{ color: event.surprise && event.surprise > 0 ? '#A2C8A1' : '#CF4505' }}>
                          {event.actual}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Market Regime Indicators */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl p-6 border border-border-light dark:border-border-dark">
        <div className="flex items-center gap-2 mb-6">
          <AlertCircle className="w-5 h-5 text-pipstop-primary" />
          <span className="text-lg font-semibold text-text-primary-light dark:text-text-primary-dark">Market Regime Indicators</span>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-2">Regime Duration</div>
              <div className="text-xl font-bold text-text-primary-light dark:text-text-primary-dark">
                {mockMarketRegime.duration_hours.toFixed(1)}h
              </div>
            </div>
          </div>
          
          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-2">Correlation Breakdown</div>
              <div className="text-xl font-bold" style={{ 
                color: mockMarketRegime.correlation_breakdown ? '#CF4505' : '#A2C8A1' 
              }}>
                {mockMarketRegime.correlation_breakdown ? 'YES' : 'NO'}
              </div>
            </div>
          </div>
          
          <div className="bg-elevated-light dark:bg-elevated-dark rounded-lg p-5 border border-border-light dark:border-border-dark">
            <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-4 text-center">
              <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mb-2">Flight to Quality</div>
              <div className="text-xl font-bold" style={{ 
                color: mockMarketRegime.flight_to_quality ? '#FFE4B3' : '#A2C8A1' 
              }}>
                {mockMarketRegime.flight_to_quality ? 'ACTIVE' : 'INACTIVE'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};