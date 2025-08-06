# LumiSignals - Institutional Trading Platform

Institutional-grade quantitative trading platform with Fargate-based execution engine.

## Architecture

- **Redis Cluster**: 4-node cluster for trade queue management
- **Fargate Trade Executor**: Containerized trade execution engine
- **OANDA Integration**: Professional API integration for FX trading

## Status

✅ Working Fargate deployment with institutional architecture

## Quick Start

```bash
# Deploy infrastructure
cd infrastructure/terraform/redis-cluster
terraform init && terraform apply

cd ../fargate-trade-executor
terraform init && terraform apply
```
