#!/bin/bash

# LumiSignals Data Orchestrator Deployment Script
# Builds Docker image with updated config (1200 M5 candles) and deploys to ECS
# Usage: ./deploy-with-config-update.sh

set -e

echo "🚀 Starting LumiSignals Data Orchestrator deployment with config update..."

# Configuration
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="816945674467"
ECR_REPOSITORY="lumisignals-data-orchestrator"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
ECS_CLUSTER="lumisignals-cluster"
ECS_SERVICE="lumisignals-data-orchestrator"
TASK_FAMILY="lumisignals-data-orchestrator"

# Generate unique hash for this deployment
COMMIT_SHA=$(git rev-parse --short HEAD)
BUILD_DATE=$(date +%Y%m%d-%H%M%S)
UNIQUE_HASH="${COMMIT_SHA}-${BUILD_DATE}"
VERSION="h1-backfill-1200-candles-${UNIQUE_HASH}"

echo "📋 Deployment Details:"
echo "   Repository: ${ECR_URI}"
echo "   Version: ${VERSION}"
echo "   Hash: ${UNIQUE_HASH}"
echo "   Build Date: ${BUILD_DATE}"
echo ""

# Step 1: Login to ECR
echo "🔐 Logging in to Amazon ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_URI}

# Step 2: Build Docker image with updated config
echo "🏗️ Building Docker image with config updates..."
echo "   Config: 1200 historical M5 candles (100 hours of data)"
echo "   TTL: 5 days (432000 seconds)"

# Build with version info and cache busting
docker build \
    --build-arg VERSION="${VERSION}" \
    --build-arg BUILD_DATE="${BUILD_DATE}" \
    --build-arg COMMIT_SHA="${COMMIT_SHA}" \
    --build-arg CACHEBUST="$(date +%s)" \
    --platform linux/amd64 \
    -t ${ECR_REPOSITORY}:${UNIQUE_HASH} \
    -t ${ECR_REPOSITORY}:latest \
    .

# Step 3: Tag images for ECR
echo "🏷️ Tagging images for ECR..."
docker tag ${ECR_REPOSITORY}:${UNIQUE_HASH} ${ECR_URI}:${UNIQUE_HASH}
docker tag ${ECR_REPOSITORY}:latest ${ECR_URI}:latest

# Step 4: Push images to ECR with extended timeout
echo "☁️ Pushing images to ECR (extended timeout: 15 minutes each)..."
echo "   Pushing tagged version: ${UNIQUE_HASH}"

# Push with extended timeout handling (15 minutes each)
timeout 900 docker push ${ECR_URI}:${UNIQUE_HASH} || {
    echo "❌ Push of tagged version failed or timed out after 15 minutes"
    exit 1
}

echo "   Pushing latest version..."
timeout 900 docker push ${ECR_URI}:latest || {
    echo "❌ Push of latest version failed or timed out after 15 minutes"
    exit 1
}

# Step 5: Get current task definition
echo "📋 Retrieving current task definition..."
CURRENT_TASK_DEF=$(aws ecs describe-task-definition \
    --task-definition ${TASK_FAMILY} \
    --region ${AWS_REGION} \
    --query 'taskDefinition' \
    --output json)

# Step 6: Create new task definition with updated image
echo "📝 Creating new task definition..."
NEW_TASK_DEF=$(echo ${CURRENT_TASK_DEF} | jq --arg IMAGE "${ECR_URI}:${UNIQUE_HASH}" '
    .containerDefinitions[0].image = $IMAGE |
    del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .placementConstraints, .compatibilities, .registeredAt, .registeredBy)
')

# Register new task definition
echo "✍️ Registering new task definition..."
NEW_TASK_REVISION=$(aws ecs register-task-definition \
    --region ${AWS_REGION} \
    --cli-input-json "${NEW_TASK_DEF}" \
    --query 'taskDefinition.revision' \
    --output text)

echo "   New task definition: ${TASK_FAMILY}:${NEW_TASK_REVISION}"

# Step 7: Update ECS service
echo "🔄 Updating ECS service with new task definition..."
aws ecs update-service \
    --cluster ${ECS_CLUSTER} \
    --service ${ECS_SERVICE} \
    --task-definition ${TASK_FAMILY}:${NEW_TASK_REVISION} \
    --region ${AWS_REGION} \
    --query 'service.{ServiceName:serviceName,TaskDefinition:taskDefinition,Status:status}' \
    --output table

# Step 8: Wait for deployment to complete
echo "⏳ Waiting for service deployment to complete..."
aws ecs wait services-stable \
    --cluster ${ECS_CLUSTER} \
    --services ${ECS_SERVICE} \
    --region ${AWS_REGION}

# Step 9: Verify deployment
echo "✅ Verifying deployment..."
FINAL_STATUS=$(aws ecs describe-services \
    --cluster ${ECS_CLUSTER} \
    --services ${ECS_SERVICE} \
    --region ${AWS_REGION} \
    --query 'services[0].{Status:status,RunningCount:runningCount,DesiredCount:desiredCount,TaskDefinition:taskDefinition}' \
    --output table)

echo "${FINAL_STATUS}"

# Step 10: Clean up old images (optional)
echo "🧹 Cleaning up local Docker images..."
docker rmi ${ECR_REPOSITORY}:${UNIQUE_HASH} ${ECR_REPOSITORY}:latest ${ECR_URI}:${UNIQUE_HASH} ${ECR_URI}:latest 2>/dev/null || true

echo ""
echo "🎉 Deployment completed successfully!"
echo ""
echo "📊 Configuration Updates Applied:"
echo "   ✅ Historical data points: 100 → 1200 M5 candles"
echo "   ✅ Data retention: 2 hours → 5 days"
echo "   ✅ H1 backfill: Added automatic historical H1 data backfill on startup"
echo "   ✅ Expected H1 candles: 5-8 → 80-100 (immediate via backfill)"
echo ""
echo "🔍 Monitor the service:"
echo "   aws ecs describe-services --cluster ${ECS_CLUSTER} --services ${ECS_SERVICE} --region ${AWS_REGION}"
echo ""
echo "📈 After 2-4 hours of data collection, you should see 80-100 H1 candles in your TradingView charts!"
echo ""