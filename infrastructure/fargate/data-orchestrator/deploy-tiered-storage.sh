#!/bin/bash
# TIERED STORAGE DEPLOYMENT: 500 Candlestick Lazy Loading System
# Based on Golden Template TD 196 + Enhanced with Tiered Storage

echo "========================================"
echo "TIERED STORAGE DEPLOYMENT"
echo "500 Candlestick Lazy Loading System"
echo "========================================"
echo
echo "NEW FEATURES:"
echo "1. Hot Tier: 50 most recent candles (1 day TTL)"
echo "2. Warm Tier: 450 older candles (5 day TTL)" 
echo "3. Cold Tier: 500 bootstrap candles (7 day TTL)"
echo "4. Automatic rotation: Hot -> Warm tier management"
echo "5. Smart retrieval: Multi-tier fallback system"
echo "6. Bootstrap collection: ENABLE_BOOTSTRAP=true"
echo
echo "BASED ON GOLDEN TEMPLATE TD 196:"
echo "✅ Correct IAM roles (both task + execution)"
echo "✅ High performance: CPU 2048, Memory 4096"
echo "✅ JSON secrets format (Architecture Bible)"
echo "✅ Proven deployment verification process"
echo

# Generate timestamp for unique container tag
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
IMAGE_TAG="816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:tiered-storage-${TIMESTAMP}"

echo "[1/9] Building container with tiered storage system..."
echo "Image: $IMAGE_TAG"
docker build --no-cache --build-arg VERSION="tiered-storage-${TIMESTAMP}" --build-arg CACHEBUST="${TIMESTAMP}" -t "${IMAGE_TAG}" . || exit 1

echo
echo "[2/9] Pushing to ECR..."
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com
docker push "${IMAGE_TAG}" || exit 1

echo
echo "[3/9] Creating task definition with Golden Template TD 196 configuration + Tiered Storage environment variables..."
echo "USING: Golden Template IAM roles + CPU/Memory + Secrets"

# Create the task definition with environment variables
NEW_REVISION=$(aws ecs register-task-definition \
--family lumisignals-data-orchestrator \
--task-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-role \
--execution-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role \
--network-mode awsvpc \
--requires-compatibilities FARGATE \
--cpu 2048 \
--memory 4096 \
--container-definitions '[{
  "name": "lumisignals-data-orchestrator",
  "image": "'${IMAGE_TAG}'",
  "essential": true,
  "environment": [
    {"name": "TIMEFRAMES", "value": "M5,H1"},
    {"name": "AGGREGATED_TIMEFRAMES", "value": "M15,M30"},
    {"name": "HOT_TIER_CANDLES", "value": "50"},
    {"name": "WARM_TIER_CANDLES", "value": "450"},
    {"name": "BOOTSTRAP_CANDLES", "value": "500"},
    {"name": "HOT_TIER_TTL", "value": "86400"},
    {"name": "WARM_TIER_TTL", "value": "432000"},
    {"name": "COLD_TIER_TTL", "value": "604800"},
    {"name": "ENABLE_BOOTSTRAP", "value": "true"},
    {"name": "COLLECTION_INTERVAL_SECONDS", "value": "300"}
  ],
  "logConfiguration": {
    "logDriver": "awslogs",
    "options": {
      "awslogs-group": "/ecs/lumisignals-data-orchestrator",
      "awslogs-region": "us-east-1",
      "awslogs-stream-prefix": "ecs"
    }
  },
  "secrets": [
    {"name": "OANDA_API_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::"},
    {"name": "OANDA_ACCOUNT_ID", "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::"},
    {"name": "OANDA_ENVIRONMENT", "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::"},
    {"name": "DATABASE_CREDENTIALS", "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials"}
  ]
}]' \
--region us-east-1 --query "taskDefinition.revision" --output text)

echo "✅ Created Task Definition: lumisignals-data-orchestrator:$NEW_REVISION"

echo
echo "[4/9] Verifying task definition configuration..."

# Verify IAM roles (Golden Template requirement)
TASK_ROLE=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region us-east-1 --query "taskDefinition.taskRoleArn" --output text)
echo "Task Role ARN: $TASK_ROLE"
if [[ "$TASK_ROLE" == *"lumisignals-ecs-task-role"* ]]; then
    echo "✅ VERIFIED: Correct IAM task role configured"
else
    echo "❌ ERROR: Wrong IAM task role! Expected lumisignals-ecs-task-role"
    exit 1
fi

# Verify execution role  
EXEC_ROLE=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region us-east-1 --query "taskDefinition.executionRoleArn" --output text)
echo "Execution Role ARN: $EXEC_ROLE"
if [[ "$EXEC_ROLE" == *"lumisignals-ecs-task-execution-role"* ]]; then
    echo "✅ VERIFIED: Correct IAM execution role configured"
else
    echo "❌ ERROR: Wrong IAM execution role! Expected lumisignals-ecs-task-execution-role"
    exit 1
fi

# Verify secrets (Golden Template requirement)
SECRETS_COUNT=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text)
echo "Secrets count: $SECRETS_COUNT"
if [ "$SECRETS_COUNT" == "4" ]; then
    echo "✅ VERIFIED: 4 secrets configured correctly"
else
    echo "❌ ERROR: Expected 4 secrets, got $SECRETS_COUNT"
    exit 1
fi

