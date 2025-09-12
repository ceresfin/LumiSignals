#!/bin/bash
"""
Fargate Data Orchestrator Deployment with Redis Verification

This script:
1. Builds and deploys the Fargate data orchestrator 
2. Includes Redis verification scripts in the container
3. Runs a post-deployment verification task
4. Validates the tiered storage system has 500 candles
"""

set -e

# Configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPOSITORY="lumisignals-data-orchestrator"
ECS_CLUSTER="lumisignals-trading-cluster"
ECS_SERVICE="lumisignals-data-orchestrator"
TASK_DEFINITION="lumisignals-data-orchestrator"

echo "🚀 Deploying Fargate Data Orchestrator with Redis Verification"
echo "============================================================="

# Step 1: Build and push the Docker image
echo ""
echo "📦 Building Docker image..."
echo "-----------------------------"

# Login to ECR
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Build the image
docker build -t $ECR_REPOSITORY .

# Tag and push
IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR_REPOSITORY:latest"
docker tag $ECR_REPOSITORY:latest $IMAGE_URI
docker push $IMAGE_URI

echo "✓ Image pushed to: $IMAGE_URI"

# Step 2: Update ECS task definition
echo ""
echo "🔄 Updating ECS task definition..."
echo "----------------------------------"

# Get current task definition
CURRENT_TASK_DEF=$(aws ecs describe-task-definition \
    --task-definition $TASK_DEFINITION \
    --region $REGION \
    --query 'taskDefinition')

# Update the image URI in the task definition
UPDATED_TASK_DEF=$(echo $CURRENT_TASK_DEF | sed "s|\"image\": \"[^\"]*\"|\"image\": \"$IMAGE_URI\"|g")

# Register new task definition
NEW_TASK_DEF=$(echo $UPDATED_TASK_DEF | aws ecs register-task-definition \
    --cli-input-json file:///dev/stdin \
    --region $REGION \
    --query 'taskDefinition.taskDefinitionArn' \
    --output text)

echo "✓ New task definition: $NEW_TASK_DEF"

# Step 3: Update the ECS service
echo ""
echo "🔄 Updating ECS service..."
echo "--------------------------"

aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE \
    --task-definition $NEW_TASK_DEF \
    --region $REGION \
    --query 'service.serviceName' \
    --output text

echo "✓ Service update initiated"

# Step 4: Wait for deployment to complete
echo ""
echo "⏳ Waiting for deployment to complete..."
echo "----------------------------------------"

aws ecs wait services-stable \
    --cluster $ECS_CLUSTER \
    --services $ECS_SERVICE \
    --region $REGION

echo "✓ Deployment completed successfully"

# Step 5: Run Redis verification task
echo ""
echo "🔍 Running Redis verification task..."
echo "------------------------------------"

# Create verification task definition
VERIFICATION_TASK_DEF=$(cat <<EOF
{
    "family": "redis-verification-task",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "256",
    "memory": "512",
    "executionRoleArn": "arn:aws:iam::$ACCOUNT_ID:role/ecsTaskExecutionRole",
    "taskRoleArn": "arn:aws:iam::$ACCOUNT_ID:role/ecs-task-role",
    "containerDefinitions": [
        {
            "name": "redis-verifier",
            "image": "$IMAGE_URI",
            "essential": true,
            "command": ["python3", "test_redis_from_fargate.py", "--full-verification", "--save-results"],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/ecs/redis-verification",
                    "awslogs-region": "$REGION",
                    "awslogs-stream-prefix": "verification"
                }
            },
            "environment": [
                {
                    "name": "AWS_DEFAULT_REGION",
                    "value": "$REGION"
                }
            ],
            "secrets": [
                {
                    "name": "REDIS_CREDENTIALS",
                    "valueFrom": "arn:aws:secretsmanager:$REGION:$ACCOUNT_ID:secret:lumisignals/redis/market-data/auth-token"
                }
            ]
        }
    ]
}
EOF
)

# Register verification task definition
echo "$VERIFICATION_TASK_DEF" | aws ecs register-task-definition \
    --cli-input-json file:///dev/stdin \
    --region $REGION > /dev/null

