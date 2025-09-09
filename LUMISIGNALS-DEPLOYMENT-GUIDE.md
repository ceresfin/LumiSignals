# LumiSignals Deployment Guide
**The Complete ECS Golden Template System & Deployment Process**

## 🎯 Quick Reference

**✅ CURRENT STATUS (September 9, 2025)**:
- **Golden Template**: Task Definition 196 ✅ ACTIVE 
- **Container**: `iam-fix-20250909-131543` ✅ RUNNING
- **Status**: Comprehensive orchestrator active, stale trade cleanup working
- **Performance**: CPU 2048, Memory 4096 (high performance)
- **Secrets**: AWS Secrets Manager JSON format (Architecture Bible compliant)

## 🚀 Emergency Quick Deploy

### Hotfix (Use Current Golden Template)
```bash
# EMERGENCY: Switch to TD 196 (current golden template)
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:196 --desired-count 1 --force-new-deployment --region us-east-1
```

### Working Deployment Script
```bash
# Run the verified working deployment script
cd infrastructure/fargate/data-orchestrator
./deploy-correct-iam-role.bat
```

---

## 📊 Golden Template System

### Task Definition 196: The Optimal Configuration

**Why TD 196 is Golden**:
- ✅ **Correct IAM Roles**: Both task and execution roles fixed  
- ✅ **High Performance**: CPU 2048, Memory 4096 (4x more resources)
- ✅ **JSON Database Format**: Single `DATABASE_CREDENTIALS` secret
- ✅ **OANDA Secrets**: 3 individual OANDA secrets properly configured
- ✅ **Proven Working**: Currently running comprehensive orchestrator successfully

**Complete Configuration**:
```json
{
  "family": "lumisignals-data-orchestrator",
  "taskRoleArn": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-role",
  "executionRoleArn": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role",
  "cpu": "2048",
  "memory": "4096",
  "secrets": [
    {
      "name": "OANDA_API_KEY",
      "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::"
    },
    {
      "name": "OANDA_ACCOUNT_ID", 
      "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::"
    },
    {
      "name": "OANDA_ENVIRONMENT",
      "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::"
    },
    {
      "name": "DATABASE_CREDENTIALS",
      "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials"
    }
  ]
}
```

### Historical Context: Why We Needed TD 196

**The Problem**: 7+ consecutive ECS deployments (TD 188-194) silently failed due to IAM role issues
**The Discovery**: No single task definition had optimal configuration

| Task Definition | IAM Roles | Database Format | CPU/Memory | Status |
|----------------|-----------|----------------|------------|---------|
| TD 187 | ✅ Correct | ❌ Old (8 individual secrets) | ✅ High (2048/4096) | Good IAM, old secrets |
| TD 195 | ❌ Wrong execution role | ✅ JSON format | ❌ Low (256/512) | Good secrets, bad IAM |
| TD 191 | ❌ Wrong task role | ❌ Old format | ❌ Low | Bad overall |
| **TD 196** | **✅ Both correct** | **✅ JSON format** | **✅ High** | **✅ OPTIMAL** |

---

## 🔐 AWS Secrets Manager Configuration

### Required Secrets

#### 1. OANDA API Credentials
**Secret Name**: `lumisignals/oanda/api/credentials`  
**Format**: JSON
```json
{
  "api_key": "YOUR_OANDA_API_KEY",
  "account_id": "YOUR_OANDA_ACCOUNT_ID",
  "environment": "practice"
}
```

#### 2. Database Credentials  
**Secret Name**: `lumisignals/rds/postgresql/credentials`  
**Format**: JSON (Architecture Bible Standard)
```json
{
  "host": "lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com",
  "port": 5432,
  "dbname": "lumisignals", 
  "username": "lumisignals_user",
  "password": "SECURE_PASSWORD_HERE",
  "ssl": true
}
```

### Verification Commands
```bash
# Verify OANDA secret exists
aws secretsmanager get-secret-value --secret-id "lumisignals/oanda/api/credentials" --region us-east-1

# Verify Database secret exists  
aws secretsmanager get-secret-value --secret-id "lumisignals/rds/postgresql/credentials" --region us-east-1
```

