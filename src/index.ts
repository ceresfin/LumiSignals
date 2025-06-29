import dotenv from 'dotenv';
import { logger } from './utils/logger';
import { OandaClient } from './api/oandaClient';
import { TradingBot } from './services/tradingBot';
import { config } from './config/config';

dotenv.config();

async function main() {
    try {
        logger.info('Starting OANDA Trading Bot...');
        
        const oandaClient = new OandaClient(config.oanda);
        const tradingBot = new TradingBot(oandaClient, config.trading);
        
        await oandaClient.testConnection();
        logger.info('Successfully connected to OANDA API');
        
        if (config.trading.enabled) {
            await tradingBot.start();
        } else {
            logger.warn('Trading is disabled. Running in monitoring mode only.');
            await tradingBot.monitor();
        }
    } catch (error) {
        logger.error('Fatal error:', error);
        process.exit(1);
    }
}

process.on('SIGINT', () => {
    logger.info('Shutting down gracefully...');
    process.exit(0);
});

main();