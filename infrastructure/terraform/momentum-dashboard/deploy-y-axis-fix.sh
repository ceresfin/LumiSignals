#!/bin/bash
# Deploy Y-axis decimal precision fix to pipstop.org
# Usage: ./deploy-y-axis-fix.sh

echo "🚀 Deploying Y-axis decimal precision fix to pipstop.org..."
echo "Changes: Non-JPY pairs will show 4 decimal places on Y-axis"
echo ""

# Configuration from LumiSignals Architecture Bible
S3_BUCKET="pipstop.org-website"
CLOUDFRONT_DISTRIBUTION="EKCW6AHXVBAW0"
AWS_REGION="us-east-1"

# Build the React application
echo "📦 Building React dashboard..."
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
aws s3 sync dist/ s3://$S3_BUCKET/ \
    --delete \
    --cache-control "max-age=31536000" \
    --exclude "index.html" \
    --region $AWS_REGION

# Deploy index.html with no-cache headers for immediate updates
echo "  ↗️  Deploying index.html with no-cache headers..."
aws s3 cp dist/index.html s3://$S3_BUCKET/index.html \
    --cache-control "no-cache, no-store, must-revalidate" \
    --region $AWS_REGION

if [ $? -ne 0 ]; then
    echo "❌ S3 deployment failed!"
    exit 1
fi

echo "✅ S3 deployment completed"
echo ""

# Invalidate CloudFront cache
echo "🔄 Invalidating CloudFront cache..."
INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id $CLOUDFRONT_DISTRIBUTION \
    --paths "/*" \
    --query 'Invalidation.Id' \
    --output text \
    --region $AWS_REGION)

if [ $? -ne 0 ]; then
    echo "❌ CloudFront invalidation failed!"
    exit 1
fi

echo "✅ CloudFront invalidation created: $INVALIDATION_ID"
echo ""

echo "🎉 Deployment completed successfully!"
echo ""
echo "Changes deployed:"
echo "  ✅ Y-axis precision: JPY pairs (2 decimals), Non-JPY pairs (4 decimals)"
echo "  ✅ Added debug logging for Y-axis precision"
echo "  ✅ CloudFront cache invalidated for immediate updates"
echo ""
echo "🌐 Live at: https://pipstop.org"
echo "🔍 Debug: Check browser console for Y-axis precision logs"
echo ""
echo "Monitor CloudFront invalidation:"
echo "aws cloudfront get-invalidation --distribution-id $CLOUDFRONT_DISTRIBUTION --id $INVALIDATION_ID"