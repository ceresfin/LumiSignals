# LumiSignals - OANDA Trading Bot

An automated forex trading bot with OANDA API integration and comprehensive Airtable journaling for trade analysis.

## Project Structure

```
.
├── src/
│   ├── api/          # OANDA API client and related code
│   ├── strategies/   # Trading strategies implementation
│   ├── indicators/   # Technical indicators
│   ├── utils/        # Utility functions and helpers
│   ├── types/        # TypeScript type definitions
│   ├── config/       # Configuration management
│   ├── services/     # Core services (trading bot, etc.)
│   └── models/       # Data models
├── tests/            # Test files
│   ├── unit/         # Unit tests
│   └── integration/  # Integration tests
├── data/             # Data storage
│   ├── historical/   # Historical market data
│   └── live/         # Live trading data
├── logs/             # Application logs
├── config/           # Configuration files
├── docs/             # Documentation
└── scripts/          # Utility scripts
```

## Getting Started

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your OANDA API credentials and preferences.

3. **Build the project:**
   ```bash
   npm run build
   ```

4. **Run tests:**
   ```bash
   npm test
   ```

5. **Start the bot:**
   ```bash
   npm start
   ```

## Development

- **Run in development mode:** `npm run dev`
- **Run tests in watch mode:** `npm run test:watch`
- **Lint code:** `npm run lint`
- **Type check:** `npm run typecheck`

## Configuration

Key configuration options in `.env`:

- `OANDA_API_KEY`: Your OANDA API key
- `OANDA_ACCOUNT_ID`: Your OANDA account ID
- `TRADING_ENABLED`: Enable/disable live trading
- `MAX_POSITION_SIZE`: Maximum position size per trade
- `RISK_PER_TRADE`: Risk percentage per trade

## Scripts

- `npm run backtest`: Run backtesting on historical data
- `npm run analyze`: Analyze trading performance

## Safety Features

- Trading can be disabled via `TRADING_ENABLED=false`
- Maximum position size limits
- Stop loss and take profit defaults
- Comprehensive logging
- Graceful shutdown handling

## License

MIT