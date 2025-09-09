@echo off
REM Full Rebuild: Fix database credentials parsing + create new golden template
REM This should finally initialize the comprehensive orchestrator for trade cleanup
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Database Credentials Fix Deployment
echo Fix config.py + Create New Golden Template
echo ========================================
echo.
echo CRITICAL FIX: config.py now reads individual DATABASE_HOST variables
echo EXPECTED RESULT: Comprehensive orchestrator will initialize and cleanup trades
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:db-creds-fix-%TIMESTAMP%

echo [1/5] Building container with database credentials fix...
echo Image: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=db-creds-fix-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/5] Pushing to ECR with all cache clearing...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/5] Creating new task definition with TD 191 secrets + fixed container...
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSTaskRole ^
--execution-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSExecutionRole ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 256 ^
--memory 512 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"%IMAGE_TAG%\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_HOST\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:host::\"},{\"name\":\"DATABASE_PORT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:port::\"},{\"name\":\"DATABASE_USERNAME\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:username::\"},{\"name\":\"DATABASE_PASSWORD\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:password::\"},{\"name\":\"DATABASE_NAME\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:dbname::\"}]}]" ^
--region us-east-1 --query "taskDefinition.revision" --output text > new-revision.txt

set /p NEW_REVISION=<new-revision.txt
echo ✅ Created Task Definition: lumisignals-data-orchestrator:%NEW_REVISION%

echo.
echo [4/5] Deploying with all 4 cache clearing methods...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [5/5] Waiting 4 minutes for comprehensive orchestrator to initialize...
timeout /t 240 /nobreak

echo.
echo ========================================
echo DATABASE CREDENTIALS FIX DEPLOYED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Definition: %NEW_REVISION%
echo Fix: config.py now reads individual DATABASE_HOST variables
echo.
echo CHECKING FOR COMPREHENSIVE ORCHESTRATOR...

REM Check for comprehensive orchestrator initialization
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream.txt
set /p STREAM_NAME=<latest-stream.txt

echo.
echo Looking for database initialization messages...
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-20:].message" --output text | findstr /C:"DEBUG: Database host" /C:"DEBUG: Using individual" /C:"🎯"

echo.
echo Expected to see:
echo - "DEBUG: Using individual database environment variables"
echo - "🎯 Comprehensive orchestrator created"
echo - "📊 Initializing Enhanced PostgreSQL database connection"
echo.

if "%NEW_REVISION%"=="" (
    echo ❌ Task definition creation failed!
) else (
    echo ✅ NEW GOLDEN TEMPLATE: Task Definition %NEW_REVISION%
    echo.
    echo GOLDEN TEMPLATE UPDATE REQUIRED:
    echo 1. Update container-deployment-script.md
    echo 2. Change "Golden Template: Task Definition 191" to "Task Definition %NEW_REVISION%"
    echo 3. Update container image reference to: %IMAGE_TAG%
    echo 4. This TD has: database credentials fix + all cache busting + all 8 secrets
    echo.
    echo Expected Results:
    echo - Database manager initializes ✅
    echo - Comprehensive orchestrator starts ✅
    echo - Old trades get cleaned up automatically ✅
    echo - Trade 1581 should disappear from pipstop.org ✅
)

echo.
del new-revision.txt latest-stream.txt temp_token.txt 2>nul
pause
goto :end

:error
echo.
echo ========================================
echo DEPLOYMENT FAILED!
echo ========================================
del new-revision.txt latest-stream.txt temp_token.txt 2>nul

:end