export interface TradingConfig {
    enabled: boolean;
    maxPositionSize: number;
    riskPerTrade: number;
    defaultStopLossPips: number;
    defaultTakeProfitPips: number;
}

export interface Signal {
    instrument: string;
    direction: 'BUY' | 'SELL';
    strength: number;
    timestamp: Date;
    strategy: string;
    metadata?: Record<string, any>;
}

export interface Position {
    id: string;
    instrument: string;
    units: number;
    side: 'BUY' | 'SELL';
    openPrice: number;
    currentPrice: number;
    unrealizedPL: number;
    marginUsed: number;
    openTime: Date;
}

export interface TradeResult {
    id: string;
    instrument: string;
    units: number;
    profit: number;
    openTime: Date;
    closeTime: Date;
    openPrice: number;
    closePrice: number;
}