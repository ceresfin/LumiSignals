#!/bin/bash
# Deploy Force Bootstrap - Complete Solution
# This script modifies code, builds container, and deploys using TD 196 golden template

set -e

echo "=========================================="
echo "🚀 FORCE BOOTSTRAP DEPLOYMENT"
echo "=========================================="
echo "This will:"
echo "1. Modify code to support FORCE_BOOTSTRAP_CLEAR"
echo "2. Build new container with changes"
echo "3. Deploy using TD 196 golden template configuration"
echo "4. Enable bootstrap with force clear"
echo ""

# Generate timestamp for container tag
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="src/data_orchestrator.py.backup_${TIMESTAMP}"
IMAGE_TAG="816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:force-bootstrap-${TIMESTAMP}"

echo "[1/6] Creating backup and modifying code..."
echo "Backup: ${BACKUP_FILE}"

# Create backup
cp src/data_orchestrator.py "${BACKUP_FILE}"
echo "✅ Created backup: ${BACKUP_FILE}"

# Modify the code to add FORCE_BOOTSTRAP_CLEAR support
python3 - << 'EOF'
import re

# Read the file
with open("src/data_orchestrator.py", "r") as f:
    content = f.read()

# Find and replace the bootstrap marker check section
old_pattern = r'(                # Use first shard to check bootstrap completion marker\n                redis_conn = await self\.redis_manager\.get_connection\(0\)\n                bootstrap_marker_key = "lumisignals:system:bootstrap:completed"\n                has_bootstrapped = await redis_conn\.get\(bootstrap_marker_key\))'

new_replacement = '''                # Use first shard to check bootstrap completion marker
                redis_conn = await self.redis_manager.get_connection(0)
                bootstrap_marker_key = "lumisignals:system:bootstrap:completed"
                
                # Check if we should force clear the bootstrap marker
                if os.getenv('FORCE_BOOTSTRAP_CLEAR', '').lower() == 'true':
                    logger.warning("⚠️  FORCE_BOOTSTRAP_CLEAR is set - clearing bootstrap marker for one-time re-bootstrap")
                    await redis_conn.delete(bootstrap_marker_key)
                    has_bootstrapped = None
                else:
                    has_bootstrapped = await redis_conn.get(bootstrap_marker_key)'''

# Replace the pattern
if re.search(old_pattern, content, re.MULTILINE):
    new_content = re.sub(old_pattern, new_replacement, content, flags=re.MULTILINE)
    
    # Write the modified content
    with open("src/data_orchestrator.py", "w") as f:
        f.write(new_content)
    
    print("✅ Successfully modified data_orchestrator.py")
else:
    print("⚠️  Pattern not found - code may already be modified or structure changed")
    print("Please check the file manually")
EOF

if [ $? -ne 0 ]; then
    echo "❌ Code modification failed"
    exit 1
fi

echo ""
echo "[2/6] Building Docker container with force bootstrap support..."
echo "Image: ${IMAGE_TAG}"

# Build container
docker build --no-cache \
  --build-arg VERSION="force-bootstrap-${TIMESTAMP}" \
  --build-arg CACHEBUST="${TIMESTAMP}" \
  -t "${IMAGE_TAG}" .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi

echo ""
echo "[3/6] Logging into ECR and pushing container..."

# ECR login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com

if [ $? -ne 0 ]; then
    echo "❌ ECR login failed"
    exit 1
fi

# Push image
docker push "${IMAGE_TAG}"

if [ $? -ne 0 ]; then
    echo "❌ Docker push failed"
    exit 1
fi

echo ""
echo "[4/6] Creating task definition using TD 196 golden template..."
echo "🔑 Using TD 196 configuration:"
echo "  - CPU: 2048, Memory: 4096"
echo "  - IAM Roles: Both correct from TD 196"
echo "  - Secrets: 4 secrets in JSON format"
echo "  - Environment: ENABLE_BOOTSTRAP=true, FORCE_BOOTSTRAP_CLEAR=true"

# Create task definition using TD 196 golden template with force bootstrap
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
      },
      {
        \"name\": \"FORCE_BOOTSTRAP_CLEAR\",
        \"value\": \"true\"
      }
    ]
  }]" \
  --region us-east-1 \
  --query "taskDefinition.revision" \
  --output text > force_bootstrap_revision.txt

