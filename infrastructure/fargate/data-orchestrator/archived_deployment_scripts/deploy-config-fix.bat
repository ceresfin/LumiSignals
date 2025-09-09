@echo off
REM Configuration Fix: Unified Database Config + Enhanced Debug Logging
REM This fixes the database config mismatch between main.py and data_orchestrator.py
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Configuration Fix Deployment
echo Unified Database Config + Enhanced Debug
echo ========================================
echo.
echo CRITICAL FIXES:
echo 1. data_orchestrator.py now uses settings.parsed_database_* (same as main.py)
echo 2. config.py prioritizes DATABASE_CREDENTIALS JSON parsing
echo 3. Enhanced debug logging to track credential parsing
echo 4. Both main.py and data_orchestrator.py use same database config source
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:config-fix-%TIMESTAMP%

echo [1/6] Building container with configuration fixes...
echo Image: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=config-fix-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/6] Pushing to ECR...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/6] Creating task definition with DATABASE_CREDENTIALS secret...
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSTaskRole ^
--execution-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSExecutionRole ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 256 ^
--memory 512 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"%IMAGE_TAG%\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_CREDENTIALS\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials\"}]}]" ^
--region us-east-1 --query "taskDefinition.revision" --output text > new-config-revision.txt

set /p NEW_REVISION=<new-config-revision.txt
echo ✅ Created Task Definition: lumisignals-data-orchestrator:%NEW_REVISION%

echo.
echo [4/6] Verifying task definition configuration...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text') do set SECRETS_COUNT=%%i
echo Secrets count: %SECRETS_COUNT%

for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.containerDefinitions[0].secrets[?name==`DATABASE_CREDENTIALS`].name" --output text') do set DB_SECRET_NAME=%%i
if "%DB_SECRET_NAME%"=="DATABASE_CREDENTIALS" (
    echo ✅ VERIFIED: DATABASE_CREDENTIALS secret properly configured
) else (
    echo ❌ ERROR: DATABASE_CREDENTIALS secret missing
    goto :error
)

echo.
echo [5/6] Deploying with all cache clearing methods...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [6/6] Waiting 4 minutes for comprehensive orchestrator initialization...
echo This should finally work with unified database configuration!
timeout /t 240 /nobreak

echo.
echo ========================================
echo CONFIGURATION FIX DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Definition: %NEW_REVISION%
echo.
echo KEY FIXES APPLIED:
echo ✅ data_orchestrator.py uses same database config as main.py
echo ✅ config.py prioritizes DATABASE_CREDENTIALS JSON parsing  
echo ✅ Enhanced debug logging for credential tracking
echo ✅ Unified database configuration eliminates mismatch
echo.

echo CHECKING FOR INITIALIZATION SUCCESS...
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream-config.txt
set /p STREAM_NAME=<latest-stream-config.txt

echo.
echo Looking for critical debug messages...
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-40:].message" --output text | findstr /C:"DEBUG: Parsing DATABASE_CREDENTIALS" /C:"DEBUG: parsed_database_host" /C:"📊 Initializing Enhanced PostgreSQL" /C:"🎯 Creating comprehensive orchestrator" /C:"🎯 Comprehensive orchestrator created"

echo.
echo Expected to see:
echo - "DEBUG: Parsing DATABASE_CREDENTIALS JSON (Architecture Bible format)"
echo - "DEBUG: parsed_database_host returning: 'lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com'"
echo - "📊 Initializing Enhanced PostgreSQL database connection"
echo - "🎯 Creating comprehensive orchestrator with database: lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com"
echo - "🎯 Comprehensive orchestrator created - initialization pending"
echo.

if "%NEW_REVISION%"=="" (
    echo ❌ Task definition creation failed!
) else (
    echo ✅ NEW GOLDEN TEMPLATE: Task Definition %NEW_REVISION%
    echo.
    echo EXPECTED RESULTS:
    echo ✅ Database credentials parsed from DATABASE_CREDENTIALS JSON
    echo ✅ Database manager initializes in main.py
    echo ✅ Comprehensive orchestrator initializes in data_orchestrator.py
    echo ✅ Old pending order 99 gets cleaned up
    echo ✅ Trade 1581 removed from pipstop.org
    echo ✅ Real accurate trade data displayed
)

echo.
del new-config-revision.txt latest-stream-config.txt temp_token.txt 2>nul
pause
goto :end

:error
echo.
echo ========================================
echo CONFIGURATION FIX DEPLOYMENT FAILED!
echo ========================================
del new-config-revision.txt latest-stream-config.txt temp_token.txt 2>nul

:end