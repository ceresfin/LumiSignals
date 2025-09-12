@echo off
REM TIERED STORAGE DEPLOYMENT: 500 Candlestick Lazy Loading System
REM Based on Golden Template TD 196 + Enhanced with Tiered Storage
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo TIERED STORAGE DEPLOYMENT 
echo 500 Candlestick Lazy Loading System
echo ========================================
echo.
echo NEW FEATURES:
echo 1. Hot Tier: 50 most recent candles (1 day TTL)
echo 2. Warm Tier: 450 older candles (5 day TTL) 
echo 3. Cold Tier: 500 bootstrap candles (7 day TTL)
echo 4. Automatic rotation: Hot -^> Warm tier management
echo 5. Smart retrieval: Multi-tier fallback system
echo 6. Bootstrap collection: ENABLE_BOOTSTRAP=true
echo.
echo BASED ON GOLDEN TEMPLATE TD 196:
echo ✅ Correct IAM roles (both task + execution)
echo ✅ High performance: CPU 2048, Memory 4096
echo ✅ JSON secrets format (Architecture Bible)
echo ✅ Proven deployment verification process
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:tiered-storage-%TIMESTAMP%

echo [1/9] Building container with tiered storage system...
echo Image: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=tiered-storage-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/9] Pushing to ECR...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/9] Creating task definition with Golden Template TD 196 configuration + Tiered Storage environment variables...
echo USING: Golden Template IAM roles + CPU/Memory + Secrets
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-role ^
--execution-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 2048 ^
--memory 4096 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"%IMAGE_TAG%\",\"essential\":true,\"environment\":[{\"name\":\"TIMEFRAMES\",\"value\":\"M5,H1\"},{\"name\":\"AGGREGATED_TIMEFRAMES\",\"value\":\"M15,M30\"},{\"name\":\"HOT_TIER_CANDLES\",\"value\":\"50\"},{\"name\":\"WARM_TIER_CANDLES\",\"value\":\"450\"},{\"name\":\"BOOTSTRAP_CANDLES\",\"value\":\"500\"},{\"name\":\"HOT_TIER_TTL\",\"value\":\"86400\"},{\"name\":\"WARM_TIER_TTL\",\"value\":\"432000\"},{\"name\":\"COLD_TIER_TTL\",\"value\":\"604800\"},{\"name\":\"ENABLE_BOOTSTRAP\",\"value\":\"true\"},{\"name\":\"COLLECTION_INTERVAL_SECONDS\",\"value\":\"300\"}],\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_CREDENTIALS\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials\"}]}]" ^
--region us-east-1 --query "taskDefinition.revision" --output text > new-tiered-revision.txt

set /p NEW_REVISION=<new-tiered-revision.txt
echo ✅ Created Task Definition: lumisignals-data-orchestrator:%NEW_REVISION%

echo.
echo [4/9] Verifying task definition configuration...
REM Verify IAM roles (Golden Template requirement)
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.taskRoleArn" --output text') do set TASK_ROLE=%%i
echo Task Role ARN: %TASK_ROLE%
echo %TASK_ROLE% | findstr /C:"lumisignals-ecs-task-role" >nul
if %errorlevel%==0 (
    echo ✅ VERIFIED: Correct IAM task role configured
) else (
    echo ❌ ERROR: Wrong IAM task role! Expected lumisignals-ecs-task-role
    goto :error
)

REM Verify execution role  
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.executionRoleArn" --output text') do set EXEC_ROLE=%%i
echo Execution Role ARN: %EXEC_ROLE%
echo %EXEC_ROLE% | findstr /C:"lumisignals-ecs-task-execution-role" >nul
if %errorlevel%==0 (
    echo ✅ VERIFIED: Correct IAM execution role configured
) else (
    echo ❌ ERROR: Wrong IAM execution role! Expected lumisignals-ecs-task-execution-role
    goto :error
)

REM Verify secrets (Golden Template requirement)
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text') do set SECRETS_COUNT=%%i
echo Secrets count: %SECRETS_COUNT%
if "%SECRETS_COUNT%"=="4" (
    echo ✅ VERIFIED: 4 secrets configured correctly
) else (
    echo ❌ ERROR: Expected 4 secrets, got %SECRETS_COUNT%
    goto :error
)

REM Verify environment variables (Tiered Storage requirement)
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].environment)" --output text') do set ENV_COUNT=%%i
echo Environment variables count: %ENV_COUNT%
if %ENV_COUNT% GEQ 10 (
    echo ✅ VERIFIED: Tiered storage environment variables configured (%ENV_COUNT% total)
) else (
    echo ❌ ERROR: Expected at least 10 environment variables, got %ENV_COUNT%
    goto :error
)

REM Verify CPU/Memory (Golden Template requirement)
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.cpu" --output text') do set CPU_UNITS=%%i
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.memory" --output text') do set MEMORY_UNITS=%%i
echo CPU: %CPU_UNITS%, Memory: %MEMORY_UNITS%
if "%CPU_UNITS%"=="2048" if "%MEMORY_UNITS%"=="4096" (
    echo ✅ VERIFIED: High performance configuration (Golden Template standard)
) else (
    echo ❌ ERROR: Expected CPU 2048, Memory 4096, got CPU %CPU_UNITS%, Memory %MEMORY_UNITS%
    goto :error
)

echo.
echo [5/9] Deploying service with new task definition...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [6/9] Waiting 45 seconds for deployment to start...
timeout /t 45 /nobreak

