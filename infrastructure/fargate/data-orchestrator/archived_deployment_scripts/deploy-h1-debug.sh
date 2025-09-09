#!/bin/bash
# Deploy H1 backfill with debug logging
# Usage: ./deploy-h1-debug.sh

echo "Deploying H1 backfill with enhanced debug logging..."
echo "This will help diagnose why only 1 H1 candle is returned"
echo ""

# Configuration
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="816945674467"
ECR_REPOSITORY="lumisignals-data-orchestrator"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
ECS_CLUSTER="lumisignals-cluster"
ECS_SERVICE="lumisignals-data-orchestrator"

# Generate unique hash
COMMIT_SHA=$(git rev-parse --short HEAD)
BUILD_DATE=$(date +"%Y%m%d-%H%M%S")
UNIQUE_HASH="${COMMIT_SHA}-${BUILD_DATE}"

echo "Building Docker image with debug logging..."

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI

# Build and push
docker build \
    --build-arg VERSION="h1-debug-${UNIQUE_HASH}" \
    --build-arg BUILD_DATE="${BUILD_DATE}" \
    --build-arg COMMIT_SHA="${COMMIT_SHA}" \
    --platform linux/amd64 \
    -t ${ECR_REPOSITORY}:${UNIQUE_HASH} \
    -t ${ECR_REPOSITORY}:latest \
    .

# Tag and push
docker tag ${ECR_REPOSITORY}:${UNIQUE_HASH} ${ECR_URI}:${UNIQUE_HASH}
docker tag ${ECR_REPOSITORY}:latest ${ECR_URI}:latest

echo "Pushing to ECR..."
docker push ${ECR_URI}:${UNIQUE_HASH}
docker push ${ECR_URI}:latest

# Force new deployment
echo "Updating ECS service..."
aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE \
    --force-new-deployment \
    --region $AWS_REGION

echo ""
echo "Deployment initiated! Debug logging added for:"
echo "  - OANDA API H1 requests (date ranges)"
echo "  - OANDA API H1 responses (candle counts)"
echo "  - H1 backfill process for each currency pair"
echo ""
echo "Monitor logs with:"
echo "aws logs tail /ecs/lumisignals-data-orchestrator --region us-east-1 --follow | grep -E 'H1|backfill'"