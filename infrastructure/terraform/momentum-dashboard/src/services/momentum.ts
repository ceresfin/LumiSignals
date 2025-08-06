// Momentum calculation service - builds on existing LumiSignals algorithms
import { MomentumData, MomentumSignal, TimeframeMomentum, PriceData, CurrencyPair } from '../types/momentum';

// Momentum calculation weights (from existing implementation)
const TIMEFRAME_WEIGHTS = {
  '48h': 3.0,
  '24h': 2.5,
  '4h': 2.0,
  '1h': 1.5,
  '15m': 1.0
};

// Thresholds for momentum strength classification
const MOMENTUM_THRESHOLDS = {
  weak: 0.001,    // 0.1%
  strong: 0.005   // 0.5%
};

// Signal generation thresholds
const SIGNAL_THRESHOLDS = {
  strong_bullish: 4,    // 4+ bullish timeframes + 1+ strong
  weak_bullish: 3,      // 3+ bullish timeframes
  neutral: 2,           // Mixed signals
  weak_bearish: 3,      // 3+ bearish timeframes
  strong_bearish: 4     // 4+ bearish timeframes + 1+ strong
};

/**
 * Calculate percentage change between two prices
 */
function calculatePercentageChange(oldPrice: number, newPrice: number): number {
  return (newPrice - oldPrice) / oldPrice;
}

/**
 * Calculate momentum for a specific timeframe
 */
function calculateTimeframeMomentum(
  currentPrice: number, 
  historicalPrice: number, 
  volume: number = 1
): TimeframeMomentum {
  const change = calculatePercentageChange(historicalPrice, currentPrice);
  const absChange = Math.abs(change);
  
  return {
    direction: change >= 0 ? 'bullish' : 'bearish',
    strength: absChange >= MOMENTUM_THRESHOLDS.strong ? 'strong' : 'weak',
    change_percent: change,
    volume_factor: volume
  };
}

/**
 * Extract historical prices for different timeframes
 * This assumes price_data is ordered by timestamp (newest first)
 */
function extractTimeframePrices(priceData: PriceData[]): Record<string, number> {
  if (priceData.length === 0) return {};
  
  const currentPrice = priceData[0].close;
  const now = new Date(priceData[0].timestamp);
  
  // Calculate approximate data points for each timeframe
  const timeframes = {
    '15m': 1,      // 1 data point back (15 minutes)
    '1h': 4,       // 4 data points back (1 hour)
    '4h': 16,      // 16 data points back (4 hours)
    '24h': 96,     // 96 data points back (24 hours)
    '48h': 192     // 192 data points back (48 hours)
  };
  
  const historicalPrices: Record<string, number> = {};
  
  Object.entries(timeframes).forEach(([timeframe, pointsBack]) => {
    if (priceData.length > pointsBack) {
      historicalPrices[timeframe] = priceData[pointsBack].close;
    } else {
      // Use oldest available data if we don't have enough history
      historicalPrices[timeframe] = priceData[priceData.length - 1].close;
    }
  });
  
  return historicalPrices;
}

/**
 * Generate momentum signal based on timeframe analysis
 */
function generateMomentumSignal(timeframes: Record<string, TimeframeMomentum>): MomentumSignal {
  const bullishCount = Object.values(timeframes).filter(tf => tf.direction === 'bullish').length;
  const bearishCount = Object.values(timeframes).filter(tf => tf.direction === 'bearish').length;
  const strongCount = Object.values(timeframes).filter(tf => tf.strength === 'strong').length;
  
  // Strong signals require both majority agreement and strong momentum
  if (bullishCount >= SIGNAL_THRESHOLDS.strong_bullish && strongCount >= 1) {
    return 'STRONG_BULLISH';
  }
  
  if (bearishCount >= SIGNAL_THRESHOLDS.strong_bearish && strongCount >= 1) {
    return 'STRONG_BEARISH';
  }
  
  // Weak signals require majority agreement
  if (bullishCount >= SIGNAL_THRESHOLDS.weak_bullish) {
    return 'WEAK_BULLISH';
  }
  
  if (bearishCount >= SIGNAL_THRESHOLDS.weak_bearish) {
    return 'WEAK_BEARISH';
  }
  
  return 'NEUTRAL';
}

/**
 * Calculate composite momentum score (-100 to +100)
 */
