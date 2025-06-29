export interface OandaConfig {
    apiKey: string;
    accountId: string;
    apiUrl: string;
    environment: string;
}

export interface AccountSummary {
    id: string;
    currency: string;
    balance: string;
    unrealizedPL: string;
    realizedPL: string;
    marginUsed: string;
    marginAvailable: string;
    openPositionCount: number;
    openTradeCount: number;
    pendingOrderCount: number;
}

export interface Instrument {
    name: string;
    type: string;
    displayName: string;
    pipLocation: number;
    displayPrecision: number;
    tradeUnitsPrecision: number;
    minimumTradeSize: string;
    maximumTrailingStopDistance: string;
    minimumTrailingStopDistance: string;
    maximumPositionSize: string;
    maximumOrderUnits: string;
    marginRate: string;
}

export interface Candle {
    time: string;
    volume: number;
    complete: boolean;
    mid: {
        o: string;
        h: string;
        l: string;
        c: string;
    };
}

export interface Order {
    instrument: string;
    units: string;
    type: 'MARKET' | 'LIMIT' | 'STOP' | 'MARKET_IF_TOUCHED';
    timeInForce?: 'FOK' | 'IOC' | 'GTC' | 'GFD' | 'GTD';
    priceBound?: string;
    positionFill?: 'OPEN_ONLY' | 'REDUCE_FIRST' | 'REDUCE_ONLY' | 'DEFAULT';
    clientExtensions?: {
        id?: string;
        tag?: string;
        comment?: string;
    };
    takeProfitOnFill?: {
        price: string;
        timeInForce?: 'GTC' | 'GFD' | 'GTD';
    };
    stopLossOnFill?: {
        price: string;
        timeInForce?: 'GTC' | 'GFD' | 'GTD';
    };
}