echo.
echo [7/9] CRITICAL: Verifying task actually starts (prevents silent failures)...
echo Checking running tasks...
aws ecs list-tasks --cluster lumisignals-cluster --service-name lumisignals-data-orchestrator --region us-east-1 --query "taskArns[0]" --output text > current-task.txt
set /p TASK_ARN=<current-task.txt

if "%TASK_ARN%"=="None" (
    echo ❌ ERROR: No running task found!
    echo Checking ECS service events for errors...
    aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:5]" --output table
    goto :error
)

echo Found running task: %TASK_ARN%
echo Checking task definition revision...
for /f "tokens=*" %%i in ('aws ecs describe-tasks --cluster lumisignals-cluster --tasks %TASK_ARN% --region us-east-1 --query "tasks[0].taskDefinitionArn" --output text') do set RUNNING_TD=%%i
echo Running task definition: %RUNNING_TD%
echo %RUNNING_TD% | findstr /C:":%NEW_REVISION%" >nul
if %errorlevel%==0 (
    echo ✅ VERIFIED: New task definition %NEW_REVISION% is running!
) else (
    echo ⚠️ WARNING: Task is still running old definition
    echo Waiting additional 2 minutes for rollout...
    timeout /t 120 /nobreak
    
    REM Re-check after wait
    aws ecs list-tasks --cluster lumisignals-cluster --service-name lumisignals-data-orchestrator --region us-east-1 --query "taskArns[0]" --output text > current-task2.txt
    set /p TASK_ARN2=<current-task2.txt
    for /f "tokens=*" %%i in ('aws ecs describe-tasks --cluster lumisignals-cluster --tasks %TASK_ARN2% --region us-east-1 --query "tasks[0].taskDefinitionArn" --output text') do set RUNNING_TD2=%%i
    echo Re-check - Running task definition: %RUNNING_TD2%
    echo %RUNNING_TD2% | findstr /C:":%NEW_REVISION%" >nul
    if %errorlevel%==0 (
        echo ✅ VERIFIED: New task definition %NEW_REVISION% is now running!
    ) else (
        echo ❌ ERROR: Deployment failed - still running old task definition
        echo Checking service events...
        aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:5]" --output table
        goto :error
    )
)

echo.
echo [8/9] Waiting 2 minutes for bootstrap collection to initialize...
echo BOOTSTRAP PROCESS: ENABLE_BOOTSTRAP=true will collect 500 candles for all pairs/timeframes
timeout /t 120 /nobreak

echo.
echo [9/9] Checking for tiered storage initialization messages...
REM Get latest log stream
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream-tiered.txt
set /p STREAM_NAME=<latest-stream-tiered.txt

echo.
echo Looking for tiered storage and bootstrap initialization messages...
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-60:].message" --output text | findstr /C:"Bootstrap enabled" /C:"tiered Redis storage" /C:"Bootstrap collection completed" /C:"hot tier" /C:"warm tier" /C:"ERROR" /C:"Failed"

echo.
echo ========================================
echo TIERED STORAGE DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Definition: %NEW_REVISION%
echo Configuration Summary:
echo   ✅ Hot Tier: 50 candles (1 day TTL)
echo   ✅ Warm Tier: 450 candles (5 day TTL)
echo   ✅ Cold Tier: 500 candles (7 day TTL)
echo   ✅ Bootstrap: Enabled (500 candles on startup)
echo   ✅ Timeframes: M5, H1 (native) + M15, M30 (aggregated)
echo   ✅ Golden Template: IAM roles, CPU/Memory, Secrets
echo.
echo MONITORING COMMANDS:
echo # Check tier stats for EUR_USD M5:
echo aws ecs execute-command --cluster lumisignals-cluster --task [TASK_ID] --container lumisignals-data-orchestrator --command "python -c \"import asyncio; from src.data_orchestrator import *; asyncio.run(orchestrator.get_tier_stats('EUR_USD', 'M5'))\""
echo.
echo # Watch logs for bootstrap completion:
echo aws logs tail /ecs/lumisignals-data-orchestrator --follow --region us-east-1
echo.
echo Next Steps:
echo 1. Monitor logs for "Bootstrap collection completed successfully"  
echo 2. Check pipstop.org charts for improved loading (500 candlesticks)
echo 3. Monitor tier utilization via CloudWatch or tier stats
echo 4. Test chart scrollback performance with 500 candles
echo.

del new-tiered-revision.txt latest-stream-tiered.txt current-task.txt current-task2.txt temp_token.txt 2>nul
pause
goto :end

:error
echo.
echo ========================================
echo TIERED STORAGE DEPLOYMENT FAILED!
echo ========================================
echo Common failure causes:
echo 1. Wrong IAM role configuration
echo 2. Task failed to start (check ECS service events)
echo 3. Container image build/push issues
echo 4. Environment variable parsing errors
echo 5. Resource constraints (CPU/Memory)
echo.
echo TROUBLESHOOTING COMMANDS:
echo # Check service events:
echo aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:10]" --output table
echo.
echo # Check task definition details:
echo aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.{taskRole:taskRoleArn,executionRole:executionRoleArn,cpu:cpu,memory:memory,secrets:length(containerDefinitions[0].secrets),env:length(containerDefinitions[0].environment)}" --output json
echo.
echo # Emergency rollback to TD 196:
echo aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:196 --desired-count 1 --force-new-deployment --region us-east-1
echo.
del new-tiered-revision.txt latest-stream-tiered.txt current-task.txt current-task2.txt temp_token.txt 2>nul
pause

:end