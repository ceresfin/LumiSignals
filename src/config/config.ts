import { z } from 'zod';

const envSchema = z.object({
    OANDA_API_KEY: z.string(),
    OANDA_ACCOUNT_ID: z.string(),
    OANDA_API_URL: z.string().url(),
    OANDA_ENVIRONMENT: z.string().optional().default('practice'),
    TRADING_ENABLED: z.string().transform(val => val === 'true'),
    MAX_POSITION_SIZE: z.string().transform(Number),
    RISK_PER_TRADE: z.string().transform(Number),
    DEFAULT_STOP_LOSS_PIPS: z.string().transform(Number),
    DEFAULT_TAKE_PROFIT_PIPS: z.string().transform(Number),
    AIRTABLE_API_TOKEN: z.string(),
    BASE_ID: z.string(),
    TABLE_NAME: z.string(),
    LOG_LEVEL: z.string().optional().default('info'),
    LOG_FILE_PATH: z.string().optional().default('./logs/trading.log'),
    TIMEZONE: z.string().optional().default('UTC'),
});

const env = envSchema.parse(process.env);

export const config = {
    oanda: {
        apiKey: env.OANDA_API_KEY,
        accountId: env.OANDA_ACCOUNT_ID,
        apiUrl: env.OANDA_API_URL,
        environment: env.OANDA_ENVIRONMENT,
    },
    airtable: {
        apiKey: env.AIRTABLE_API_TOKEN,
        baseId: env.BASE_ID,
        tableName: env.TABLE_NAME,
    },
    trading: {
        enabled: env.TRADING_ENABLED,
        maxPositionSize: env.MAX_POSITION_SIZE,
        riskPerTrade: env.RISK_PER_TRADE,
        defaultStopLossPips: env.DEFAULT_STOP_LOSS_PIPS,
        defaultTakeProfitPips: env.DEFAULT_TAKE_PROFIT_PIPS,
    },
    app: {
        logLevel: env.LOG_LEVEL,
        logFilePath: env.LOG_FILE_PATH,
        timezone: env.TIMEZONE,
    },
} as const;