# Get the VPC and subnet configuration from the existing service
VPC_CONFIG=$(aws ecs describe-services \
    --cluster $ECS_CLUSTER \
    --services $ECS_SERVICE \
    --region $REGION \
    --query 'services[0].networkConfiguration.awsvpcConfiguration.{subnets:subnets,securityGroups:securityGroups}')

SUBNETS=$(echo $VPC_CONFIG | grep -o '"subnets":\[[^]]*\]' | sed 's/"subnets"://')
SECURITY_GROUPS=$(echo $VPC_CONFIG | grep -o '"securityGroups":\[[^]]*\]' | sed 's/"securityGroups"://')

# Run the verification task
echo "Running verification task in same VPC as the service..."

VERIFICATION_TASK_ARN=$(aws ecs run-task \
    --cluster $ECS_CLUSTER \
    --task-definition "redis-verification-task" \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=$SUBNETS,securityGroups=$SECURITY_GROUPS,assignPublicIp=ENABLED}" \
    --region $REGION \
    --query 'tasks[0].taskArn' \
    --output text)

echo "✓ Verification task started: $VERIFICATION_TASK_ARN"

# Wait for verification task to complete
echo "⏳ Waiting for verification to complete..."

aws ecs wait tasks-stopped \
    --cluster $ECS_CLUSTER \
    --tasks $VERIFICATION_TASK_ARN \
    --region $REGION

# Get verification results from logs
echo ""
echo "📋 Verification Results:"
echo "------------------------"

LOG_GROUP="/ecs/redis-verification"

# Get the latest log stream
LOG_STREAM=$(aws logs describe-log-streams \
    --log-group-name $LOG_GROUP \
    --order-by LastEventTime \
    --descending \
    --max-items 1 \
    --region $REGION \
    --query 'logStreams[0].logStreamName' \
    --output text 2>/dev/null || echo "")

if [ -n "$LOG_STREAM" ] && [ "$LOG_STREAM" != "None" ]; then
    echo "📄 Fetching logs from: $LOG_STREAM"
    
    aws logs get-log-events \
        --log-group-name $LOG_GROUP \
        --log-stream-name $LOG_STREAM \
        --region $REGION \
        --query 'events[*].message' \
        --output text
else
    echo "⚠️ No verification logs found. Task may have failed to start."
fi

# Check task exit code
TASK_STATUS=$(aws ecs describe-tasks \
    --cluster $ECS_CLUSTER \
    --tasks $VERIFICATION_TASK_ARN \
    --region $REGION \
    --query 'tasks[0].containers[0].exitCode' \
    --output text)

echo ""
echo "🎯 Deployment Summary:"
echo "----------------------"
echo "✓ Docker image built and pushed"
echo "✓ ECS service updated"
echo "✓ Deployment completed"

if [ "$TASK_STATUS" = "0" ]; then
    echo "✅ Redis verification: PASSED"
    echo ""
    echo "🎉 SUCCESS: Fargate Data Orchestrator deployed and verified!"
    echo ""
    echo "Next steps:"
    echo "1. Monitor the service: aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE"
    echo "2. Check logs: aws logs tail /ecs/lumisignals-data-orchestrator --follow"
    echo "3. Verify data collection: aws logs tail /ecs/redis-verification --follow"
else
    echo "⚠️ Redis verification: FAILED (exit code: $TASK_STATUS)"
    echo ""
    echo "🚨 Deployment completed but verification failed."
    echo "Check the logs above for issues with Redis connectivity or data."
fi

echo ""
echo "📊 Useful monitoring commands:"
echo "------------------------------"
echo "# Check service status"
echo "aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}'"
echo ""
echo "# Monitor application logs"
echo "aws logs tail /ecs/lumisignals-data-orchestrator --follow"
echo ""
echo "# Run manual Redis verification"
echo "aws ecs run-task --cluster $ECS_CLUSTER --task-definition redis-verification-task --launch-type FARGATE --network-configuration \"awsvpcConfiguration={subnets=$SUBNETS,securityGroups=$SECURITY_GROUPS,assignPublicIp=ENABLED}\""