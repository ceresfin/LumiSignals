import winston from 'winston';
import path from 'path';
import fs from 'fs';

const logDir = path.dirname(process.env.LOG_FILE_PATH || './logs/trading.log');
if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir, { recursive: true });
}

export const logger = winston.createLogger({
    level: process.env.LOG_LEVEL || 'info',
    format: winston.format.combine(
        winston.format.timestamp({
            format: 'YYYY-MM-DD HH:mm:ss',
        }),
        winston.format.errors({ stack: true }),
        winston.format.splat(),
        winston.format.json(),
    ),
    defaultMeta: { service: 'oanda-trading-bot' },
    transports: [
        new winston.transports.File({
            filename: process.env.LOG_FILE_PATH || './logs/trading.log',
            maxsize: 10485760, // 10MB
            maxFiles: 5,
        }),
        new winston.transports.Console({
            format: winston.format.combine(
                winston.format.colorize(),
                winston.format.simple(),
            ),
        }),
    ],
});