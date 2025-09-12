#!/bin/bash

echo "🚀 Deploying CORS Fix to pipstop.org..."
echo "=============================================="
echo ""
echo "🏥 SURGICAL FIX - CORS Error Resolution:"
echo "   ❌ Problem: Graphs tab getting CORS errors from Lambda endpoints" 
echo "   ✅ Solution: Redirect to working RDS API that connects to tiered storage"
echo "   📊 Result: 500 candlestick lazy loading now accessible via Graphs tab"
echo "   🔒 Scope: Only affects Graphs tab - other tabs unchanged (minimal risk)"
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
echo "📦 Building React application with CORS fix..."
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
echo "🎉 CORS Fix Deployment Complete!"
echo "=================================="
echo "🔧 Technical Changes Applied:"
echo "   📡 getCandlestickData() method now uses RDS API instead of Lambda"
echo "   🛡️ CORS errors eliminated by using working API Gateway endpoint"
echo "   🗄️ Charts now connect to tiered storage system via RDS endpoint"
echo "   💾 Environment variables updated to reflect the architectural change"
echo ""
echo "📊 Expected Results:"
echo "   ✅ Graphs tab should load without CORS errors"
echo "   📈 500 candlesticks should be available for lazy loading"
echo "   🔄 Current data should remain (tiered storage system working)" 
echo "   🎯 Only Graphs tab affected - other tabs unchanged"
echo ""
echo "🧪 Testing Instructions:"
echo "   1. Visit https://pipstop.org"
echo "   2. Click on 'Graphs' tab"
echo "   3. Check browser console - should be no CORS errors"
echo "   4. Verify candlestick charts load properly"
echo "   5. Check for 500 candle count (or whatever RDS API provides)"
echo ""
echo "🌐 Visit https://pipstop.org to test the CORS fix"
echo "⏰ Note: CloudFront cache clearing may take 2-3 minutes"
echo ""
echo "🔍 If issues persist:"
echo "   - Check browser console for any remaining errors"
echo "   - Verify RDS API is responding: https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/candlestick-data"
echo "   - Confirm tiered storage system is collecting data properly"