---

## 🚀 Deployment Process

### Method 1: Use Working Script (Recommended)

**Location**: `infrastructure/fargate/data-orchestrator/deploy-correct-iam-role.bat`

**Features**:
- ✅ Silent failure prevention (5-step verification)
- ✅ IAM role verification  
- ✅ Task startup confirmation
- ✅ ECS service event monitoring
- ✅ Automatic cache clearing (4 methods)

**Usage**:
```bash
cd infrastructure/fargate/data-orchestrator
./deploy-correct-iam-role.bat
```

### Method 2: Manual AWS CLI Commands

```bash
# 1. Build and push container
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
IMAGE_TAG="816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:manual-${TIMESTAMP}"

docker build --no-cache --build-arg VERSION="manual-${TIMESTAMP}" --build-arg CACHEBUST="${TIMESTAMP}" -t "${IMAGE_TAG}" .
docker push "${IMAGE_TAG}"

# 2. Create task definition using TD 196 template
aws ecs register-task-definition \
--family lumisignals-data-orchestrator \
--task-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-role \
--execution-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role \
--network-mode awsvpc \
--requires-compatibilities FARGATE \
--cpu 2048 \
--memory 4096 \
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"${IMAGE_TAG}\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_CREDENTIALS\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials\"}]}]" \
--region us-east-1 --query "taskDefinition.revision" --output text

# 3. Deploy with verification
NEW_REVISION=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 --query "taskDefinition.revision" --output text)
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:${NEW_REVISION} --desired-count 1 --force-new-deployment --region us-east-1
```

---

## ✅ Critical Verification Steps

### 1. Pre-Deployment Validation
```bash
# Verify golden template hasn't changed
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:196 --region us-east-1 --query "taskDefinition.{taskRole:taskRoleArn,executionRole:executionRoleArn,cpu:cpu,memory:memory,secrets:length(containerDefinitions[0].secrets)}" --output json

# Expected output:
{
    "taskRole": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-role",
    "executionRole": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role", 
    "cpu": "2048",
    "memory": "4096",
    "secrets": 4
}
```

### 2. Post-Deployment Verification  
```bash
# 1. Verify task definition created
NEW_REVISION=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 --query "taskDefinition.revision" --output text)
echo "New revision: ${NEW_REVISION}"

# 2. Verify 4 secrets configured
SECRETS_COUNT=$(aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:${NEW_REVISION} --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text)
echo "Secrets count: ${SECRETS_COUNT}" # Should be 4

# 3. Verify correct IAM roles
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:${NEW_REVISION} --region us-east-1 --query "taskDefinition.{taskRole:taskRoleArn,executionRole:executionRoleArn}" --output json

# 4. CRITICAL: Verify new task actually starts
sleep 60
TASK_ARN=$(aws ecs list-tasks --cluster lumisignals-cluster --service-name lumisignals-data-orchestrator --region us-east-1 --query "taskArns[0]" --output text)
if [ "$TASK_ARN" = "None" ]; then
    echo "❌ CRITICAL ERROR: No running task found"
    aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:5]" --output table
    exit 1
fi

# 5. Verify new task definition is running
RUNNING_TD=$(aws ecs describe-tasks --cluster lumisignals-cluster --tasks ${TASK_ARN} --region us-east-1 --query "tasks[0].taskDefinitionArn" --output text)
echo "Running task definition: ${RUNNING_TD}"
```

### 3. Application Health Check
```bash
# Check CloudWatch logs for successful initialization
STREAM_NAME=$(aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text)

# Look for successful initialization messages
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "${STREAM_NAME}" --region us-east-1 --query "events[-20:].message" --output text | grep -E "Comprehensive orchestrator completed successfully|Account data collection.*completed"

# Expected messages:
# - "DEBUG: Comprehensive orchestrator completed successfully"
# - "✅ OANDA API authentication: Working with 28 currency pairs"
# - "✅ Database cleanup active"
```

---

