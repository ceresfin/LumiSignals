// Correlation Matrix - Institutional-grade risk management tool
import React, { useMemo } from 'react';
import { AlertTriangle, TrendingUp, TrendingDown, Info } from 'lucide-react';

interface CorrelationData {
  pair1: string;
  pair2: string;
  correlation: number;  // -1 to +1
  lookback_periods: number;
  confidence: number;  // 0 to 1
  last_updated: string;
}

interface PortfolioPosition {
  pair: string;
  position_size: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  risk_percent: number;
}

interface CorrelationMatrixProps {
  positions?: PortfolioPosition[];
  className?: string;
  showOnlyActivePositions?: boolean;
  timeframe?: '1h' | '4h' | '1d' | '1w';
}

// Mock correlation data - in production this would come from your API
const mockCorrelations: CorrelationData[] = [
  { pair1: 'EUR/USD', pair2: 'GBP/USD', correlation: 0.87, lookback_periods: 100, confidence: 0.95, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'EUR/USD', pair2: 'USD/JPY', correlation: -0.34, lookback_periods: 100, confidence: 0.88, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'EUR/USD', pair2: 'USD/CAD', correlation: -0.62, lookback_periods: 100, confidence: 0.92, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'EUR/USD', pair2: 'AUD/USD', correlation: 0.73, lookback_periods: 100, confidence: 0.91, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'GBP/USD', pair2: 'USD/JPY', correlation: -0.28, lookback_periods: 100, confidence: 0.84, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'GBP/USD', pair2: 'USD/CAD', correlation: -0.55, lookback_periods: 100, confidence: 0.89, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'GBP/USD', pair2: 'AUD/USD', correlation: 0.69, lookback_periods: 100, confidence: 0.87, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'USD/JPY', pair2: 'USD/CAD', correlation: 0.41, lookback_periods: 100, confidence: 0.86, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'USD/JPY', pair2: 'AUD/USD', correlation: -0.23, lookback_periods: 100, confidence: 0.79, last_updated: '2025-01-15T14:30:00Z' },
  { pair1: 'USD/CAD', pair2: 'AUD/USD', correlation: -0.48, lookback_periods: 100, confidence: 0.85, last_updated: '2025-01-15T14:30:00Z' },
];

// Mock portfolio positions
const mockPositions: PortfolioPosition[] = [
  { pair: 'EUR/USD', position_size: 150000, entry_price: 1.0845, current_price: 1.0883, pnl: 570, risk_percent: 15 },
  { pair: 'GBP/USD', position_size: -80000, entry_price: 1.2756, current_price: 1.2748, pnl: 64, risk_percent: 8 },
  { pair: 'USD/JPY', position_size: 120000, entry_price: 148.25, current_price: 148.67, pnl: 340, risk_percent: 12 },
  { pair: 'AUD/USD', position_size: 60000, entry_price: 0.6758, current_price: 0.6761, pnl: 18, risk_percent: 6 },
  { pair: 'USD/CAD', position_size: -45000, entry_price: 1.3435, current_price: 1.3428, pnl: 23, risk_percent: 5 },
];

