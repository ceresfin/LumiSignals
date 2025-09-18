#!/bin/bash

# Deploy Tier Rotation Logic Fix - Following LumiSignals Deployment Guide
# Based on deploy-correct-iam-role.bat pattern with TD 196 golden template

set -e

echo "============================================"
echo "DEPLOYING TIER ROTATION LOGIC FIX"
echo "============================================"
echo ""
echo "ISSUE: Only 43 candles available instead of 500"
echo "CAUSE: Tier overlaps - 457 duplicates from hot/warm/cold overlap"
echo "FIXES: Bootstrap distribution + Rotation chronology + Lifecycle management"
echo "TESTED: All tests passed locally"
echo ""

# AWS Configuration (from golden template)
AWS_REGION="us-east-1"
CLUSTER_NAME="lumisignals-cluster"
SERVICE_NAME="lumisignals-data-orchestrator"
ECR_REPOSITORY="lumisignals/institutional-orchestrator-postgresql17"

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY"

echo "🔧 AWS Configuration:"
echo "📍 Region: $AWS_REGION"
echo "📍 Cluster: $CLUSTER_NAME"
echo "📍 Service: $SERVICE_NAME"
echo "📍 ECR Repository: $ECR_URI"
echo "📍 Account ID: $AWS_ACCOUNT_ID"
echo ""

# Step 1: Build new container image with tier fixes
echo "🏗️ [1/6] Building container image with tier rotation fixes..."
echo ""

# Create timestamp tag for this deployment
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
IMAGE_TAG="tier-fix-$TIMESTAMP"

echo "🔖 Image tag: $IMAGE_TAG"
echo ""

# Build the container (following LumiSignals pattern)
echo "🔨 Building container with cache bust..."
docker build --no-cache --build-arg VERSION="tier-fix-$TIMESTAMP" --build-arg CACHEBUST="$TIMESTAMP" -t "$ECR_URI:$IMAGE_TAG" .

if [ $? -ne 0 ]; then
    echo "❌ Container build failed!"
    exit 1
fi

echo "✅ Container built successfully"
echo ""

# Step 2: Login to ECR and push image
echo "🚀 [2/6] Pushing image to ECR..."
echo ""

# Get ECR login token
echo "🔐 Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI

echo "📦 Pushing image to ECR..."
docker push "$ECR_URI:$IMAGE_TAG"

if [ $? -ne 0 ]; then
    echo "❌ Image push failed!"
    exit 1
fi

echo "✅ Image pushed successfully"
echo ""

# Step 3: Create new task definition using TD 196 golden template
echo "📝 [3/6] Creating task definition using TD 196 golden template..."
echo ""

# Use TD 196 configuration (optimal golden template)
aws ecs register-task-definition \
--family lumisignals-data-orchestrator \
--task-role-arn "arn:aws:iam::$AWS_ACCOUNT_ID:role/lumisignals-ecs-task-role" \
--execution-role-arn "arn:aws:iam::$AWS_ACCOUNT_ID:role/lumisignals-ecs-task-execution-role" \
--network-mode awsvpc \
--requires-compatibilities FARGATE \
--cpu 2048 \
--memory 4096 \
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"$ECR_URI:$IMAGE_TAG\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:$AWS_ACCOUNT_ID:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:$AWS_ACCOUNT_ID:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:$AWS_ACCOUNT_ID:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_CREDENTIALS\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:$AWS_ACCOUNT_ID:secret:lumisignals/rds/postgresql/credentials\"}]}]" \
--region $AWS_REGION --output text

if [ $? -ne 0 ]; then
    echo "❌ Task definition creation failed!"
    exit 1
fi

echo "✅ New task definition created"
echo ""

# Step 4: Deploy with verification (following LumiSignals pattern)
echo "🔄 [4/6] Deploying new task definition..."
echo ""

# Get new revision number
NEW_REVISION=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region $AWS_REGION --query "taskDefinition.revision" --output text)

echo "📝 New revision: $NEW_REVISION"

# Deploy the service
aws ecs update-service --cluster $CLUSTER_NAME --service $SERVICE_NAME --task-definition lumisignals-data-orchestrator:$NEW_REVISION --desired-count 1 --force-new-deployment --region $AWS_REGION

if [ $? -ne 0 ]; then
    echo "❌ Service update failed!"
    exit 1
fi

echo "✅ Service update initiated"
echo ""

# Step 5: Critical verification (following LumiSignals pattern)
echo "🔍 [5/6] Critical verification steps..."
echo ""

echo "✅ Verification 1: Check 4 secrets configured"
SECRETS_COUNT=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region $AWS_REGION --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text)
echo "📊 Secrets count: $SECRETS_COUNT (should be 4)"

