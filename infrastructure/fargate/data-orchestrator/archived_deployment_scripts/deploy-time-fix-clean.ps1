# PowerShell script to deploy time handling fixes for OANDA nanosecond precision
# Usage: .\deploy-time-fix-clean.ps1

Write-Host "Time Handling Fix Deployment Starting..." -ForegroundColor Green
Write-Host "Fix: Proper handling of OANDA nanosecond timestamps" -ForegroundColor Yellow
Write-Host ""

# Configuration
$AWS_REGION = "us-east-1"
$AWS_ACCOUNT_ID = "816945674467"
$ECR_REPOSITORY = "lumisignals-data-orchestrator"
$ECR_URI = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
$ECS_CLUSTER = "lumisignals-cluster"
$ECS_SERVICE = "lumisignals-data-orchestrator"
$TASK_FAMILY = "lumisignals-data-orchestrator"

# Generate unique hash for this deployment
$COMMIT_SHA = git rev-parse --short HEAD
$BUILD_DATE = Get-Date -Format "yyyyMMdd-HHmmss"
$UNIQUE_HASH = "${COMMIT_SHA}-${BUILD_DATE}"
$VERSION = "time-handling-fix-${UNIQUE_HASH}"

Write-Host "Deployment Details:" -ForegroundColor Cyan
Write-Host "   Repository: ${ECR_URI}" -ForegroundColor White
Write-Host "   Version: ${VERSION}" -ForegroundColor White  
Write-Host "   Hash: ${UNIQUE_HASH}" -ForegroundColor White
Write-Host "   Build Date: ${BUILD_DATE}" -ForegroundColor White
Write-Host ""
Write-Host "Time Handling Fixes:" -ForegroundColor Yellow
Write-Host "   Parse OANDA nanosecond timestamps" -ForegroundColor White
Write-Host "   Proper datetime sorting in H1 backfill" -ForegroundColor White  
Write-Host "   Consistent time format for TradingView" -ForegroundColor White
Write-Host "   Apply to both M5 regular data and H1 backfill" -ForegroundColor White
Write-Host ""

# Step 1: Login to ECR
Write-Host "Logging in to Amazon ECR..." -ForegroundColor Cyan
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI

# Step 2: Build Docker image
Write-Host "Building Docker image with time handling fixes..." -ForegroundColor Cyan
docker build `
    --build-arg VERSION="$VERSION" `
    --build-arg BUILD_DATE="$BUILD_DATE" `
    --build-arg COMMIT_SHA="$COMMIT_SHA" `
    --build-arg CACHEBUST="$(Get-Date -UFormat %s)" `
    --platform linux/amd64 `
    -t ${ECR_REPOSITORY}:$UNIQUE_HASH `
    -t ${ECR_REPOSITORY}:latest `
    .

# Step 3: Tag for ECR
Write-Host "Tagging images for ECR..." -ForegroundColor Cyan
docker tag ${ECR_REPOSITORY}:$UNIQUE_HASH ${ECR_URI}:$UNIQUE_HASH
docker tag ${ECR_REPOSITORY}:latest ${ECR_URI}:latest

# Step 4: Push to ECR
Write-Host "Pushing images to ECR..." -ForegroundColor Cyan
docker push ${ECR_URI}:$UNIQUE_HASH
docker push ${ECR_URI}:latest

# Step 5: Get current task definition and update
Write-Host "Updating task definition..." -ForegroundColor Cyan
$currentTaskDef = aws ecs describe-task-definition --task-definition $TASK_FAMILY --region $AWS_REGION --query 'taskDefinition' --output json | ConvertFrom-Json

# Update image
$currentTaskDef.containerDefinitions[0].image = "${ECR_URI}:${UNIQUE_HASH}"

# Remove read-only fields
$currentTaskDef.PSObject.Properties.Remove('taskDefinitionArn')
$currentTaskDef.PSObject.Properties.Remove('revision')
$currentTaskDef.PSObject.Properties.Remove('status')
$currentTaskDef.PSObject.Properties.Remove('requiresAttributes')
$currentTaskDef.PSObject.Properties.Remove('placementConstraints')
$currentTaskDef.PSObject.Properties.Remove('compatibilities')
$currentTaskDef.PSObject.Properties.Remove('registeredAt')
$currentTaskDef.PSObject.Properties.Remove('registeredBy')

# Convert to JSON
$newTaskDefJson = $currentTaskDef | ConvertTo-Json -Depth 10 -Compress

# Step 6: Register new task definition
Write-Host "Registering new task definition..." -ForegroundColor Cyan
$newTaskRevision = aws ecs register-task-definition --region $AWS_REGION --cli-input-json $newTaskDefJson --query 'taskDefinition.revision' --output text

Write-Host "New task definition: ${TASK_FAMILY}:${newTaskRevision}" -ForegroundColor Green

# Step 7: Update ECS service
Write-Host "Updating ECS service..." -ForegroundColor Cyan
aws ecs update-service --cluster $ECS_CLUSTER --service $ECS_SERVICE --task-definition "${TASK_FAMILY}:${newTaskRevision}" --region $AWS_REGION --query 'service.{ServiceName:serviceName,TaskDefinition:taskDefinition,Status:status}' --output table

# Step 8: Wait for deployment
Write-Host "Waiting for deployment to complete..." -ForegroundColor Cyan
aws ecs wait services-stable --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION

# Step 9: Verify
Write-Host "Verifying deployment..." -ForegroundColor Cyan
aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION --query 'services[0].{Status:status,RunningCount:runningCount,DesiredCount:desiredCount,TaskDefinition:taskDefinition}' --output table

Write-Host ""
Write-Host "Time Handling Fix deployment completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Technical Changes Applied:" -ForegroundColor Yellow
Write-Host "   Added parse_oanda_timestamp method" -ForegroundColor White
Write-Host "   Handle nanosecond precision timestamps" -ForegroundColor White
Write-Host "   Proper datetime sorting in H1 backfill" -ForegroundColor White
Write-Host "   Consistent time formatting across M5 and H1 data" -ForegroundColor White
Write-Host "   OANDA API requests use proper nanosecond format" -ForegroundColor White
Write-Host ""
Write-Host "Expected Results:" -ForegroundColor Yellow
Write-Host "   No more time parsing errors in logs" -ForegroundColor White
Write-Host "   Accurate chronological sorting of H1 candles" -ForegroundColor White
Write-Host "   Consistent time format in TradingView charts" -ForegroundColor White
Write-Host "   Improved reliability during data collection" -ForegroundColor White
Write-Host ""
Write-Host "Monitor logs with:" -ForegroundColor Cyan
Write-Host 'aws logs tail /ecs/lumisignals-data-orchestrator --region us-east-1 --follow' -ForegroundColor Gray