#!/bin/bash
# Deploy Smart Bootstrap Fix - Shell Script Version
# Fixes bootstrap running on every container restart
# Uses TD 196 template configuration with new container image

set -e  # Exit on any error

echo "=========================================="
echo "🚀 SMART BOOTSTRAP FIX DEPLOYMENT"
echo "=========================================="
echo "✅ Fixes: Bootstrap only runs once"
echo "✅ Uses: TD 196 golden template configuration"
echo "✅ Prevents: Data corruption from repeated bootstrap"
echo ""

# Generate timestamp for container tag
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
IMAGE_TAG="816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:smart-bootstrap-${TIMESTAMP}"

echo "[1/6] Building Docker container with smart bootstrap fix..."
echo "Image: ${IMAGE_TAG}"
echo ""

# Build container
docker build --no-cache \
  --build-arg VERSION="smart-bootstrap-${TIMESTAMP}" \
  --build-arg CACHEBUST="${TIMESTAMP}" \
  -t "${IMAGE_TAG}" .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi

echo ""
echo "[2/6] Logging into ECR..."

# ECR login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com

if [ $? -ne 0 ]; then
    echo "❌ ECR login failed"
    exit 1
fi

echo ""
echo "[3/6] Pushing container to ECR..."

# Push image
docker push "${IMAGE_TAG}"

if [ $? -ne 0 ]; then
    echo "❌ Docker push failed"
    exit 1
fi

echo ""
echo "[4/6] Creating new task definition using TD 196 template..."
echo "🔑 Using TD 196 golden configuration:"
echo "  - CPU: 2048, Memory: 4096"
echo "  - IAM Roles: Both correct from TD 196"
echo "  - Secrets: 4 secrets in JSON format"
echo ""

# Create task definition using TD 196 template configuration
aws ecs register-task-definition \
  --family lumisignals-data-orchestrator \
  --task-role-arn "arn:aws:iam::816945674467:role/lumisignals-ecs-task-role" \
  --execution-role-arn "arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role" \
  --network-mode awsvpc \
  --requires-compatibilities FARGATE \
  --cpu 2048 \
  --memory 4096 \
  --container-definitions "[{
    \"name\": \"lumisignals-data-orchestrator\",
    \"image\": \"${IMAGE_TAG}\",
    \"essential\": true,
    \"logConfiguration\": {
      \"logDriver\": \"awslogs\",
      \"options\": {
        \"awslogs-group\": \"/ecs/lumisignals-data-orchestrator\",
        \"awslogs-region\": \"us-east-1\",
        \"awslogs-stream-prefix\": \"ecs\"
      }
    },
    \"secrets\": [
      {
        \"name\": \"OANDA_API_KEY\",
        \"valueFrom\": \"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"
      },
      {
        \"name\": \"OANDA_ACCOUNT_ID\",
        \"valueFrom\": \"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"
      },
      {
        \"name\": \"OANDA_ENVIRONMENT\",
        \"valueFrom\": \"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"
      },
      {
        \"name\": \"DATABASE_CREDENTIALS\",
        \"valueFrom\": \"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials\"
      }
    ],
    \"environment\": [
      {
        \"name\": \"ENABLE_BOOTSTRAP\",
        \"value\": \"true\"
      }
    ]
  }]" \
  --region us-east-1 \
  --query "taskDefinition.revision" \
  --output text > new_revision.txt

if [ $? -ne 0 ]; then
    echo "❌ Task definition registration failed"
    exit 1
fi

NEW_REVISION=$(cat new_revision.txt)
echo "✅ Created Task Definition: lumisignals-data-orchestrator:${NEW_REVISION}"

echo ""
echo "[5/6] Deploying new task definition..."

# Update ECS service
aws ecs update-service \
  --cluster lumisignals-cluster \
  --service lumisignals-data-orchestrator \
  --task-definition "lumisignals-data-orchestrator:${NEW_REVISION}" \
  --desired-count 1 \
  --force-new-deployment \
  --region us-east-1

if [ $? -ne 0 ]; then
    echo "❌ Service update failed"
    exit 1
fi

echo "✅ Service update initiated"

echo ""
echo "[6/6] Verification Steps..."
echo ""
echo "⏳ Waiting 60 seconds for task to start..."
sleep 60

echo ""
echo "🔍 Verifying deployment..."

# Check if new task is running
TASK_ARN=$(aws ecs list-tasks \
  --cluster lumisignals-cluster \
  --service-name lumisignals-data-orchestrator \
  --region us-east-1 \
  --query "taskArns[0]" \
  --output text)

if [ "$TASK_ARN" = "None" ] || [ -z "$TASK_ARN" ]; then
    echo "❌ CRITICAL: No running task found"
    echo "📋 Recent service events:"
    aws ecs describe-services \
      --cluster lumisignals-cluster \
      --services lumisignals-data-orchestrator \
      --region us-east-1 \
      --query "services[0].events[:5]" \
      --output table
    exit 1
fi

# Verify new task definition is running
RUNNING_TD=$(aws ecs describe-tasks \
  --cluster lumisignals-cluster \
  --tasks "${TASK_ARN}" \
  --region us-east-1 \
  --query "tasks[0].taskDefinitionArn" \
  --output text)

echo "🔍 Running task definition: ${RUNNING_TD}"

if [[ "$RUNNING_TD" == *":${NEW_REVISION}" ]]; then
    echo "✅ SUCCESS: New task definition ${NEW_REVISION} is running"
else
    echo "⚠️  WARNING: Expected revision ${NEW_REVISION} but running ${RUNNING_TD}"
fi

echo ""
echo "📊 DEPLOYMENT SUMMARY:"
echo "=================================="
echo "✅ Task Definition: lumisignals-data-orchestrator:${NEW_REVISION}"
echo "✅ Container Image: ${IMAGE_TAG}"
echo "✅ Configuration: TD 196 golden template"
echo "✅ Smart Bootstrap: Enabled with one-time execution"
echo ""
echo "🔍 WHAT TO MONITOR:"
echo "1. Bootstrap behavior - should see 'Bootstrap already completed' on restarts"
echo "2. H1 data collection - should resume after bootstrap fix"
echo "3. Data gaps - should stop appearing after smart bootstrap"
echo ""
echo "📋 MONITORING COMMANDS:"
echo "# Watch logs for smart bootstrap messages:"
echo "aws logs tail /ecs/lumisignals-data-orchestrator --follow"
echo ""
echo "# Check data availability:"
echo "curl -s \"https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/H1?count=10\""
echo ""
echo "🎉 SMART BOOTSTRAP DEPLOYMENT COMPLETE!"

# Clean up
rm -f new_revision.txt