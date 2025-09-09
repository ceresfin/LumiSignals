# Quick hotfix deployment for H1 backfill variable scope issue
# Usage: .\deploy-hotfix.ps1

Write-Host "HOTFIX: H1 Backfill Variable Scope Fix" -ForegroundColor Red
Write-Host "Fixing: max_candles not defined error" -ForegroundColor Yellow
Write-Host ""

# Configuration
$AWS_REGION = "us-east-1"
$AWS_ACCOUNT_ID = "816945674467"
$ECR_REPOSITORY = "lumisignals-data-orchestrator"
$ECR_URI = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
$ECS_CLUSTER = "lumisignals-cluster"
$ECS_SERVICE = "lumisignals-data-orchestrator"
$TASK_FAMILY = "lumisignals-data-orchestrator"

# Generate unique hash
$COMMIT_SHA = git rev-parse --short HEAD
$BUILD_DATE = Get-Date -Format "yyyyMMdd-HHmmss"
$UNIQUE_HASH = "${COMMIT_SHA}-${BUILD_DATE}"
$VERSION = "hotfix-h1-scope-${UNIQUE_HASH}"

Write-Host "Building and deploying hotfix..." -ForegroundColor Cyan

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI

# Build
docker build `
    --build-arg VERSION="$VERSION" `
    --build-arg BUILD_DATE="$BUILD_DATE" `
    --build-arg COMMIT_SHA="$COMMIT_SHA" `
    --build-arg CACHEBUST="$(Get-Date -UFormat %s)" `
    --platform linux/amd64 `
    -t ${ECR_REPOSITORY}:$UNIQUE_HASH `
    -t ${ECR_REPOSITORY}:latest `
    .

# Tag
docker tag ${ECR_REPOSITORY}:$UNIQUE_HASH ${ECR_URI}:$UNIQUE_HASH
docker tag ${ECR_REPOSITORY}:latest ${ECR_URI}:latest

# Push
Write-Host "Pushing to ECR..." -ForegroundColor Cyan
docker push ${ECR_URI}:$UNIQUE_HASH
docker push ${ECR_URI}:latest

# Create task definition JSON
$taskDefJson = @"
{
    "containerDefinitions": [
        {
            "name": "lumisignals-data-orchestrator",
            "image": "${ECR_URI}:${UNIQUE_HASH}",
            "cpu": 0,
            "portMappings": [
                {
                    "containerPort": 8080,
                    "hostPort": 8080,
                    "protocol": "tcp"
                }
            ],
            "essential": true,
            "environment": [
                {
                    "name": "COLLECTION_INTERVAL_SECONDS",
                    "value": "300"
                },
                {
                    "name": "AWS_DEFAULT_REGION",
                    "value": "us-east-1"
                },
                {
                    "name": "MAX_REQUESTS_PER_SECOND",
                    "value": "20"
                },
                {
                    "name": "LOG_LEVEL",
                    "value": "INFO"
                },
                {
                    "name": "REDIS_TTL_SECONDS",
                    "value": "300"
                },
                {
                    "name": "ENABLE_H1_BACKFILL",
                    "value": "true"
                }
            ],
            "mountPoints": [],
            "volumesFrom": [],
            "secrets": [
                {
                    "name": "OANDA_API_KEY",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::"
                },
                {
                    "name": "OANDA_ACCOUNT_ID",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::"
                },
                {
                    "name": "OANDA_ENVIRONMENT",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::"
                },
                {
                    "name": "DATABASE_HOST",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:host::"
                },
                {
                    "name": "DATABASE_PORT",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:port::"
                },
                {
                    "name": "DATABASE_NAME",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:dbname::"
                },
                {
                    "name": "DATABASE_USERNAME",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:username::"
                },
                {
                    "name": "DATABASE_PASSWORD",
                    "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:password::"
                }
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/ecs/lumisignals-data-orchestrator",
                    "awslogs-region": "us-east-1",
                    "awslogs-stream-prefix": "ecs"
                }
            },
            "systemControls": []
        }
    ],
    "family": "lumisignals-data-orchestrator",
    "taskRoleArn": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-role",
    "executionRoleArn": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role",
    "networkMode": "awsvpc",
    "volumes": [],
    "requiresCompatibilities": [
        "FARGATE"
    ],
    "cpu": "2048",
    "memory": "4096"
}
"@

# Save task definition
$taskDefJson | Out-File -FilePath "hotfix-task-def.json" -Encoding UTF8

# Register task definition
Write-Host "Registering task definition..." -ForegroundColor Cyan
$newTaskRevision = aws ecs register-task-definition --region $AWS_REGION --cli-input-json file://hotfix-task-def.json --query 'taskDefinition.revision' --output text

Write-Host "New task definition: ${TASK_FAMILY}:${newTaskRevision}" -ForegroundColor Green

# Update service
Write-Host "Updating ECS service..." -ForegroundColor Cyan
aws ecs update-service --cluster $ECS_CLUSTER --service $ECS_SERVICE --task-definition "${TASK_FAMILY}:${newTaskRevision}" --region $AWS_REGION --query 'service.{ServiceName:serviceName,TaskDefinition:taskDefinition,Status:status}' --output table

# Wait
Write-Host "Waiting for deployment..." -ForegroundColor Cyan
aws ecs wait services-stable --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION

# Verify
Write-Host "Verifying deployment..." -ForegroundColor Cyan
aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION --query 'services[0].{Status:status,RunningCount:runningCount,DesiredCount:desiredCount,TaskDefinition:taskDefinition}' --output table

# Clean up
Remove-Item -Path "hotfix-task-def.json" -Force

Write-Host ""
Write-Host "HOTFIX DEPLOYED!" -ForegroundColor Green
Write-Host "Fixed: max_candles variable scope issue in H1 backfill" -ForegroundColor Yellow
Write-Host ""
Write-Host "Monitor logs to verify H1 backfill is working:" -ForegroundColor Cyan
Write-Host 'aws logs tail /ecs/lumisignals-data-orchestrator --region us-east-1 --follow' -ForegroundColor Gray