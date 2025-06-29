import axios, { AxiosInstance } from 'axios';
import { logger } from '../utils/logger';
import { OandaConfig, AccountSummary, Instrument, Candle } from '../types/oanda';

export class OandaClient {
    private client: AxiosInstance;
    private accountId: string;

    constructor(config: OandaConfig) {
        this.accountId = config.accountId;
        this.client = axios.create({
            baseURL: config.apiUrl,
            headers: {
                'Authorization': `Bearer ${config.apiKey}`,
                'Content-Type': 'application/json',
            },
        });
    }

    async testConnection(): Promise<void> {
        try {
            await this.getAccountSummary();
        } catch (error) {
            logger.error('Failed to connect to OANDA API:', error);
            throw new Error('OANDA API connection failed');
        }
    }

    async getAccountSummary(): Promise<AccountSummary> {
        const response = await this.client.get(`/v3/accounts/${this.accountId}/summary`);
        return response.data.account;
    }

    async getInstruments(): Promise<Instrument[]> {
        const response = await this.client.get(`/v3/accounts/${this.accountId}/instruments`);
        return response.data.instruments;
    }

    async getCandles(
        instrument: string,
        granularity: string,
        count: number = 100
    ): Promise<Candle[]> {
        const response = await this.client.get('/v3/instruments/' + instrument + '/candles', {
            params: {
                granularity,
                count,
            },
        });
        return response.data.candles;
    }

    async createOrder(orderRequest: any): Promise<any> {
        const response = await this.client.post(
            `/v3/accounts/${this.accountId}/orders`,
            { order: orderRequest }
        );
        return response.data;
    }

    async getOpenPositions(): Promise<any[]> {
        const response = await this.client.get(`/v3/accounts/${this.accountId}/positions`);
        return response.data.positions;
    }
}