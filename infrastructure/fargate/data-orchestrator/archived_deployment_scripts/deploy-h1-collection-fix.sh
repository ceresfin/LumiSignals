#!/bin/bash
# Fix H1 data collection conflict
# Usage: ./deploy-h1-collection-fix.sh

echo "Fixing H1 data collection conflict..."
echo "Issue: Regular M5 collection overwrites H1 backfill data"
echo "Solution: Only collect M5 in regular cycles, let H1 backfill handle H1 data"
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

echo "Building Docker image with H1 collection fix..."

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI

# Build
docker build \
    --build-arg VERSION="h1-fix-${UNIQUE_HASH}" \
    --build-arg BUILD_DATE="${BUILD_DATE}" \
    --build-arg COMMIT_SHA="${COMMIT_SHA}" \
    --build-arg CACHEBUST="$(date +%s)" \
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

# Update service
echo "Updating ECS service..."
aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE \
    --force-new-deployment \
    --region $AWS_REGION

echo ""
echo "H1 collection fix deployed!"
echo ""
echo "Changes:"
echo "  ✅ Regular collection now only collects M5 data"
echo "  ✅ H1 data handled exclusively by H1 backfill process"
echo "  ✅ H1 backfill data (500 candles) won't be overwritten"
echo "  ✅ H1 data persists for 5 days (fixed TTL)"
echo ""
echo "This ensures you'll consistently see 100+ H1 candles!"