export const CorrelationMatrix: React.FC<CorrelationMatrixProps> = ({
  positions = mockPositions,
  className = '',
  showOnlyActivePositions = true,
  timeframe = '1d'
}) => {
  // Create correlation matrix
  const correlationMatrix = useMemo(() => {
    const pairs = positions.map(p => p.pair);
    const matrix: { [key: string]: { [key: string]: number } } = {};
    
    // Initialize matrix
    pairs.forEach(pair1 => {
      matrix[pair1] = {};
      pairs.forEach(pair2 => {
        if (pair1 === pair2) {
          matrix[pair1][pair2] = 1.0;
        } else {
          // Find correlation data
          const correlationData = mockCorrelations.find(c => 
            (c.pair1 === pair1 && c.pair2 === pair2) ||
            (c.pair1 === pair2 && c.pair2 === pair1)
          );
          matrix[pair1][pair2] = correlationData ? correlationData.correlation : 0;
        }
      });
    });
    
    return matrix;
  }, [positions]);

  // Calculate risk concentration based on correlations
  const riskAnalysis = useMemo(() => {
    const pairs = positions.map(p => p.pair);
    let highCorrelationPairs: string[] = [];
    let totalRiskConcentration = 0;
    
    pairs.forEach(pair1 => {
      pairs.forEach(pair2 => {
        if (pair1 !== pair2) {
          const correlation = correlationMatrix[pair1][pair2];
          if (Math.abs(correlation) > 0.7) {
            highCorrelationPairs.push(`${pair1} & ${pair2}`);
          }
          
          // Calculate risk concentration
          const position1 = positions.find(p => p.pair === pair1);
          const position2 = positions.find(p => p.pair === pair2);
          if (position1 && position2) {
            const riskContribution = Math.abs(correlation) * position1.risk_percent * position2.risk_percent / 100;
            totalRiskConcentration += riskContribution;
          }
        }
      });
    });
    
    return {
      highCorrelationPairs: [...new Set(highCorrelationPairs)],
      totalRiskConcentration: totalRiskConcentration / 2 // Divide by 2 to avoid double counting
    };
  }, [correlationMatrix, positions]);

  // Color mapping for correlation values
  const getCorrelationColor = (correlation: number, opacity: number = 0.8) => {
    const absCorrelation = Math.abs(correlation);
    
    if (correlation > 0.7) {
      // High positive correlation - red (risky)
      return `rgba(207, 69, 5, ${absCorrelation * opacity})`;
    } else if (correlation < -0.7) {
      // High negative correlation - blue (hedging)
      return `rgba(50, 160, 168, ${absCorrelation * opacity})`;
    } else if (absCorrelation > 0.3) {
      // Moderate correlation - orange/yellow
      return `rgba(255, 228, 179, ${absCorrelation * opacity * 0.6})`;
    } else {
      // Low correlation - neutral
      return `rgba(44, 44, 44, ${opacity * 0.5})`;
    }
  };

  const getCorrelationIcon = (correlation: number) => {
    if (correlation > 0.7) {
      return <AlertTriangle className="w-4 h-4" style={{ color: '#CF4505' }} />;
    } else if (correlation < -0.7) {
      return <TrendingDown className="w-4 h-4" style={{ color: '#32A0A8' }} />;
    } else if (Math.abs(correlation) > 0.3) {
      return <TrendingUp className="w-4 h-4" style={{ color: '#FFE4B3' }} />;
    } else {
      return <Info className="w-4 h-4" style={{ color: '#B6E6C4' }} />;
    }
  };

  const pairs = positions.map(p => p.pair);

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <h3 className="text-lg font-semibold" style={{ color: '#F7F2E6' }}>
            Position Correlation Matrix
          </h3>
          <div className="text-sm" style={{ color: '#B6E6C4' }}>
            {timeframe} timeframe • {pairs.length} pairs
          </div>
        </div>
        
        <div className="flex items-center space-x-2">
          <span className="text-sm" style={{ color: '#B6E6C4' }}>
            Risk Concentration: 
          </span>
          <span 
            className="text-sm font-bold"
            style={{ color: riskAnalysis.totalRiskConcentration > 15 ? '#CF4505' : '#A2C8A1' }}
          >
            {riskAnalysis.totalRiskConcentration.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Risk Alerts */}
      {riskAnalysis.highCorrelationPairs.length > 0 && (
        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(207, 69, 5, 0.1)',
          borderColor: '#CF4505'
        }}>
          <div className="flex items-center space-x-2 mb-2">
            <AlertTriangle className="w-5 h-5" style={{ color: '#CF4505' }} />
            <span className="font-medium" style={{ color: '#CF4505' }}>
              High Correlation Alert
            </span>
          </div>
          <p className="text-sm" style={{ color: '#F7F2E6' }}>
            The following pairs show high correlation (&gt;0.7), indicating potential risk concentration:
          </p>
          <ul className="text-sm mt-2 space-y-1">
            {riskAnalysis.highCorrelationPairs.slice(0, 3).map((pair, index) => (
              <li key={index} style={{ color: '#B6E6C4' }}>
                • {pair}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Correlation Matrix */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="w-20 h-12 text-center border text-sm font-medium" style={{ 
                background: 'rgba(30, 30, 30, 0.8)', 
                borderColor: '#2C2C2C',
                color: '#B6E6C4'
              }}>
                Pair
              </th>
              {pairs.map((pair) => (
                <th
                  key={pair}
                  className="w-20 h-12 text-center border font-medium text-xs"
                  style={{
                    background: 'rgba(30, 30, 30, 0.8)',
                    borderColor: '#2C2C2C',
                    color: '#F7F2E6'
                  }}
                >
                  {pair.replace('/', '/\n')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pairs.map((pair1) => (
              <tr key={pair1}>
                <td
                  className="w-20 h-12 text-center border font-medium text-xs"
                  style={{
                    background: 'rgba(30, 30, 30, 0.8)',
                    borderColor: '#2C2C2C',
                    color: '#F7F2E6'
                  }}
                >
                  {pair1.replace('/', '/\n')}
                </td>
                {pairs.map((pair2) => {
                  const correlation = correlationMatrix[pair1][pair2];
                  const isIdentical = pair1 === pair2;
                  
                  return (
                    <td
                      key={pair2}
                      className="w-20 h-12 text-center border cursor-pointer transition-opacity hover:opacity-80"
                      style={{
                        background: isIdentical 
                          ? 'rgba(44, 44, 44, 0.8)' 
                          : getCorrelationColor(correlation),
                        borderColor: '#2C2C2C'
                      }}
                      title={`${pair1} vs ${pair2}: ${correlation.toFixed(2)} correlation`}
                    >
                      {isIdentical ? (
                        <span className="text-xs" style={{ color: '#B6E6C4' }}>1.00</span>
                      ) : (
                        <div className="flex flex-col items-center">
                          <div className="flex items-center space-x-1">
                            {getCorrelationIcon(correlation)}
                          </div>
                          <span 
                            className="text-xs font-bold"
                            style={{ color: '#F7F2E6' }}
                          >
                            {correlation.toFixed(2)}
                          </span>
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Position Impact Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <div className="text-sm" style={{ color: '#B6E6C4' }}>Diversification Score</div>
          <div className="text-xl font-bold" style={{ 
            color: riskAnalysis.totalRiskConcentration > 15 ? '#CF4505' : '#A2C8A1' 
          }}>
            {Math.max(0, 100 - riskAnalysis.totalRiskConcentration).toFixed(0)}%
          </div>
        </div>

        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <div className="text-sm" style={{ color: '#B6E6C4' }}>High Correlations</div>
          <div className="text-xl font-bold" style={{ 
            color: riskAnalysis.highCorrelationPairs.length > 0 ? '#CF4505' : '#A2C8A1' 
          }}>
            {riskAnalysis.highCorrelationPairs.length}
          </div>
        </div>

        <div className="p-4 rounded-lg border" style={{
          background: 'rgba(30, 30, 30, 0.8)',
          borderColor: '#2C2C2C'
        }}>
          <div className="text-sm" style={{ color: '#B6E6C4' }}>Active Positions</div>
          <div className="text-xl font-bold" style={{ color: '#F7F2E6' }}>
            {positions.length}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-between text-xs" style={{ color: '#B6E6C4' }}>
        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-2">
            <div className="w-4 h-4 rounded" style={{ background: 'rgba(207, 69, 5, 0.8)' }} />
            <span>High Positive (&gt;0.7)</span>
          </div>
          <div className="flex items-center space-x-2">
            <div className="w-4 h-4 rounded" style={{ background: 'rgba(255, 228, 179, 0.6)' }} />
            <span>Moderate (0.3-0.7)</span>
          </div>
          <div className="flex items-center space-x-2">
            <div className="w-4 h-4 rounded" style={{ background: 'rgba(44, 44, 44, 0.8)' }} />
            <span>Low (&lt;0.3)</span>
          </div>
          <div className="flex items-center space-x-2">
            <div className="w-4 h-4 rounded" style={{ background: 'rgba(50, 160, 168, 0.8)' }} />
            <span>High Negative (&lt;-0.7)</span>
          </div>
        </div>
        <div>
          Higher correlation = Higher risk concentration
        </div>
      </div>
    </div>
  );
};