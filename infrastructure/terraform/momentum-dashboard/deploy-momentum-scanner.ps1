# Deploy Momentum Scanner feature to pipstop.org
# Usage: .\deploy-momentum-scanner.ps1

Write-Host "🚀 Deploying Momentum Scanner feature to pipstop.org..." -ForegroundColor Green
Write-Host "Feature: 5-timeframe momentum analysis for all 28 currency pairs" -ForegroundColor Yellow
Write-Host ""

# Configuration from LumiSignals Architecture Bible
$S3_BUCKET = "pipstop.org-website"
$CLOUDFRONT_DISTRIBUTION = "EKCW6AHXVBAW0"
$AWS_REGION = "us-east-1"

# Build the React application
Write-Host "📦 Building React dashboard with Momentum Scanner..." -ForegroundColor Cyan
npm run build

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Build completed successfully" -ForegroundColor Green
Write-Host ""

# Deploy assets to S3 with proper cache headers
Write-Host "📤 Deploying to S3 bucket: $S3_BUCKET" -ForegroundColor Cyan

# Deploy static assets with long cache (excludes index.html)
Write-Host "  ↗️  Syncing static assets with long cache headers..." -ForegroundColor Yellow
aws s3 sync dist/ s3://$S3_BUCKET/ --delete --cache-control "max-age=31536000" --exclude "index.html" --region $AWS_REGION

# Deploy index.html with no-cache headers for immediate updates
Write-Host "  ↗️  Deploying index.html with no-cache headers..." -ForegroundColor Yellow
aws s3 cp dist/index.html s3://$S3_BUCKET/index.html --cache-control "no-cache, no-store, must-revalidate" --region $AWS_REGION

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ S3 deployment failed!" -ForegroundColor Red
    exit 1
}

Write-Host "✅ S3 deployment completed" -ForegroundColor Green
Write-Host ""

# Invalidate CloudFront cache
Write-Host "🔄 Invalidating CloudFront cache..." -ForegroundColor Cyan
$INVALIDATION_OUTPUT = aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_DISTRIBUTION --paths "/*" --query 'Invalidation.Id' --output text --region $AWS_REGION

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ CloudFront invalidation failed!" -ForegroundColor Red
    exit 1
}

Write-Host "✅ CloudFront invalidation created: $INVALIDATION_OUTPUT" -ForegroundColor Green
Write-Host ""

Write-Host "🎉 Deployment completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "New features deployed:" -ForegroundColor Yellow
Write-Host "  ✅ New 'Momentum Scanner' tab added to navigation"
Write-Host "  ✅ 5-timeframe momentum analysis (48h, 24h, 4h, 60m, 15m)"
Write-Host "  ✅ All 28 currency pairs with color-coded percentage changes"
Write-Host "  ✅ Currency filter radio buttons (USD, EUR, GBP, JPY, CAD, AUD, CHF, NZD)"
Write-Host "  ✅ 5-minute auto-refresh with manual refresh option"
Write-Host "  ✅ CloudFront cache invalidated for immediate updates"
Write-Host ""
Write-Host "🌐 Live at: https://pipstop.org" -ForegroundColor Cyan
Write-Host "📊 Navigate to: Momentum Scanner tab (2nd tab in navigation)" -ForegroundColor Yellow
Write-Host "🔍 Debug: Check browser console for momentum data API calls" -ForegroundColor Yellow