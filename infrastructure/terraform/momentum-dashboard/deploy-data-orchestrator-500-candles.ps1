# Deploy Data Orchestrator 500 candles update to pipstop.org
# This update makes the graphs tab use the Data Orchestrator API to fetch 500 candlesticks from tiered storage

Write-Host "🎯 Deploying Data Orchestrator 500 candles update..." -ForegroundColor Green
Write-Host "This will update ONLY the graphs tab to use Data Orchestrator API" -ForegroundColor Yellow

Write-Host "`nBuilding dashboard..." -ForegroundColor Cyan
npm run build

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`n📦 Deploying to S3..." -ForegroundColor Cyan
aws s3 sync dist/ s3://pipstop.org-website/ --delete --cache-control "max-age=31536000" --exclude "index.html" --region us-east-1
aws s3 cp dist/index.html s3://pipstop.org-website/index.html --cache-control "no-cache" --region us-east-1

Write-Host "`n🔄 Invalidating CloudFront..." -ForegroundColor Cyan
aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths "/*" --region us-east-1

Write-Host "`n✅ Deployment complete!" -ForegroundColor Green
Write-Host "📊 Graphs tab now fetches 500 candlesticks from Data Orchestrator" -ForegroundColor Yellow
Write-Host "🌐 Check https://pipstop.org - Graphs tab" -ForegroundColor Cyan
Write-Host "`n📝 Changes:" -ForegroundColor Yellow
Write-Host "  - Graphs tab uses Data Orchestrator API (Fargate)" -ForegroundColor White
Write-Host "  - Requests 500 candlesticks from tiered storage" -ForegroundColor White
Write-Host "  - Other tabs remain unchanged (still use Lambda)" -ForegroundColor White