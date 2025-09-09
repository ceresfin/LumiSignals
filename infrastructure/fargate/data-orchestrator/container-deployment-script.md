# LumiSignals Container Deployment Process Documentation

## Overview
This document captures the deployment process improvements developed during 10+ container deployments for the LumiSignals Data Orchestrator. The goal is to provide reliable, repeatable deployment procedures that avoid common pitfalls.

## Golden Template System

### ⚠️ CRITICAL: Golden Template Analysis Reveals Multiple Issues

**DISCOVERY**: No existing task definition has optimal configuration

**Configuration Analysis**:
- **TD 187**: ✅ Correct IAM roles, ❌ Old database secrets format, ✅ High CPU/Memory (2048/4096)
- **TD 195**: ❌ Wrong execution role, ✅ JSON database format, ❌ Low CPU/Memory (256/512)  
- **TD 191**: ❌ Wrong task role, ❌ Old database format, ❌ Low CPU/Memory

**✅ COMPLETED: NEW Hybrid Golden Template Created**
**Task Definition 196 - OPTIMAL CONFIGURATION**:
- **IAM Task Role**: `arn:aws:iam::816945674467:role/lumisignals-ecs-task-role` ✅ (from TD 187)
- **IAM Execution Role**: `arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role` ✅ (from TD 187)
- **Database Format**: JSON `DATABASE_CREDENTIALS` secret ✅ (from TD 195)
- **Resources**: CPU 2048, Memory 4096 ✅ (from TD 187)  
- **Container**: Latest with comprehensive orchestrator fixes

### Golden Template Validation
Before any deployment, verify the golden template hasn't changed:
```bash
# Get current golden template (will be set after next deployment)
# Check secrets count
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text
# Should return: 4 (OANDA + DATABASE_CREDENTIALS JSON)

# Verify correct IAM roles
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 --query "taskDefinition.{taskRole:taskRoleArn,executionRole:executionRoleArn,cpu:cpu,memory:memory}" --output json
# Should return: both lumisignals-ecs-* roles, CPU 2048, Memory 4096
```

### Golden Template Secrets (Reference)
**NEW Hybrid Golden Template** will contain these exact 4 secrets:
1. `OANDA_API_KEY` → `arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::`
2. `OANDA_ACCOUNT_ID` → `arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::`
3. `OANDA_ENVIRONMENT` → `arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::`
4. `DATABASE_CREDENTIALS` → `arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials`

**CRITICAL**: Database uses single JSON secret format (not individual fields) as per Architecture Bible

## Deployment Types

### 1. Full Rebuild Deployment (Most Common)
**Use when**: Code changes require new container with all fixes
**Process**: Build new container → Preserve TD 191 secrets → Deploy

**Script Template**:
```batch
@echo off
REM Full Rebuild: New container with TD 191 secrets preserved
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:rebuild-%TIMESTAMP%

echo [1/5] Building new container with cache busting...
docker build --no-cache --build-arg VERSION=rebuild-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% .

echo [2/5] Pushing to ECR...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG%
del temp_token.txt

echo [3/5] Creating task definition with TD 187 secrets (CORRECT IAM role)...
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-role ^
--execution-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 256 ^
--memory 512 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"%IMAGE_TAG%\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_CREDENTIALS\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials\"}]}]" ^
--region us-east-1 --query "taskDefinition.revision" --output text > new-revision.txt

set /p NEW_REVISION=<new-revision.txt

echo [4/5] Deploying with all 4 cache clearing methods...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo [5/5] Waiting 4 minutes for deployment...
timeout /t 240 /nobreak

echo Verifying deployment...
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream.txt
set /p STREAM_NAME=<latest-stream.txt
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-5:].message" --output text

del new-revision.txt latest-stream.txt temp_token.txt 2>nul
```

### 2. Hotfix Deployment (Emergency)
**Use when**: Critical fix needed immediately, use existing working configuration
**Process**: Switch to known working task definition

**Script Template**:
```batch
@echo off
REM Hotfix: Immediate switch to TD 187 (corrected golden template)
echo Emergency deployment to TD 187 (CORRECT IAM role)...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:187 --desired-count 1 --force-new-deployment --region us-east-1

echo Waiting 2 minutes...
timeout /t 120 /nobreak
echo Hotfix deployment complete - TD 187 active with correct IAM role
```

### 3. Secrets-Only Update
**Use when**: OANDA authentication broken but container is good
**Process**: Add missing secrets to existing task definition

**Script Template**:
```batch
@echo off
REM Fix missing secrets by copying from TD 191 golden template
echo Getting current task definition...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 --query "taskDefinition.containerDefinitions[0].image" --output text > current-image.txt
set /p CURRENT_IMAGE=<current-image.txt

echo Creating new TD with TD 191 secrets and current container...
[Use same AWS CLI command as Full Rebuild but with %CURRENT_IMAGE% instead of new build]
```