## 🚨 Troubleshooting

### Common Issues & Solutions

#### 1. "ECS was unable to assume the role" Error
**Cause**: Wrong IAM role name  
**Solution**: Use correct roles from TD 196
```bash
# Correct roles:
# Task Role: arn:aws:iam::816945674467:role/lumisignals-ecs-task-role
# Execution Role: arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role
```

#### 2. "Illegal header value b'Bearer '" Error  
**Cause**: Missing OANDA secrets
**Solution**: Verify OANDA secrets exist and are properly formatted

#### 3. Task Definition Created But Task Won't Start
**Cause**: Silent failure - check ECS service events
**Solution**: 
```bash
aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:10]" --output table
```

#### 4. Database Connection Issues
**Cause**: Wrong database credentials format
**Solution**: Ensure `DATABASE_CREDENTIALS` is single JSON secret (not 8 individual fields)

#### 5. Comprehensive Orchestrator Not Initializing
**Cause**: Low resources or credential parsing issues  
**Solution**: Ensure CPU 2048, Memory 4096 and check logs for "DEBUG: Parsing DATABASE_CREDENTIALS JSON"

### Quick Fixes

```bash
# Emergency rollback to known working state
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:196 --desired-count 1 --force-new-deployment --region us-east-1

# Force service restart (if task stuck)
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 0 --region us-east-1
sleep 30  
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 1 --region us-east-1
```

---

## 📈 Production Status

### Current System Status (September 9, 2025)
```bash
✅ Task Definition 196: ACTIVE
✅ Comprehensive orchestrator: Initializing successfully  
✅ Account data collection: "Comprehensive orchestrator completed successfully"
✅ OANDA API: Working with 28 currency pairs
✅ Database cleanup: Automated stale trade removal active
✅ High performance: CPU 2048, Memory 4096
✅ Secrets format: Architecture Bible JSON compliance
✅ Deployment verification: Silent failure prevention active
```

### Architecture Compliance
- ✅ Single OANDA API connection maintained
- ✅ Fargate → Redis → PostgreSQL → pipstop.org pipeline active
- ✅ Comprehensive data orchestrator with cleanup capabilities  
- ✅ AWS Secrets Manager JSON format for all credentials
- ✅ Production-ready with full monitoring and verification

### Success Metrics
- **Deployments**: 19 total iterations documented
- **Silent Failures Prevented**: 1 execution role issue caught immediately
- **Performance Improvement**: 4x more CPU/Memory than recent deployments  
- **Cleanup Success**: Stale trade 1581 automated removal active
- **System Stability**: No manual intervention required

---

## 📚 Additional Documentation

- **Architecture Bible**: Complete system documentation in `THE_LUMISIGNALS_ARCHITECTURE_BIBLE.md`
- **Working Script**: `infrastructure/fargate/data-orchestrator/deploy-correct-iam-role.bat`
- **Detailed Process**: `infrastructure/fargate/data-orchestrator/container-deployment-script.md`
- **GitHub Commits**: `da791b4` (infrastructure) + `c22f6e1` (documentation)

---

## 🎯 Quick Commands Reference

```bash
# Check current running task definition
aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].taskDefinition" --output text

# Get latest logs
STREAM_NAME=$(aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text)
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "${STREAM_NAME}" --region us-east-1 --query "events[-10:].message" --output text

# Emergency hotfix to TD 196
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:196 --desired-count 1 --force-new-deployment --region us-east-1

# Verify secrets exist
aws secretsmanager list-secrets --region us-east-1 --query "SecretList[?contains(Name, 'lumisignals')].Name" --output table
```

---

**Last Updated**: September 9, 2025  
**Golden Template**: Task Definition 196 ✅ PRODUCTION ACTIVE  
**Status**: Comprehensive orchestrator running, stale trade cleanup working  
**Next Steps**: Monitor pipstop.org for trade 1581 cleanup, implement institutional overlays

---

*This guide documents the complete journey from silent deployment failures through the creation of the optimal Task Definition 196 golden template. All procedures have been tested in production and verified working.*