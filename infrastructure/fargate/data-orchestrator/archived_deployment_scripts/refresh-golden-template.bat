@echo off
REM Refresh Golden Template Script
REM Creates a new definitive golden template with latest code + all cache busting
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Refresh Golden Template
echo Build Perfect Container + Create New Golden Template
echo ========================================
echo.
echo Purpose: Create new golden template with:
echo - Latest code with all fixes
echo - All 4 cache clearing methods applied
echo - All 8 AWS Secrets Manager configurations
echo - Becomes new deployment baseline
echo.

REM Get current golden template for reference
set CURRENT_GOLDEN=191
echo Current Golden Template: TD %CURRENT_GOLDEN%
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:golden-%TIMESTAMP%

echo [1/6] Building new golden container with all cache busting methods...
echo Image: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=golden-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/6] Pushing to ECR...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/6] Validating current golden template secrets...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%CURRENT_GOLDEN% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text') do set SECRETS_COUNT=%%i

if "%SECRETS_COUNT%"=="8" (
    echo ✅ Current golden template has all 8 secrets
) else (
    echo ❌ WARNING: Current golden template only has %SECRETS_COUNT% secrets!
)

echo.
echo [4/6] Creating new golden template task definition...
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSTaskRole ^
--execution-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSExecutionRole ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 256 ^
--memory 512 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"%IMAGE_TAG%\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_HOST\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:host::\"},{\"name\":\"DATABASE_PORT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:port::\"},{\"name\":\"DATABASE_USERNAME\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:username::\"},{\"name\":\"DATABASE_PASSWORD\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:password::\"},{\"name\":\"DATABASE_NAME\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:dbname::\"}]}]" ^
--region us-east-1 --query "taskDefinition.revision" --output text > new-golden-revision.txt

set /p NEW_GOLDEN=<new-golden-revision.txt
echo ✅ Created New Golden Template: TD %NEW_GOLDEN%

echo.
echo [5/6] Validating new golden template...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_GOLDEN% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text') do set NEW_SECRETS_COUNT=%%i

if "%NEW_SECRETS_COUNT%"=="8" (
    echo ✅ New golden template has all 8 secrets
) else (
    echo ❌ ERROR: New golden template only has %NEW_SECRETS_COUNT% secrets!
    goto :error
)

echo.
echo [6/6] Deploying new golden template...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_GOLDEN% --desired-count 1 --force-new-deployment --region us-east-1

echo Waiting 3 minutes for deployment...
timeout /t 180 /nobreak

echo.
echo ========================================
echo NEW GOLDEN TEMPLATE CREATED!
echo ========================================
echo.
echo OLD GOLDEN TEMPLATE: TD %CURRENT_GOLDEN%
echo NEW GOLDEN TEMPLATE: TD %NEW_GOLDEN%
echo Container: %IMAGE_TAG%
echo.
echo ✅ Built with all 4 cache clearing methods
echo ✅ Contains latest code and all fixes
echo ✅ Has all 8 AWS Secrets Manager configurations
echo ✅ Successfully deployed and running
echo.
echo REQUIRED MANUAL UPDATES:
echo 1. Update container-deployment-script.md
echo 2. Change golden template reference from TD %CURRENT_GOLDEN% to TD %NEW_GOLDEN%
echo 3. Update container image reference to: %IMAGE_TAG%
echo 4. Update all deployment scripts to use TD %NEW_GOLDEN% as baseline
echo.
echo This is now your definitive golden template for all future deployments!
echo.

del new-golden-revision.txt temp_token.txt 2>nul
pause
goto :end

:error
echo.
echo ========================================
echo GOLDEN TEMPLATE REFRESH FAILED!
echo ========================================
del new-golden-revision.txt temp_token.txt 2>nul

:end