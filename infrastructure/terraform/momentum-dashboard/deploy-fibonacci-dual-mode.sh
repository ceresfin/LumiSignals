#!/bin/bash

echo "🚀 Deploying Dual-Mode Fibonacci (Fixed + ATR) to pipstop.org..."
echo "=============================================================="
echo "📊 New Features:"
echo "   - Fibonacci (Fixed): Timeframe-specific thresholds"
echo "   - Fibonacci (ATR): Dynamic volatility-based thresholds"
echo "   - Visual distinction: Fixed=Blue/Dashed, ATR=Orange/Solid"
echo ""

# Build the React application
echo "📦 Building React application..."
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

# Invalidate CloudFront distribution (if exists)
echo "🔄 Checking for CloudFront distribution..."
DISTRIBUTION_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?Aliases.Items[?contains(@, 'pipstop.org')]].Id" --output text)

if [ ! -z "$DISTRIBUTION_ID" ]; then
    echo "🌐 Invalidating CloudFront cache for distribution: $DISTRIBUTION_ID"
    aws cloudfront create-invalidation --distribution-id $DISTRIBUTION_ID --paths "/*"
    echo "✅ CloudFront invalidation initiated!"
else
    echo "ℹ️ No CloudFront distribution found for pipstop.org"
fi

echo ""
echo "🎉 Deployment complete!"
echo "🌐 Visit https://pipstop.org to test the new dual-mode Fibonacci toggles"
echo ""
echo "📋 Testing Instructions:"
echo "1. Look for 'Fibonacci (Fixed)' and 'Fibonacci (ATR)' in the Structure signals group"
echo "2. Fixed mode: Blue/purple dashed lines (timeframe-specific thresholds)"
echo "3. ATR mode: Orange/red solid lines (volatility-adaptive thresholds)"
echo "4. Both modes can be enabled simultaneously for comparison"
echo ""