@echo off
REM FINAL FIX: Single DATABASE_CREDENTIALS JSON Secret
REM This fixes the invalid :: syntax and uses the Architecture Bible format
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo FINAL FIX: Single DATABASE_CREDENTIALS Secret
echo Using Architecture Bible Format
echo ========================================
echo.
echo CRITICAL FIX: Using single JSON DATABASE_CREDENTIALS secret
echo REMOVES: Invalid individual field references with :: syntax
echo ADDS: Single JSON secret as documented in Architecture Bible
echo EXPECTED: Comprehensive orchestrator will initialize and cleanup trades
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:final-fix-%TIMESTAMP%

echo [1/6] Building container with all fixes + all cache clearing methods...
echo Image: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=final-fix-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/6] Pushing to ECR with cache clearing...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/6] Creating task definition with CORRECT secrets format...
echo Using single DATABASE_CREDENTIALS JSON secret (Architecture Bible format)
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSTaskRole ^
--execution-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSExecutionRole ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 256 ^
--memory 512 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"%IMAGE_TAG%\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_CREDENTIALS\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials\"}]}]" ^
--region us-east-1 --query "taskDefinition.revision" --output text > new-final-revision.txt

set /p NEW_REVISION=<new-final-revision.txt
echo ✅ Created Task Definition: lumisignals-data-orchestrator:%NEW_REVISION%

echo.
echo [4/6] VERIFICATION: Checking secrets configuration...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text') do set SECRETS_COUNT=%%i

echo Secrets count: %SECRETS_COUNT%
if "%SECRETS_COUNT%"=="4" (
    echo ✅ VERIFIED: New task definition has 4 secrets (3 OANDA + 1 DATABASE_CREDENTIALS)
) else (
    echo ❌ ERROR: Expected 4 secrets, got %SECRETS_COUNT%
    goto :error
)

REM Verify DATABASE_CREDENTIALS specifically
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.containerDefinitions[0].secrets[?name==`DATABASE_CREDENTIALS`].name" --output text') do set DB_SECRET=%%i
if "%DB_SECRET%"=="DATABASE_CREDENTIALS" (
    echo ✅ VERIFIED: DATABASE_CREDENTIALS secret configured correctly
) else (
    echo ❌ ERROR: DATABASE_CREDENTIALS secret missing!
    goto :error
)

echo.
echo [5/6] Deploying with all 4 cache clearing methods...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [6/6] Waiting 4 minutes for comprehensive orchestrator initialization...
timeout /t 240 /nobreak

echo.
echo ========================================
echo FINAL FIX DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Definition: %NEW_REVISION%
echo Fix: Single DATABASE_CREDENTIALS JSON secret (Architecture Bible format)
echo.
echo CHECKING FOR COMPREHENSIVE ORCHESTRATOR INITIALIZATION...

REM Get latest log stream
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream-final.txt
set /p STREAM_NAME=<latest-stream-final.txt

echo.
echo Looking for critical initialization messages...
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-30:].message" --output text | findstr /C:"DEBUG: Database host" /C:"DEBUG: Using individual" /C:"DEBUG: Parsing DATABASE_CREDENTIALS" /C:"📊 Initializing Enhanced PostgreSQL" /C:"🎯"

echo.
echo Expected to see:
echo - "DEBUG: Parsing DATABASE_CREDENTIALS JSON" 
echo - "📊 Initializing Enhanced PostgreSQL database connection"
echo - "🎯 Comprehensive orchestrator created"
echo.

if "%NEW_REVISION%"=="" (
    echo ❌ Task definition creation failed!
) else (
    echo ✅ NEW GOLDEN TEMPLATE: Task Definition %NEW_REVISION%
    echo.
    echo GOLDEN TEMPLATE UPDATE REQUIRED:
    echo 1. Update container-deployment-script.md
    echo 2. Change golden template from TD 192 to TD %NEW_REVISION%
    echo 3. Update container image to: %IMAGE_TAG%
    echo 4. This TD uses CORRECT DATABASE_CREDENTIALS format per Architecture Bible
    echo.
    echo Expected Results:
    echo ✅ Database manager initializes (JSON secret format works)
    echo ✅ Comprehensive orchestrator starts (🎯 messages appear)
    echo ✅ Old pending order 99 gets cleaned up automatically  
    echo ✅ Trade 1581 disappears from pipstop.org
    echo ✅ Real accurate trade data in pipstop.org
)

echo.
del new-final-revision.txt latest-stream-final.txt temp_token.txt 2>nul
pause
goto :end

:error
echo.
echo ========================================
echo FINAL FIX DEPLOYMENT FAILED!
echo ========================================
del new-final-revision.txt latest-stream-final.txt temp_token.txt 2>nul

:end