# Verify environment variables (Tiered Storage requirement)
ENV_COUNT=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].environment)" --output text)
echo "Environment variables count: $ENV_COUNT"
if [ "$ENV_COUNT" -ge "10" ]; then
    echo "✅ VERIFIED: Tiered storage environment variables configured ($ENV_COUNT total)"
else
    echo "❌ ERROR: Expected at least 10 environment variables, got $ENV_COUNT"
    exit 1
fi

# Verify CPU/Memory (Golden Template requirement)
CPU_UNITS=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region us-east-1 --query "taskDefinition.cpu" --output text)
MEMORY_UNITS=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region us-east-1 --query "taskDefinition.memory" --output text)
echo "CPU: $CPU_UNITS, Memory: $MEMORY_UNITS"
if [ "$CPU_UNITS" == "2048" ] && [ "$MEMORY_UNITS" == "4096" ]; then
    echo "✅ VERIFIED: High performance configuration (Golden Template standard)"
else
    echo "❌ ERROR: Expected CPU 2048, Memory 4096, got CPU $CPU_UNITS, Memory $MEMORY_UNITS"
    exit 1
fi

echo
echo "[5/9] Deploying service with new task definition..."
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:$NEW_REVISION --desired-count 1 --force-new-deployment --region us-east-1

echo
echo "[6/9] Waiting 45 seconds for deployment to start..."
sleep 45

echo
echo "[7/9] CRITICAL: Verifying task actually starts (prevents silent failures)..."
echo "Checking running tasks..."
TASK_ARN=$(aws ecs list-tasks --cluster lumisignals-cluster --service-name lumisignals-data-orchestrator --region us-east-1 --query "taskArns[0]" --output text)

if [ "$TASK_ARN" == "None" ] || [ "$TASK_ARN" == "" ]; then
    echo "❌ ERROR: No running task found!"
    echo "Checking ECS service events for errors..."
    aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:5]" --output table
    exit 1
fi

echo "Found running task: $TASK_ARN"
echo "Checking task definition revision..."
RUNNING_TD=$(aws ecs describe-tasks --cluster lumisignals-cluster --tasks $TASK_ARN --region us-east-1 --query "tasks[0].taskDefinitionArn" --output text)
echo "Running task definition: $RUNNING_TD"

if [[ "$RUNNING_TD" == *":$NEW_REVISION"* ]]; then
    echo "✅ VERIFIED: New task definition $NEW_REVISION is running!"
else
    echo "⚠️ WARNING: Task is still running old definition"
    echo "Waiting additional 2 minutes for rollout..."
    sleep 120
    
    # Re-check after wait
    TASK_ARN2=$(aws ecs list-tasks --cluster lumisignals-cluster --service-name lumisignals-data-orchestrator --region us-east-1 --query "taskArns[0]" --output text)
    RUNNING_TD2=$(aws ecs describe-tasks --cluster lumisignals-cluster --tasks $TASK_ARN2 --region us-east-1 --query "tasks[0].taskDefinitionArn" --output text)
    echo "Re-check - Running task definition: $RUNNING_TD2"
    
    if [[ "$RUNNING_TD2" == *":$NEW_REVISION"* ]]; then
        echo "✅ VERIFIED: New task definition $NEW_REVISION is now running!"
    else
        echo "❌ ERROR: Deployment failed - still running old task definition"
        echo "Checking service events..."
        aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:5]" --output table
        exit 1
    fi
fi

echo
echo "[8/9] Waiting 2 minutes for bootstrap collection to initialize..."
echo "BOOTSTRAP PROCESS: ENABLE_BOOTSTRAP=true will collect 500 candles for all pairs/timeframes"
sleep 120

echo
echo "[9/9] Checking for tiered storage initialization messages..."
# Get latest log stream
STREAM_NAME=$(aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text)

echo
echo "Looking for tiered storage and bootstrap initialization messages..."
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "$STREAM_NAME" --region us-east-1 --query "events[-60:].message" --output text | grep -E "Bootstrap enabled|tiered Redis storage|Bootstrap collection completed|hot tier|warm tier|ERROR|Failed"

echo
echo "========================================"
echo "TIERED STORAGE DEPLOYMENT COMPLETED!"
echo "========================================"
echo
echo "Container: $IMAGE_TAG"
echo "Task Definition: $NEW_REVISION"
echo "Configuration Summary:"
echo "  ✅ Hot Tier: 50 candles (1 day TTL)"
echo "  ✅ Warm Tier: 450 candles (5 day TTL)"
echo "  ✅ Cold Tier: 500 candles (7 day TTL)"
echo "  ✅ Bootstrap: Enabled (500 candles on startup)"
echo "  ✅ Timeframes: M5, H1 (native) + M15, M30 (aggregated)"
echo "  ✅ Golden Template: IAM roles, CPU/Memory, Secrets"
echo
echo "MONITORING COMMANDS:"
echo "# Watch logs for bootstrap completion:"
echo "aws logs tail /ecs/lumisignals-data-orchestrator --follow --region us-east-1"
echo
echo "# Check current task definition:"
echo "aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query \"services[0].taskDefinition\" --output text"
echo
echo "Next Steps:"
echo "1. Monitor logs for 'Bootstrap collection completed successfully'"  
echo "2. Check pipstop.org charts for improved loading (500 candlesticks)"
echo "3. Monitor tier utilization via CloudWatch"
echo "4. Test chart scrollback performance with 500 candles"
echo

echo "Deployment completed successfully!"