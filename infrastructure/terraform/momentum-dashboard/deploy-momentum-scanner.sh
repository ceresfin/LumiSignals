#!/bin/bash
# Deploy Momentum Scanner feature to pipstop.org
# Usage: ./deploy-momentum-scanner.sh

echo "🚀 Deploying Momentum Scanner feature to pipstop.org..."
echo "Feature: 5-timeframe momentum analysis for all 28 currency pairs"
echo ""

# Configuration from LumiSignals Architecture Bible
S3_BUCKET="pipstop.org-website"
CLOUDFRONT_DISTRIBUTION="EKCW6AHXVBAW0"
AWS_REGION="us-east-1"

# Build the React application
echo "📦 Building React dashboard with Momentum Scanner..."
npm run build

if [ $? -ne 0 ]; then
    echo "❌ Build failed!"
    exit 1
fi

echo "✅ Build completed successfully"
echo ""

# Deploy assets to S3 with proper cache headers
echo "📤 Deploying to S3 bucket: $S3_BUCKET"

# Deploy static assets with long cache (excludes index.html)
echo "  ↗️  Syncing static assets with long cache headers..."
aws s3 sync dist/ s3://$S3_BUCKET/ --delete --cache-control "max-age=31536000" --exclude "index.html" --region $AWS_REGION

# Deploy index.html with no-cache headers for immediate updates
echo "  ↗️  Deploying index.html with no-cache headers..."
aws s3 cp dist/index.html s3://$S3_BUCKET/index.html --cache-control "no-cache, no-store, must-revalidate" --region $AWS_REGION

if [ $? -ne 0 ]; then
    echo "❌ S3 deployment failed!"
    exit 1
fi

echo "✅ S3 deployment completed"
echo ""

# Invalidate CloudFront cache
echo "🔄 Invalidating CloudFront cache..."
INVALIDATION_OUTPUT=$(aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_DISTRIBUTION --paths "/*" --query 'Invalidation.Id' --output text --region $AWS_REGION)

if [ $? -ne 0 ]; then
    echo "❌ CloudFront invalidation failed!"
    exit 1
fi

echo "✅ CloudFront invalidation created: $INVALIDATION_OUTPUT"
echo ""

echo "🎉 Deployment completed successfully!"
echo ""
echo "New features deployed:"
echo "  ✅ New 'Momentum Scanner' tab added to navigation"
echo "  ✅ 5-timeframe momentum analysis (48h, 24h, 4h, 60m, 15m)"
echo "  ✅ All 28 currency pairs with color-coded percentage changes"
echo "  ✅ Currency filter radio buttons (USD, EUR, GBP, JPY, CAD, AUD, CHF, NZD)"
echo "  ✅ 5-minute auto-refresh with manual refresh option"
echo "  ✅ CloudFront cache invalidated for immediate updates"
echo ""
echo "🌐 Live at: https://pipstop.org"
echo "📊 Navigate to: Momentum Scanner tab (2nd tab in navigation)"
echo "🔍 Debug: Check browser console for momentum data API calls"