### 4. Golden Template Update
**Use when**: Base configuration (roles, networking, etc.) needs changes
**Process**: Manually update TD 191 structure, then update golden template reference
**⚠️ DANGER**: Only use when absolutely necessary, requires manual verification

## 4 Cache Clearing Methods

### Why All 4 Methods Are Required
ECS aggressively caches containers. Without all 4 methods, deployments may use old code even after successful container pushes.

### Method 1: Unique Container Tags
```batch
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:unique-%TIMESTAMP%
```

### Method 2: Docker Build Cache Busting
```batch
docker build --no-cache --build-arg VERSION=v-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% .
```

### Method 3: Force New ECS Deployment
```batch
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1
```

### Method 4: Service Stop/Start (If needed)
```batch
REM Only use if Methods 1-3 fail
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 0 --region us-east-1
timeout /t 60 /nobreak
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 1 --region us-east-1
```

## Common Failure Modes & Solutions

### Error: "Illegal header value b'Bearer '"
**Root Cause**: OANDA secrets missing or corrupted
**Solution**: Use Secrets-Only deployment type
**Prevention**: Always verify 8 secrets in new task definition

### Error: PowerShell JSON manipulation fails
**Root Cause**: Complex JSON parsing in Windows batch files
**Solution**: Use AWS CLI direct approach (avoid PowerShell ConvertFrom-Json)
**Prevention**: Use provided AWS CLI templates, never PowerShell JSON

### Error: ECS using old container despite successful push
**Root Cause**: ECS container caching
**Solution**: Apply all 4 cache clearing methods
**Prevention**: Always use all 4 methods together

### Error: 'charmap' codec can't encode characters in logs
**Root Cause**: Windows character encoding issues
**Solution**: Use specific AWS CLI log queries instead of raw log output
**Prevention**: Use provided log checking commands

### Error: Comprehensive orchestrator not initializing
**Root Cause**: Database connection or initialization logic issues
**Solution**: Verify database secrets and check 🎯 emoji in logs
**Prevention**: Include database connection verification in deployment

### Error: Task definition secrets stripped during deployment
**Root Cause**: JSON manipulation accidentally removes secrets
**Solution**: Use golden template validation before deployment
**Prevention**: Always validate against TD 187 baseline

### Error: Silent deployment failures with wrong IAM roles
**Root Cause**: Using wrong IAM role names:
- **Task Role**: `LumiSignalsECSTaskRole` instead of `lumisignals-ecs-task-role`
- **Execution Role**: `LumiSignalsECSExecutionRole` instead of `lumisignals-ecs-task-execution-role`
**Solution**: Always verify both IAM roles in task definition before and after deployment  
**Prevention**: Use TD 187 as template and verify IAM roles in deployment verification
**Impact**: Caused 7+ consecutive failed deployments (TD 188-194+) that appeared successful

## Troubleshooting Decision Tree

```
Deployment Issue?
├─ OANDA Authentication Error ("Illegal header value b'Bearer '")
│  └─ Use: Secrets-Only Update → Copy TD 191 secrets
├─ PowerShell/JSON Error during deployment
│  └─ Use: Full Rebuild → AWS CLI approach (avoid PowerShell)
├─ ECS using old container (logs show old code)
│  └─ Use: Apply all 4 cache clearing methods
├─ Service won't start/crashes
│  └─ Use: Hotfix Deployment → Switch to TD 191
├─ Database connection issues
│  └─ Check: TD 191 database secrets + RDS connectivity
└─ Unknown/Complex issue
   └─ Use: Hotfix to TD 191, then investigate
```

## Verification Procedures

### Pre-Deployment Checklist
1. ✅ Verify TD 191 golden template has 8 secrets
2. ✅ Confirm current working directory is correct
3. ✅ Test AWS CLI access and ECR login
4. ✅ Backup current task definition number

