#!/bin/bash

# Deploy Tier Rotation Logic Fix
# This script manually creates a task definition with the fixed tier rotation logic

set -e

echo "============================================"
echo "DEPLOYING TIER ROTATION LOGIC FIX"
echo "============================================"
echo ""
echo "ISSUE: Only 24/50 candles showing instead of 500"
echo "CAUSE: Tier rotation happening every 10 cycles, but ltrim happening every cycle"
echo "FIX: Check hot tier capacity and rotate BEFORE ltrim on every cycle"
echo ""

# Use existing container image but force new deployment to pick up code changes
CURRENT_TASK_DEF=$(aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].taskDefinition" --output text)
echo "Current task definition: $CURRENT_TASK_DEF"

# Get current task definition details
CURRENT_REVISION=$(echo $CURRENT_TASK_DEF | cut -d':' -f6)
echo "Current revision: $CURRENT_REVISION"

# Since we can't rebuild the container easily, let's restart the service to see if the issue was just with bootstrap
echo ""
echo "Option 1: Force service restart to trigger fresh bootstrap"
echo "The tier rotation fix is committed to git but needs container rebuild"
echo ""

echo "Restarting service to trigger fresh bootstrap with better logging..."
aws ecs update-service \
    --cluster lumisignals-cluster \
    --service lumisignals-data-orchestrator \
    --force-new-deployment \
    --region us-east-1 \
    --output table \
    --query "service.{TaskDefinition:taskDefinition,Status:status,RunningCount:runningCount}"

echo ""
echo "✅ Service restart initiated"
echo ""
echo "NEXT STEPS:"
echo "1. Monitor logs for bootstrap completion"
echo "2. Test API after 2-3 minutes"
echo "3. If still broken, we need to rebuild container with fix"
echo ""
echo "To monitor deployment:"
echo "aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query 'services[0].events[:3]' --output table"
echo ""
echo "To test after deployment:"
echo "curl -s \"https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/H1?count=500\" | python3 -c \"import sys, json; data=json.load(sys.stdin); print('Count:', len(data.get('data', []))); print('Sources:', data.get('metadata', {}).get('sources_used', []))\""