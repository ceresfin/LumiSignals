# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Enhanced trade logging system (`enhanced_trade_logger.py`)
  - Comprehensive trade log class capturing all trade lifecycle events
  - JSON-based storage for pending, filled, and cancelled orders
  - Sync status tracking for Airtable integration
  
- Enhanced synchronization system (`enhanced_sync_all.py`)
  - Fixed momentum direction mapping to Airtable select options
  - Fixed strategy bias mapping (BUY/SELL/NEUTRAL)
  - Comprehensive log synchronization with retry logic
  - Current price updates for open trades
  
- Trade logger integration wrapper (`trade_logger_integration.py`)
  - Intercepts all order placements for comprehensive logging
  - Backward compatibility with existing strategies
  - Automatic risk metric calculations
  
- TypeScript/Node.js project structure
  - Added package.json with dependencies
  - TypeScript configuration (tsconfig.json)
  - ESLint and Jest configurations
  - Airtable type definitions

### Fixed
- Trade metadata classification issues
  - Momentum direction now correctly maps to Airtable options
  - Strategy bias properly maps to BUY/SELL/NEUTRAL
  - Zone positions correctly mapped for all strategies
  
- Missing trade logs
  - All trades now captured regardless of execution path
  - Complete metadata stored for every trade
  - Order lifecycle properly tracked

### Changed
- Updated .env.example to include Airtable credentials
- Enhanced metadata storage with dict-like methods for compatibility

## [1.0.0] - 2025-06-28

### Added
- Initial OANDA trading bot implementation
- Multiple trading strategies:
  - Penny Curve Momentum (PCM)
  - Dime Curve strategies
  - Quarter Curve Butter strategy
- Airtable integration for trade journaling
- Weekend testing mode for strategy development
- Risk management with fixed dollar risk per trade
- Market timing and liquidity analysis
- Comprehensive logging system

### Features
- Real-time forex trading via OANDA API
- Multiple timeframe analysis
- Psychological levels detection
- Session-based trading logic
- Automated order placement with stop loss and take profit
- Trade metadata storage and synchronization

[Unreleased]: https://github.com/ceresfin/LumiSignals/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ceresfin/LumiSignals/releases/tag/v1.0.0