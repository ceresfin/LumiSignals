#!/bin/bash

echo "🚀 Deploying Zoom Preservation Fix to pipstop.org..."
echo "================================================"

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

# Invalidate CloudFront cache
echo "🔄 Invalidating CloudFront cache..."
aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths "/*" --region us-east-1

if [ $? -ne 0 ]; then
    echo "❌ CloudFront invalidation failed!"
    exit 1
fi

echo "✅ CloudFront invalidation created!"

echo ""
echo "🎉 Deployment complete!"
echo "📊 Changes:"
echo "   - Charts now stay in fixed positions (no reordering)"
echo "   - Sort rankings shown as badges (1-28)"
echo "   - User zoom/pan state preserved after interaction"
echo "   - Price updates don't reset chart zoom"
echo ""
echo "🌐 Visit https://pipstop.org to see the changes"
echo "⏰ Note: CloudFront cache clearing may take 2-3 minutes"