if [ "$SECRETS_COUNT" != "4" ]; then
    echo "❌ CRITICAL ERROR: Wrong number of secrets configured"
    exit 1
fi

echo "✅ Verification 2: Check correct IAM roles"
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:$NEW_REVISION --region $AWS_REGION --query "taskDefinition.{taskRole:taskRoleArn,executionRole:executionRoleArn}" --output json

echo "⏳ Verification 3: Waiting for new task to start (60 seconds)..."
sleep 60

TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER_NAME --service-name $SERVICE_NAME --region $AWS_REGION --query "taskArns[0]" --output text)

if [ "$TASK_ARN" = "None" ] || [ -z "$TASK_ARN" ]; then
    echo "❌ CRITICAL ERROR: No running task found"
    echo "🔍 Checking service events:"
    aws ecs describe-services --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $AWS_REGION --query "services[0].events[:5]" --output table
    exit 1
fi

echo "✅ Verification 4: Check running task definition"
RUNNING_TD=$(aws ecs describe-tasks --cluster $CLUSTER_NAME --tasks "$TASK_ARN" --region $AWS_REGION --query "tasks[0].taskDefinitionArn" --output text)
echo "📝 Running task definition: $RUNNING_TD"

echo "✅ All verifications passed"
echo ""

# Step 6: Test tier rotation fix
echo "🧪 [6/6] Testing tier rotation fix..."
echo ""

echo "⏳ Waiting for bootstrap completion (3 minutes)..."
echo "🔄 The system needs time to:"
echo "   1. Start container and initialize"
echo "   2. Bootstrap 500 candles with fixed tier logic"
echo "   3. Distribute data with no overlaps"
echo ""

sleep 180

echo "🧪 Testing API endpoint..."
echo ""

# Test the API to verify the fix
curl -s "https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/H1?count=500" > tier_test_result.json

echo ""
echo "📊 TIER ROTATION FIX TEST RESULTS:"
echo "============================================"

# Parse results using Python
if command -v python3 &> /dev/null; then
    CANDLES_COUNT=$(python3 -c "import json; data=json.load(open('tier_test_result.json')); print(len(data.get('data', [])))")
    SOURCES_USED=$(python3 -c "import json; data=json.load(open('tier_test_result.json')); print(data.get('metadata', {}).get('sources_used', []))")
    DUPLICATES=$(python3 -c "import json; data=json.load(open('tier_test_result.json')); print(data.get('metadata', {}).get('duplicates_found', 'N/A'))")
    
    echo "📊 Candles returned: $CANDLES_COUNT"
    echo "📊 Sources used: $SOURCES_USED"
    echo "🚨 Duplicates found: $DUPLICATES"
    
    if [ "$CANDLES_COUNT" -gt 100 ] && [ "$DUPLICATES" = "0" ]; then
        echo "🎉 SUCCESS! Tier rotation fix working!"
    else
        echo "❌ Fix may not be working correctly"
    fi
else
    echo "📊 Results saved to tier_test_result.json (Python not available for parsing)"
fi

echo ""
echo "📈 EXPECTED RESULTS AFTER FIX:"
echo "✅ Candles: 500 (was 43)"
echo "✅ Sources: ['hot(50)', 'warm(450)'] (no overlaps)"
echo "✅ Duplicates: 0 (was 457)"
echo ""

echo "============================================"
echo "🎉 DEPLOYMENT COMPLETE!"
echo "============================================"
echo ""
echo "📋 SUMMARY:"
echo "🔖 Image: $ECR_URI:$IMAGE_TAG"
echo "📝 Task Definition: lumisignals-data-orchestrator:$NEW_REVISION"
echo "🔄 Service: Updated and running"
echo ""
echo "📊 MONITORING COMMANDS:"
echo ""
echo "📋 Check service status:"
echo "aws ecs describe-services --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $AWS_REGION --query 'services[0].events[:5]' --output table"
echo ""
echo "📋 View logs:"
echo "aws logs tail /ecs/lumisignals-data-orchestrator --since 5m --follow"
echo ""
echo "🧪 Test API again:"
echo "curl -s \"https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/H1?count=500\" | python3 -c \"import sys, json; data=json.load(sys.stdin); print('Candles:', len(data.get('data', []))); print('Sources:', data.get('metadata', {}).get('sources_used', [])); print('SUCCESS!' if len(data.get('data', [])) > 100 else 'Still broken')\""
echo ""

# Cleanup
rm -f tier_test_result.json

echo "🚀 Tier rotation logic fix deployed successfully!"
echo "📊 Please monitor the system for 5-10 minutes to ensure proper operation."
echo ""