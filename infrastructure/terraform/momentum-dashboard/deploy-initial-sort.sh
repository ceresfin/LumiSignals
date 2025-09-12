#!/bin/bash

echo "🚀 Deploying Initial Chart Sorting to pipstop.org..."
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
echo "📊 New Features:"
echo "   ✨ Charts automatically sorted by institutional proximity on load"
echo "   🥇 Rank 1-3: Closest to Dimes (blue badges)"
echo "   🥈 Rank 4-10: Closest to Quarters (green badges)"  
echo "   🥉 Rank 11-20: Closest to Pennies (pink badges)"
echo "   📊 Rank 21-28: Furthest from levels (gray badges)"
echo "   🔄 Manual 'Re-sort Charts' button for fresh sorting"
echo "   💾 Order preserved until manual re-sort"
echo "   🔍 Zoom state still preserved after user interaction"
echo ""
echo "🌐 Visit https://pipstop.org to see the sorted charts"
echo "⏰ Note: CloudFront cache clearing may take 2-3 minutes"