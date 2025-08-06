// Currency Strength Matrix - Institutional-grade relative strength analysis
import React, { useMemo } from 'react';
import { TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react';

interface CurrencyStrength {
  currency: string;
  strength_score: number;  // -100 to +100
  trend: 'up' | 'down' | 'flat';
  change_24h: number;
  change_4h: number;
  change_1h: number;
}

interface CurrencyPairStrength {
  pair: string;
  base_currency: string;
  quote_currency: string;
  strength_differential: number;  // -100 to +100
  change_percent: number;
  volume_factor: number;
  momentum_score: number;
}

interface CurrencyStrengthMatrixProps {
  className?: string;
  showTimeframes?: boolean;
  autoRefresh?: boolean;
  onPairSelect?: (pair: string) => void;
}

// Mock data - in production this would come from your API
const mockCurrencyStrengths: CurrencyStrength[] = [
  { currency: 'USD', strength_score: 15.2, trend: 'up', change_24h: 0.8, change_4h: 0.3, change_1h: 0.1 },
  { currency: 'EUR', strength_score: 8.7, trend: 'up', change_24h: 0.4, change_4h: 0.2, change_1h: 0.1 },
  { currency: 'JPY', strength_score: -12.3, trend: 'down', change_24h: -0.6, change_4h: -0.3, change_1h: -0.2 },
  { currency: 'GBP', strength_score: 3.1, trend: 'flat', change_24h: 0.1, change_4h: 0.0, change_1h: 0.0 },
  { currency: 'CHF', strength_score: -5.8, trend: 'down', change_24h: -0.3, change_4h: -0.1, change_1h: -0.1 },
  { currency: 'AUD', strength_score: 7.9, trend: 'up', change_24h: 0.5, change_4h: 0.2, change_1h: 0.1 },
  { currency: 'NZD', strength_score: 12.4, trend: 'up', change_24h: 0.7, change_4h: 0.3, change_1h: 0.2 },
  { currency: 'CAD', strength_score: -3.2, trend: 'down', change_24h: -0.2, change_4h: -0.1, change_1h: 0.0 }
];

export const CurrencyStrengthMatrix: React.FC<CurrencyStrengthMatrixProps> = ({
  className = '',
  showTimeframes = true,
  autoRefresh = true,
  onPairSelect
}) => {
  // Calculate strength differentials for all currency pairs
  const strengthMatrix = useMemo(() => {
    const matrix: { [key: string]: CurrencyPairStrength } = {};
    
    mockCurrencyStrengths.forEach(baseCurrency => {
      mockCurrencyStrengths.forEach(quoteCurrency => {
        if (baseCurrency.currency !== quoteCurrency.currency) {
          const pairKey = `${baseCurrency.currency}/${quoteCurrency.currency}`;
          const strengthDiff = baseCurrency.strength_score - quoteCurrency.strength_score;
          
          matrix[pairKey] = {
            pair: pairKey,
            base_currency: baseCurrency.currency,
            quote_currency: quoteCurrency.currency,
            strength_differential: strengthDiff,
            change_percent: baseCurrency.change_24h - quoteCurrency.change_24h,
            volume_factor: Math.random() * 0.5 + 0.5, // Mock volume factor
            momentum_score: Math.abs(strengthDiff) * (Math.random() * 0.3 + 0.7)
          };
        }
      });
    });
    
    return matrix;
  }, []);

  // Color mapping for strength differential
  const getStrengthColor = (differential: number, opacity: number = 1) => {
    const normalizedStrength = Math.max(-100, Math.min(100, differential));
    const intensity = Math.abs(normalizedStrength) / 100;
    
    if (normalizedStrength > 0) {
      // Positive strength - green gradient
      const greenIntensity = Math.min(intensity * 1.5, 1);
      return `rgba(162, 200, 161, ${greenIntensity * opacity})`;
    } else if (normalizedStrength < 0) {
      // Negative strength - red gradient
      const redIntensity = Math.min(intensity * 1.5, 1);
      return `rgba(207, 69, 5, ${redIntensity * opacity})`;
    } else {
      // Neutral
      return `rgba(44, 44, 44, ${opacity})`;
    }
  };

  const getStrengthIcon = (trend: string) => {
    switch (trend) {
      case 'up':
        return <TrendingUp className="w-4 h-4" style={{ color: '#A2C8A1' }} />;
      case 'down':
        return <TrendingDown className="w-4 h-4" style={{ color: '#CF4505' }} />;
      default:
        return <Minus className="w-4 h-4" style={{ color: '#B6E6C4' }} />;
    }
  };

  const handleCellClick = (pair: string) => {
    if (onPairSelect) {
      onPairSelect(pair);
    }
  };

  const currencies = mockCurrencyStrengths.map(c => c.currency);

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <h3 className="text-lg font-semibold" style={{ color: '#F7F2E6' }}>
            Currency Strength Matrix
          </h3>
          <div className="text-sm" style={{ color: '#B6E6C4' }}>
            Real-time relative strength analysis
          </div>
        </div>
        
        {autoRefresh && (
          <button
            className="p-2 rounded-lg transition-colors hover:bg-gray-700"
            style={{ color: '#B6E6C4' }}
            title="Refresh Matrix"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Individual Currency Strengths */}
      <div className="grid grid-cols-4 lg:grid-cols-8 gap-2">
        {mockCurrencyStrengths
          .sort((a, b) => b.strength_score - a.strength_score)
          .map((currency) => (
            <div
              key={currency.currency}
              className="p-3 rounded-lg border text-center"
              style={{
                background: 'rgba(30, 30, 30, 0.8)',
                borderColor: '#2C2C2C'
              }}
            >
              <div className="flex items-center justify-center space-x-1 mb-2">
                <span className="font-bold text-sm" style={{ color: '#F7F2E6' }}>
                  {currency.currency}
                </span>
                {getStrengthIcon(currency.trend)}
              </div>
              <div
                className="text-xs font-medium"
                style={{ color: currency.strength_score >= 0 ? '#A2C8A1' : '#CF4505' }}
              >
                {currency.strength_score >= 0 ? '+' : ''}{currency.strength_score.toFixed(1)}
              </div>
              {showTimeframes && (
                <div className="text-xs mt-1" style={{ color: '#B6E6C4' }}>
                  24h: {currency.change_24h >= 0 ? '+' : ''}{currency.change_24h.toFixed(1)}%
                </div>
              )}
            </div>
          ))}
      </div>

      {/* Strength Matrix Grid */}
      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="w-12 h-12 text-center border" style={{ 
                  background: 'rgba(30, 30, 30, 0.8)', 
                  borderColor: '#2C2C2C',
                  color: '#B6E6C4'
                }}>
                  {/* Empty top-left cell */}
                </th>
                {currencies.map((currency) => (
                  <th
                    key={currency}
                    className="w-12 h-12 text-center border font-medium text-xs"
                    style={{
                      background: 'rgba(30, 30, 30, 0.8)',
                      borderColor: '#2C2C2C',
                      color: '#F7F2E6'
                    }}
                  >
                    {currency}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {currencies.map((baseCurrency) => (
                <tr key={baseCurrency}>
                  <td
                    className="w-12 h-12 text-center border font-medium text-xs"
                    style={{
                      background: 'rgba(30, 30, 30, 0.8)',
                      borderColor: '#2C2C2C',
                      color: '#F7F2E6'
                    }}
                  >
                    {baseCurrency}
                  </td>
                  {currencies.map((quoteCurrency) => {
                    if (baseCurrency === quoteCurrency) {
                      return (
                        <td
                          key={quoteCurrency}
                          className="w-12 h-12 text-center border"
                          style={{
                            background: 'rgba(44, 44, 44, 0.5)',
                            borderColor: '#2C2C2C'
                          }}
                        >
                          <span className="text-xs" style={{ color: '#B6E6C4' }}>—</span>
                        </td>
                      );
                    }

                    const pairKey = `${baseCurrency}/${quoteCurrency}`;
                    const pairData = strengthMatrix[pairKey];
                    
                    if (!pairData) return null;

                    return (
                      <td
                        key={quoteCurrency}
                        className="w-12 h-12 text-center border cursor-pointer transition-opacity hover:opacity-80"
                        style={{
                          background: getStrengthColor(pairData.strength_differential, 0.8),
                          borderColor: '#2C2C2C'
                        }}
                        onClick={() => handleCellClick(pairKey)}
                        title={`${pairKey}: ${pairData.strength_differential.toFixed(1)} (${pairData.change_percent >= 0 ? '+' : ''}${pairData.change_percent.toFixed(2)}%)`}
                      >
                        <div className="flex flex-col items-center">
                          <span 
                            className="text-xs font-bold"
                            style={{ color: '#F7F2E6' }}
                          >
                            {pairData.strength_differential.toFixed(0)}
                          </span>
                          <span 
                            className="text-xs"
                            style={{ color: pairData.change_percent >= 0 ? '#A2C8A1' : '#CF4505' }}
                          >
                            {pairData.change_percent >= 0 ? '+' : ''}{pairData.change_percent.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-between text-xs" style={{ color: '#B6E6C4' }}>
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <div className="w-4 h-4 rounded" style={{ background: 'rgba(162, 200, 161, 0.8)' }} />
            <span>Strong Performance</span>
          </div>
          <div className="flex items-center space-x-2">
            <div className="w-4 h-4 rounded" style={{ background: 'rgba(44, 44, 44, 0.8)' }} />
            <span>Neutral</span>
          </div>
          <div className="flex items-center space-x-2">
            <div className="w-4 h-4 rounded" style={{ background: 'rgba(207, 69, 5, 0.8)' }} />
            <span>Weak Performance</span>
          </div>
        </div>
        <div>
          Click cells to analyze pair in detail
        </div>
      </div>
    </div>
  );
};