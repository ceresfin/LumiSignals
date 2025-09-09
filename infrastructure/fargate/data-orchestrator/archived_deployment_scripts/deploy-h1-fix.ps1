# PowerShell wrapper for H1 Backfill Fix deployment
# This script runs the bash deployment script from PowerShell on Windows
# Usage: .\deploy-h1-fix.ps1

Write-Host "🚀 LumiSignals H1 Backfill Fix - PowerShell Deployment" -ForegroundColor Green
Write-Host "🔧 Fix: Date-range approach for H1 backfill during market closure" -ForegroundColor Yellow
Write-Host ""

# Check if we're in the right directory
$currentPath = Get-Location
$expectedPath = "*infrastructure\fargate\data-orchestrator*"

if ($currentPath -notlike $expectedPath) {
    Write-Host "❌ Please run this script from the data-orchestrator directory:" -ForegroundColor Red
    Write-Host "   cd C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator" -ForegroundColor Yellow
    Write-Host "   .\deploy-h1-fix.ps1" -ForegroundColor Yellow
    exit 1
}

# Check if Docker is running
Write-Host "🐳 Checking Docker status..." -ForegroundColor Cyan
try {
    docker --version | Out-Null
    docker info | Out-Null
    Write-Host "✅ Docker is running" -ForegroundColor Green
} catch {
    Write-Host "❌ Docker is not running. Please start Docker Desktop first." -ForegroundColor Red
    exit 1
}

# Check if AWS CLI is available
Write-Host "☁️ Checking AWS CLI..." -ForegroundColor Cyan
try {
    aws --version | Out-Null
    Write-Host "✅ AWS CLI is available" -ForegroundColor Green
} catch {
    Write-Host "❌ AWS CLI is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Check if jq is available (needed for JSON processing)
Write-Host "🔧 Checking jq..." -ForegroundColor Cyan
try {
    jq --version | Out-Null
    Write-Host "✅ jq is available" -ForegroundColor Green
} catch {
    Write-Host "⚠️ jq is not available. Installing via winget..." -ForegroundColor Yellow
    try {
        winget install jqlang.jq
        Write-Host "✅ jq installed successfully" -ForegroundColor Green
    } catch {
        Write-Host "❌ Failed to install jq. Please install manually:" -ForegroundColor Red
        Write-Host "   winget install jqlang.jq" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""
Write-Host "🔄 Running bash deployment script..." -ForegroundColor Cyan
Write-Host ""

# Run the bash script
try {
    & bash ./deploy-h1-backfill-fix.sh
    Write-Host ""
    Write-Host "🎉 Deployment completed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📊 Next Steps:" -ForegroundColor Cyan
    Write-Host "1. Monitor CloudWatch logs for H1 backfill activity" -ForegroundColor White
    Write-Host "2. Check TradingView charts - should show ~100 H1 candles" -ForegroundColor White  
    Write-Host "3. Verify fix works during market closure (weekends)" -ForegroundColor White
    Write-Host ""
    Write-Host "🔍 Monitor logs with:" -ForegroundColor Yellow
    Write-Host "   aws logs tail /ecs/lumisignals-data-orchestrator --region us-east-1 --follow" -ForegroundColor Gray
    
} catch {
    Write-Host ""
    Write-Host "❌ Deployment failed. Error:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "💡 Troubleshooting:" -ForegroundColor Yellow
    Write-Host "1. Check Docker Desktop is running" -ForegroundColor White
    Write-Host "2. Verify AWS credentials are configured" -ForegroundColor White
    Write-Host "3. Ensure you have permissions for ECR and ECS" -ForegroundColor White
    exit 1
}