function calculateCompositeScore(timeframes: Record<string, TimeframeMomentum>): number {
  let weightedSum = 0;
  let totalWeight = 0;
  
  Object.entries(timeframes).forEach(([timeframe, momentum]) => {
    const weight = TIMEFRAME_WEIGHTS[timeframe as keyof typeof TIMEFRAME_WEIGHTS];
    const direction = momentum.direction === 'bullish' ? 1 : -1;
    const strength = momentum.strength === 'strong' ? 2 : 1;
    const change = Math.abs(momentum.change_percent) * 100; // Convert to percentage
    
    const score = direction * strength * change;
    weightedSum += score * weight;
    totalWeight += weight;
  });
  
  const compositeScore = totalWeight > 0 ? weightedSum / totalWeight : 0;
  
  // Clamp to -100 to +100 range
  return Math.max(-100, Math.min(100, compositeScore));
}

/**
 * Calculate confidence in momentum signal (0-1)
 */
function calculateConfidence(timeframes: Record<string, TimeframeMomentum>, signal: MomentumSignal): number {
  const agreement = Object.values(timeframes).filter(tf => {
    if (signal.includes('BULLISH')) return tf.direction === 'bullish';
    if (signal.includes('BEARISH')) return tf.direction === 'bearish';
    return true; // NEUTRAL
  }).length;
  
  const totalTimeframes = Object.keys(timeframes).length;
  const baseConfidence = agreement / totalTimeframes;
  
  // Boost confidence for strong signals
  const strongBonus = signal.includes('STRONG') ? 0.2 : 0;
  
  return Math.min(1, baseConfidence + strongBonus);
}

/**
 * Main momentum calculation function
 */
export function calculateMomentum(priceData: PriceData[]): MomentumData {
  if (priceData.length === 0) {
    throw new Error('No price data available for momentum calculation');
  }
  
  const currentPrice = priceData[0].close;
  const historicalPrices = extractTimeframePrices(priceData);
  
  // Calculate momentum for each timeframe
  const timeframes: Record<string, TimeframeMomentum> = {};
  
  Object.entries(historicalPrices).forEach(([timeframe, historicalPrice]) => {
    // Use volume from current data point, default to 1 if not available
    const volume = priceData[0].volume || 1;
    timeframes[timeframe] = calculateTimeframeMomentum(currentPrice, historicalPrice, volume);
  });
  
  // Generate overall signal and scores
  const signal = generateMomentumSignal(timeframes);
  const compositeScore = calculateCompositeScore(timeframes);
  const confidence = calculateConfidence(timeframes, signal);
  
  return {
    composite_score: compositeScore,
    rank: 0, // Will be set during ranking process
    signal,
    confidence,
    last_updated: new Date().toISOString(),
    timeframes: timeframes as any // Type assertion for the specific structure
  };
}

/**
 * Rank currency pairs by momentum strength
 */
export function rankPairsByMomentum(pairs: CurrencyPair[]): CurrencyPair[] {
  return pairs
    .map(pair => ({
      ...pair,
      momentum: {
        ...pair.momentum,
        // Recalculate momentum if chart data is available
        ...(pair.chart_data.length > 0 ? calculateMomentum(pair.chart_data) : {})
      }
    }))
    .sort((a, b) => b.momentum.composite_score - a.momentum.composite_score)
    .map((pair, index) => ({
      ...pair,
      momentum: {
        ...pair.momentum,
        rank: index + 1
      }
    }));
}

/**
 * Get momentum color class for UI display
 */
export function getMomentumColorClass(signal: MomentumSignal): string {
  switch (signal) {
    case 'STRONG_BULLISH':
      return 'momentum-strong-bullish';
    case 'WEAK_BULLISH':
      return 'momentum-weak-bullish';
    case 'NEUTRAL':
      return 'momentum-neutral';
    case 'WEAK_BEARISH':
      return 'momentum-weak-bearish';
    case 'STRONG_BEARISH':
      return 'momentum-strong-bearish';
    default:
      return 'momentum-neutral';
  }
}

/**
 * Get momentum display text
 */
export function getMomentumDisplayText(signal: MomentumSignal): string {
  return signal.replace('_', ' ').toLowerCase()
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Filter pairs by momentum strength
 */
export function filterPairsByMomentum(pairs: CurrencyPair[], minSignal?: MomentumSignal): CurrencyPair[] {
  if (!minSignal) return pairs;
  
  const signalStrength = {
    'STRONG_BULLISH': 5,
    'WEAK_BULLISH': 4,
    'NEUTRAL': 3,
    'WEAK_BEARISH': 2,
    'STRONG_BEARISH': 1
  };
  
  const minStrength = signalStrength[minSignal];
  
  return pairs.filter(pair => {
    const pairStrength = signalStrength[pair.momentum.signal];
    return pairStrength >= minStrength;
  });
}