# Simple PowerShell deployment script for H1 Backfill Fix
# Handles the jq issue and completes the deployment

Write-Host "Completing H1 Backfill Fix deployment..." -ForegroundColor Green

# Configuration
$AWS_REGION = "us-east-1"
$AWS_ACCOUNT_ID = "816945674467"
$ECR_REPOSITORY = "lumisignals-data-orchestrator"
$ECR_URI = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
$ECS_CLUSTER = "lumisignals-cluster"
$ECS_SERVICE = "lumisignals-data-orchestrator"
$TASK_FAMILY = "lumisignals-data-orchestrator"
$IMAGE_TAG = "5c1ad74-20250808-232932"  # From the successful build above

Write-Host "Using image: ${ECR_URI}:${IMAGE_TAG}" -ForegroundColor Cyan

# Step 1: Get current task definition
Write-Host "Getting current task definition..." -ForegroundColor Cyan
$currentTaskDef = aws ecs describe-task-definition --task-definition $TASK_FAMILY --region $AWS_REGION --query 'taskDefinition' --output json | ConvertFrom-Json

# Step 2: Update image in task definition
Write-Host "Updating task definition with new image..." -ForegroundColor Cyan
$currentTaskDef.containerDefinitions[0].image = "${ECR_URI}:${IMAGE_TAG}"

# Remove read-only fields
$currentTaskDef.PSObject.Properties.Remove('taskDefinitionArn')
$currentTaskDef.PSObject.Properties.Remove('revision')
$currentTaskDef.PSObject.Properties.Remove('status')
$currentTaskDef.PSObject.Properties.Remove('requiresAttributes')
$currentTaskDef.PSObject.Properties.Remove('placementConstraints')
$currentTaskDef.PSObject.Properties.Remove('compatibilities')
$currentTaskDef.PSObject.Properties.Remove('registeredAt')
$currentTaskDef.PSObject.Properties.Remove('registeredBy')

# Convert back to JSON
$newTaskDefJson = $currentTaskDef | ConvertTo-Json -Depth 10 -Compress

# Step 3: Register new task definition
Write-Host "Registering new task definition..." -ForegroundColor Cyan
$newTaskRevision = aws ecs register-task-definition --region $AWS_REGION --cli-input-json $newTaskDefJson --query 'taskDefinition.revision' --output text

Write-Host "New task definition: ${TASK_FAMILY}:${newTaskRevision}" -ForegroundColor Green

# Step 4: Update ECS service
Write-Host "Updating ECS service..." -ForegroundColor Cyan
aws ecs update-service --cluster $ECS_CLUSTER --service $ECS_SERVICE --task-definition "${TASK_FAMILY}:${newTaskRevision}" --region $AWS_REGION --query 'service.{ServiceName:serviceName,TaskDefinition:taskDefinition,Status:status}' --output table

# Step 5: Wait for deployment
Write-Host "Waiting for deployment to complete..." -ForegroundColor Cyan
aws ecs wait services-stable --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION

# Step 6: Verify
Write-Host "Verifying deployment..." -ForegroundColor Cyan
aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION --query 'services[0].{Status:status,RunningCount:runningCount,DesiredCount:desiredCount,TaskDefinition:taskDefinition}' --output table

Write-Host ""
Write-Host "H1 Backfill Fix deployment completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Technical Changes Applied:" -ForegroundColor Yellow
Write-Host "- OANDA client enhanced with date-range support" -ForegroundColor White
Write-Host "- H1 backfill changed from count=100 to 30-day date-range approach" -ForegroundColor White
Write-Host "- Requests 30 days of data, keeps 500 most recent candles" -ForegroundColor White
Write-Host "- Works during market closure (weekends/holidays)" -ForegroundColor White
Write-Host ""
Write-Host "Monitor H1 backfill activity:" -ForegroundColor Yellow
Write-Host "aws logs tail /ecs/lumisignals-data-orchestrator --region us-east-1 --follow" -ForegroundColor Gray
Write-Host ""
Write-Host "Expected Result: TradingView should show ~500 H1 candles immediately" -ForegroundColor Green