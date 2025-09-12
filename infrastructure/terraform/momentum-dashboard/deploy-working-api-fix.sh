#!/bin/bash

echo "🚀 Deploying Working API Fix to pipstop.org..."
echo "=============================================="
echo ""
echo "🔧 SURGICAL FIX v2 - Working Data Source:"
echo "   ❌ Issue: RDS API had 0 candles (only checked Redis shard 0)" 
echo "   ✅ Solution: Switch to Direct Candlestick API with full shard access"
echo "   📊 Expected: Charts should now load with actual candlestick data"
echo "   🎯 API: https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 Working directory: $SCRIPT_DIR"

# Change to the momentum-dashboard directory
cd "$SCRIPT_DIR"

# Verify we're in the right directory
if [ ! -f "package.json" ]; then
    echo "❌ Error: package.json not found in $SCRIPT_DIR"
    exit 1
fi

# Build the React application
echo "📦 Building React application with working API fix..."
npm run build

if [ $? -ne 0 ]; then
    echo "❌ Build failed!"
    exit 1
fi

echo "✅ Build successful!"

# Deploy to S3
echo "☁️ Syncing to S3 bucket..."
aws s3 sync ./dist s3://pipstop.org-website --region us-east-1 --delete

if [ $? -ne 0 ]; then
    echo "❌ S3 sync failed!"
    exit 1
fi

echo "✅ S3 sync successful!"

# Invalidate CloudFront cache
echo "🔄 Invalidating CloudFront cache..."
aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths "/*" --region us-east-1

if [ $? -ne 0 ]; then
    echo "❌ CloudFront invalidation failed!"
    exit 1
fi

echo "✅ CloudFront invalidation created!"

echo ""
echo "🎉 Working API Fix Deployment Complete!"
echo "========================================"
echo "🔧 Technical Changes Applied:"
echo "   📡 getCandlestickData() now uses Direct Candlestick API with full Redis access"
echo "   🗄️ Connects to all 4 Redis shards (proper currency pair distribution)"
echo "   📈 API has M5→H1 aggregation fallback for comprehensive data coverage"
echo "   🔒 Maintains RDS API fallback for redundancy"
echo ""
echo "📊 Expected Results:"
echo "   ✅ Graphs tab should load with actual candlestick data"
echo "   📈 H1 timeframe charts with up to 500 candles (depending on data availability)"
echo "   🌍 All 28 currency pairs should work (proper shard distribution)" 
echo "   🔄 Current data from active Fargate data collection"
echo ""
echo "🧪 Testing Instructions:"
echo "   1. Visit https://pipstop.org"
echo "   2. Click on 'Graphs' tab"
echo "   3. Check browser console for 'Direct Candlestick API success' messages"
echo "   4. Verify candlestick charts display with data"
echo "   5. Test different currency pairs (especially non-USD majors)"
echo ""
echo "🌐 Visit https://pipstop.org to test the working API fix"
echo "⏰ Note: CloudFront cache clearing may take 2-3 minutes"
echo ""
echo "🔍 Debug Info:"
echo "   📡 API Endpoint: https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod"
echo "   🗂️ Redis Shards: 4-shard cluster with proper currency pair distribution"
echo "   📊 Data Sources: Direct H1 + M5→H1 aggregation fallback"
echo "   🔑 API Key: direct-candlestick-api-2025"