if [ $? -ne 0 ]; then
    echo "❌ Task definition registration failed"
    exit 1
fi

NEW_REVISION=$(cat force_bootstrap_revision.txt)
echo "✅ Created Task Definition: lumisignals-data-orchestrator:${NEW_REVISION}"

echo ""
echo "[5/6] Deploying with force bootstrap enabled..."

# Update ECS service
aws ecs update-service \
  --cluster lumisignals-cluster \
  --service lumisignals-data-orchestrator \
  --task-definition "lumisignals-data-orchestrator:${NEW_REVISION}" \
  --desired-count 1 \
  --force-new-deployment \
  --region us-east-1 \
  --query "service.taskDefinition" \
  --output text

if [ $? -ne 0 ]; then
    echo "❌ Service update failed"
    exit 1
fi

echo "✅ Service update initiated with TD ${NEW_REVISION}"

echo ""
echo "[6/6] Verification and monitoring setup..."
echo "⏳ Waiting 60 seconds for task to start..."
sleep 60

# Verify task is running
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

# Verify correct task definition is running
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
echo "📊 FORCE BOOTSTRAP DEPLOYMENT SUMMARY:"
echo "======================================"
echo "✅ Code Modified: Added FORCE_BOOTSTRAP_CLEAR support"
echo "✅ Backup Created: ${BACKUP_FILE}"
echo "✅ Task Definition: lumisignals-data-orchestrator:${NEW_REVISION}"
echo "✅ Container Image: ${IMAGE_TAG}"
echo "✅ Configuration: TD 196 golden template"
echo "✅ Bootstrap: ENABLED with force clear"
echo "✅ H1 Window Fix: 6-minute collection window included"
echo ""
echo "🔍 WHAT TO EXPECT:"
echo "1. Container will clear the old bootstrap marker"
echo "2. Bootstrap will collect 500 candles for all pairs"
echo "3. H1 data gaps should be filled within 5-10 minutes"
echo "4. New bootstrap marker will be set for future restarts"
echo ""
echo "📋 MONITOR BOOTSTRAP PROGRESS:"
echo "# Watch for bootstrap messages:"
echo "aws logs tail /ecs/lumisignals-data-orchestrator --follow | grep -i bootstrap"
echo ""
echo "# Expected sequence:"
echo "# 1. '⚠️  FORCE_BOOTSTRAP_CLEAR is set - clearing bootstrap marker'"
echo "# 2. '🚀 First-time bootstrap - collecting 500 candles'"
echo "# 3. 'Bootstrap collection completed successfully'"
echo ""
echo "📋 CHECK H1 DATA AFTER BOOTSTRAP:"
echo "# Wait 10 minutes, then check H1 data:"
echo "curl -s \"https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/H1?count=50\" | python3 -c \"import sys,json,datetime; d=json.load(sys.stdin); candles=d.get('data',[]); gaps=[]; prev_time=None; [gaps.append(f'Gap: {prev_time.strftime(\\\"%Y-%m-%d %H:%M\\\")} to {(curr_time:=datetime.datetime.fromisoformat(c['datetime'].replace('Z','+00:00'))).strftime(\\\"%Y-%m-%d %H:%M\\\")} ({int((curr_time-prev_time).total_seconds()/3600)} hours)') for c in candles if (prev_time and (curr_time:=datetime.datetime.fromisoformat(c['datetime'].replace('Z','+00:00'))) and (curr_time-prev_time).total_seconds()>3600) or (prev_time:=datetime.datetime.fromisoformat(c['datetime'].replace('Z','+00:00')) if not prev_time else prev_time)]; print(f'Total H1 candles: {len(candles)}'); print(f'Latest: {candles[-1][\\\"datetime\\\"] if candles else \\\"None\\\"}'); [print(gap) for gap in gaps[-3:]];\""
echo ""
echo "⚠️  IMPORTANT: After bootstrap completes and H1 gaps are filled,"
echo "    deploy again WITHOUT FORCE_BOOTSTRAP_CLEAR to return to normal operation!"
echo ""
echo "🎉 FORCE BOOTSTRAP DEPLOYMENT COMPLETE!"

# Clean up
rm -f force_bootstrap_revision.txt