#!/bin/bash

# Quick restore script to revert to working version if changes cause issues

echo "🔄 Restoring working version of chart components..."

# Restore the chart components
cp src/components/charts/LightweightTradingViewChartWithTrades.tsx.backup_2025_01_15_working src/components/charts/LightweightTradingViewChartWithTrades.tsx
cp src/components/charts/CurrencyPairGraphsWithTrades.tsx.backup_2025_01_15_working src/components/charts/CurrencyPairGraphsWithTrades.tsx

echo "✅ Files restored to working version"
echo ""
echo "Next steps:"
echo "1. npm run build"
echo "2. Deploy to S3 and invalidate CloudFront cache"