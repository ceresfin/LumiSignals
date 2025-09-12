#!/bin/bash
"""
Quick Redis Verification Runner

This script runs a one-time Redis verification task in the same VPC
as your Fargate service to check the tiered storage system.

Usage:
    ./run_redis_check.sh
    ./run_redis_check.sh --follow-logs
"""

set -e

# Configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPOSITORY="lumisignals-data-orchestrator"
ECS_CLUSTER="lumisignals-trading-cluster"
ECS_SERVICE="lumisignals-data-orchestrator"

echo "🔍 Running Redis Storage Verification"
echo "====================================="

# Get the current image URI from the running service
IMAGE_URI=$(aws ecs describe-services \
    --cluster $ECS_CLUSTER \
    --services $ECS_SERVICE \
    --region $REGION \
    --query 'services[0].taskDefinition' \
    --output text | xargs -I {} aws ecs describe-task-definition \
    --task-definition {} \
    --region $REGION \
    --query 'taskDefinition.containerDefinitions[0].image' \
    --output text)

echo "📦 Using image: $IMAGE_URI"

# Get VPC configuration from existing service
echo "🌐 Getting VPC configuration..."

VPC_CONFIG=$(aws ecs describe-services \
    --cluster $ECS_CLUSTER \
    --services $ECS_SERVICE \
    --region $REGION \
    --query 'services[0].networkConfiguration.awsvpcConfiguration')

SUBNETS=$(echo $VPC_CONFIG | grep -o '"subnets":\[[^]]*\]' | sed 's/"subnets"://' | tr -d ' ')
SECURITY_GROUPS=$(echo $VPC_CONFIG | grep -o '"securityGroups":\[[^]]*\]' | sed 's/"securityGroups"://' | tr -d ' ')

echo "📡 Subnets: $SUBNETS"
echo "🔒 Security Groups: $SECURITY_GROUPS"

# Create verification task definition if it doesn't exist
echo ""
echo "📋 Setting up verification task..."

aws ecs describe-task-definition \
    --task-definition "redis-verification-task" \
    --region $REGION > /dev/null 2>&1 || {
    
    echo "Creating new verification task definition..."
    
    cat <<EOF | aws ecs register-task-definition \
        --cli-input-json file:///dev/stdin \
        --region $REGION > /dev/null
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
    echo "✓ Task definition created"
}

# Run the verification task
echo ""
echo "🚀 Starting verification task..."

TASK_ARN=$(aws ecs run-task \
    --cluster $ECS_CLUSTER \
    --task-definition "redis-verification-task" \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=$SUBNETS,securityGroups=$SECURITY_GROUPS,assignPublicIp=ENABLED}" \
    --region $REGION \
    --query 'tasks[0].taskArn' \
    --output text)

if [ -z "$TASK_ARN" ] || [ "$TASK_ARN" = "null" ]; then
    echo "❌ Failed to start verification task"
    exit 1
fi

echo "✓ Task started: $TASK_ARN"

# Follow logs if requested
if [ "$1" = "--follow-logs" ]; then
    echo ""
    echo "📄 Following logs (Ctrl+C to stop)..."
    echo "------------------------------------"
    
    # Extract task ID from ARN
    TASK_ID=$(echo $TASK_ARN | rev | cut -d'/' -f1 | rev)
    
    # Wait a moment for the log stream to be created
    sleep 10
    
    # Try to tail logs
    aws logs tail /ecs/redis-verification \
        --follow \
        --region $REGION \
        --log-stream-names "verification/redis-verifier/$TASK_ID" 2>/dev/null || {
        echo "⚠️ Could not follow logs directly. Task may still be starting."
        echo "Manual log command:"
        echo "aws logs tail /ecs/redis-verification --follow --region $REGION"
    }
fi

# Wait for task completion
echo ""
echo "⏳ Waiting for verification to complete..."

aws ecs wait tasks-stopped \
    --cluster $ECS_CLUSTER \
    --tasks $TASK_ARN \
    --region $REGION

# Get results
echo ""
echo "📊 Verification Results:"
echo "========================"

# Get task exit code
EXIT_CODE=$(aws ecs describe-tasks \
    --cluster $ECS_CLUSTER \
    --tasks $TASK_ARN \
    --region $REGION \
    --query 'tasks[0].containers[0].exitCode' \
    --output text)

# Get logs
LOG_STREAM=$(aws logs describe-log-streams \
    --log-group-name "/ecs/redis-verification" \
    --order-by LastEventTime \
    --descending \
    --max-items 1 \
    --region $REGION \
    --query 'logStreams[0].logStreamName' \
    --output text 2>/dev/null)

if [ -n "$LOG_STREAM" ] && [ "$LOG_STREAM" != "None" ]; then
    aws logs get-log-events \
        --log-group-name "/ecs/redis-verification" \
        --log-stream-name "$LOG_STREAM" \
        --region $REGION \
        --query 'events[*].message' \
        --output text | tail -20
else
    echo "⚠️ No logs found"
fi

# Final status
echo ""
if [ "$EXIT_CODE" = "0" ]; then
    echo "✅ Redis verification completed successfully!"
    echo ""
    echo "Key indicators to check in the logs above:"
    echo "- Connected shards: Should be 4/4"
    echo "- Pairs with data: Should be > 0"  
    echo "- Total candles: Should be 500+ per major pair"
    echo "- Overall status: Should be PASS"
else
    echo "❌ Redis verification failed (exit code: $EXIT_CODE)"
    echo ""
    echo "Common issues to check:"
    echo "- VPC connectivity to Redis cluster"
    echo "- Redis auth token configuration"
    echo "- Data orchestrator bootstrap completion"
fi

echo ""
echo "🔧 Useful commands:"
echo "------------------"
echo "# View full logs:"
echo "aws logs tail /ecs/redis-verification --region $REGION"
echo ""
echo "# Check data orchestrator service:"
echo "aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $REGION"
echo ""
echo "# Manual verification from inside VPC:"
echo "aws ecs run-task --cluster $ECS_CLUSTER --task-definition redis-verification-task --launch-type FARGATE --network-configuration \"awsvpcConfiguration={subnets=$SUBNETS,securityGroups=$SECURITY_GROUPS,assignPublicIp=ENABLED}\" --region $REGION"