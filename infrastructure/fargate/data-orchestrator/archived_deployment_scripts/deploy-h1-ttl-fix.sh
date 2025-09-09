#!/bin/bash
# Fix H1 data TTL issue - increase Redis TTL
# Usage: ./deploy-h1-ttl-fix.sh

echo "Fixing H1 data TTL issue..."
echo "Current issue: H1 data expires after 5 minutes (300s)"
echo "Solution: Increase REDIS_TTL_SECONDS to 432000 (5 days)"
echo ""

# Configuration
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="816945674467"
ECS_CLUSTER="lumisignals-cluster"
ECS_SERVICE="lumisignals-data-orchestrator"
TASK_FAMILY="lumisignals-data-orchestrator"

# Get current task definition
echo "Fetching current task definition..."
CURRENT_TASK_DEF=$(aws ecs describe-task-definition --task-definition $TASK_FAMILY --region $AWS_REGION --query 'taskDefinition' --output json)

# Update REDIS_TTL_SECONDS from 300 to 432000 (5 days)
echo "Updating REDIS_TTL_SECONDS to 432000 (5 days)..."
UPDATED_TASK_DEF=$(echo $CURRENT_TASK_DEF | jq '.containerDefinitions[0].environment |= map(if .name == "REDIS_TTL_SECONDS" then .value = "432000" else . end)')

# Remove fields that can't be in registration
UPDATED_TASK_DEF=$(echo $UPDATED_TASK_DEF | jq 'del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)')

# Save to file
echo "$UPDATED_TASK_DEF" > ttl-fix-task-def.json

# Register new task definition
echo "Registering updated task definition..."
NEW_REVISION=$(aws ecs register-task-definition --cli-input-json file://ttl-fix-task-def.json --region $AWS_REGION --query 'taskDefinition.revision' --output text)

echo "New task definition revision: $NEW_REVISION"

# Update service
echo "Updating ECS service..."
aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE \
    --task-definition "${TASK_FAMILY}:${NEW_REVISION}" \
    --force-new-deployment \
    --region $AWS_REGION

# Clean up
rm -f ttl-fix-task-def.json

echo ""
echo "TTL fix deployed!"
echo ""
echo "Changes:"
echo "  ✅ REDIS_TTL_SECONDS: 300 → 432000 (5 minutes → 5 days)"
echo "  ✅ H1 historical data will now persist for 5 days"
echo "  ✅ Service is restarting with new configuration"
echo ""
echo "This will ensure H1 data doesn't disappear after 5 minutes."
echo ""
echo "Monitor deployment:"
echo "aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE --region $AWS_REGION"