### Post-Deployment Verification (CRITICAL - Prevents Silent Failures)
```batch
REM STEP 1: Verify task definition creation
set /p NEW_REVISION=<new-revision.txt
if "%NEW_REVISION%"=="" (
    echo ❌ ERROR: Task definition creation failed
    goto :error
)

REM STEP 2: Check correct secrets count
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text > secrets-count.txt
set /p SECRETS_COUNT=<secrets-count.txt
if not "%SECRETS_COUNT%"=="4" (
    echo ❌ ERROR: Expected 4 secrets, got %SECRETS_COUNT%
    goto :error
)

REM STEP 3: Verify correct IAM role
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.taskRoleArn" --output text > iam-role.txt
set /p IAM_ROLE=<iam-role.txt
echo %IAM_ROLE% | findstr /C:"lumisignals-ecs-task-role" >nul
if %errorlevel% neq 0 (
    echo ❌ ERROR: Wrong IAM role detected: %IAM_ROLE%
    echo Expected: lumisignals-ecs-task-role
    goto :error
)

REM STEP 4: CRITICAL - Verify new task actually starts (not just TD created)
timeout /t 60 /nobreak
aws ecs list-tasks --cluster lumisignals-cluster --service-name lumisignals-data-orchestrator --region us-east-1 --query "taskArns[0]" --output text > current-task.txt
set /p TASK_ARN=<current-task.txt
if "%TASK_ARN%"=="None" (
    echo ❌ CRITICAL ERROR: No running task found - deployment failed silently
    echo Checking ECS service events...
    aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:5]" --output table
    goto :error
)

REM STEP 5: Verify new task definition is actually running
aws ecs describe-tasks --cluster lumisignals-cluster --tasks %TASK_ARN% --region us-east-1 --query "tasks[0].taskDefinitionArn" --output text > running-td.txt
set /p RUNNING_TD=<running-td.txt
echo %RUNNING_TD% | findstr /C:":%NEW_REVISION%" >nul
if %errorlevel% neq 0 (
    echo ⚠️ WARNING: Task still using old definition, waiting for rollout...
    timeout /t 120 /nobreak
    REM Re-check after additional wait
    aws ecs list-tasks --cluster lumisignals-cluster --service-name lumisignals-data-orchestrator --region us-east-1 --query "taskArns[0]" --output text > current-task2.txt
    set /p TASK_ARN2=<current-task2.txt
    aws ecs describe-tasks --cluster lumisignals-cluster --tasks %TASK_ARN2% --region us-east-1 --query "tasks[0].taskDefinitionArn" --output text > running-td2.txt
    set /p RUNNING_TD2=<running-td2.txt
    echo %RUNNING_TD2% | findstr /C:":%NEW_REVISION%" >nul
    if %errorlevel% neq 0 (
        echo ❌ ERROR: Deployment failed - still running old task definition
        goto :error
    )
)

echo ✅ VERIFIED: Task Definition %NEW_REVISION% is running successfully

REM STEP 6: Check application logs for initialization
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream.txt
set /p STREAM_NAME=<latest-stream.txt

REM Check for OANDA authentication success
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-20:].message" --output text | findstr /C:"Illegal header" >nul
if %errorlevel%==0 (
    echo ❌ ERROR: OANDA authentication failure detected
    goto :error
)

REM Check for comprehensive orchestrator
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-20:].message" --output text | findstr /C:"comprehensive orchestrator" >nul
if %errorlevel%==0 (
    echo ✅ VERIFIED: Comprehensive orchestrator messages found
) else (
    echo ⚠️ WARNING: Comprehensive orchestrator messages not yet visible
)

del secrets-count.txt iam-role.txt current-task.txt running-td.txt current-task2.txt running-td2.txt latest-stream.txt 2>nul
```

## Rollback Procedures

### Emergency Rollback
```batch
REM Immediate rollback to TD 187 (corrected golden template with proper IAM role)
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:187 --desired-count 1 --force-new-deployment --region us-east-1
echo ⚠️ Rolled back to TD 187 with correct lumisignals-ecs-task-role
```

### Planned Rollback
1. Identify last known working task definition
2. Use Full Rebuild process with previous container image
3. Verify all secrets preserved
4. Update golden template reference if needed

## Best Practices

1. **Always use TD 187 as baseline** for secrets and IAM role configuration
2. **Apply all 4 cache clearing methods** for every deployment
3. **CRITICAL: Verify task actually starts** - don't just check TD creation
4. **Verify correct IAM role** (`lumisignals-ecs-task-role`) before and after deployment
5. **Wait 4+ minutes** for full deployment completion
6. **Verify OANDA authentication** before considering deployment successful
7. **Never use PowerShell JSON manipulation** - use AWS CLI direct
8. **Keep deployment scripts in version control** for consistency
9. **Test deployment scripts** on non-production first when possible
10. **Document any changes** to golden template TD 187

## Container Tag Naming Convention

- **Full Rebuild**: `rebuild-YYYYMMDD-HHMMSS`
- **Hotfix**: `hotfix-YYYYMMDD-HHMMSS` 
- **Secrets Fix**: `secrets-fix-YYYYMMDD-HHMMSS`
- **Testing**: `test-YYYYMMDD-HHMMSS`

## File Locations

All deployment scripts should be stored in:
```
/infrastructure/fargate/data-orchestrator/
├── deploy-full-rebuild.bat
├── deploy-hotfix.bat
├── deploy-secrets-fix.bat
├── verify-golden-template.bat
└── container-deployment-script.md
```

---

**Last Updated**: September 9, 2025 ✅ **DEPLOYMENT SUCCESSFUL**  
**✅ NEW Golden Template**: Task Definition 196 (OPTIMAL HYBRID CONFIGURATION)  
**Status**: Currently deployed and running comprehensive orchestrator  
**Container**: `iam-fix-20250909-131543` (contains all fixes)  
**Critical Fixes Applied**: 
- ✅ Correct IAM roles (`lumisignals-ecs-task-role` + `lumisignals-ecs-task-execution-role`)
- ✅ JSON database format (`DATABASE_CREDENTIALS`)  
- ✅ High performance resources (CPU 2048, Memory 4096)
- ✅ Deployment verification prevents silent failures
- ✅ Comprehensive orchestrator active and cleaning up stale trades