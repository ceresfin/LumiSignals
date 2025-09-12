#!/bin/bash

# Deploy Data Orchestrator 500 candles update to pipstop.org
# This update makes the graphs tab use the Data Orchestrator API to fetch 500 candlesticks from tiered storage

echo "🎯 Deploying Data Orchestrator 500 candles update..."
echo "This will update ONLY the graphs tab to use Data Orchestrator API"

echo -e "\nBuilding dashboard..."
npm run build

if [ $? -ne 0 ]; then
    echo "❌ Build failed!"
    exit 1
fi

echo -e "\n📦 Deploying to S3..."
aws s3 sync dist/ s3://pipstop.org-website/ --delete --cache-control "max-age=31536000" --exclude "index.html" --region us-east-1
aws s3 cp dist/index.html s3://pipstop.org-website/index.html --cache-control "no-cache" --region us-east-1

echo -e "\n🔄 Invalidating CloudFront..."
aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths "/*" --region us-east-1

echo -e "\n✅ Deployment complete!"
echo "📊 Graphs tab now fetches 500 candlesticks from Data Orchestrator"
echo "🌐 Check https://pipstop.org - Graphs tab"
echo -e "\n📝 Changes:"
echo "  - Graphs tab uses Data Orchestrator API (Fargate)"
echo "  - Requests 500 candlesticks from tiered storage"
echo "  - Other tabs remain unchanged (still use Lambda)"