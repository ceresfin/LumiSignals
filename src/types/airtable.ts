export interface AirtableConfig {
    apiKey: string;
    baseId: string;
    tableName: string;
}

export interface TradeRecord {
    id?: string;
    instrument: string;
    direction: 'BUY' | 'SELL';
    entryPrice: number;
    exitPrice?: number;
    stopLoss: number;
    takeProfit: number;
    units: number;
    openTime: string;
    closeTime?: string;
    profit?: number;
    status: 'OPEN' | 'CLOSED' | 'CANCELLED';
    strategy?: string;
    notes?: string;
}