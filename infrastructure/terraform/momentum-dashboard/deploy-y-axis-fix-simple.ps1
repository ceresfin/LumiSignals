# Deploy Y-axis decimal precision fix to pipstop.org
# Usage: .\deploy-y-axis-fix-simple.ps1

Write-Host "🚀 Deploying Y-axis decimal precision fix to pipstop.org..." -ForegroundColor Green
Write-Host "Changes: Non-JPY pairs will show 4 decimal places on Y-axis" -ForegroundColor Yellow
Write-Host ""

# Configuration from LumiSignals Architecture Bible
$S3_BUCKET = "pipstop.org-website"
$CLOUDFRONT_DISTRIBUTION = "EKCW6AHXVBAW0"
$AWS_REGION = "us-east-1"

# Build the React application
Write-Host "📦 Building React dashboard..." -ForegroundColor Cyan
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
Write-Host "Changes deployed:" -ForegroundColor Yellow
Write-Host "  ✅ Y-axis precision: JPY pairs (2 decimals), Non-JPY pairs (4 decimals)"
Write-Host "  ✅ Added debug logging for Y-axis precision"
Write-Host "  ✅ CloudFront cache invalidated for immediate updates"
Write-Host ""
Write-Host "🌐 Live at: https://pipstop.org" -ForegroundColor Cyan
Write-Host "🔍 Debug: Check browser console for Y-axis precision logs" -ForegroundColor Yellow