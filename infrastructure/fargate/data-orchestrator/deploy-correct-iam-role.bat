@echo off
REM CRITICAL FIX: Correct IAM Role + Enhanced Verification
REM This fixes the IAM role issue that caused 7 silent failures (TD 188-194)
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo CRITICAL FIX: Correct IAM Role Deployment
echo Fixing Silent Failures from TD 188-194
echo ========================================
echo.
echo CRITICAL CHANGES:
echo 1. FIXED: Execution role lumisignals-ecs-task-execution-role (not LumiSignalsECSExecutionRole)
echo 2. FIXED: Task role lumisignals-ecs-task-role (already correct)
echo 3. KEPT: DATABASE_CREDENTIALS JSON format (from TD 195)
echo 4. RESTORED: CPU 2048, Memory 4096 (from TD 187 - higher performance)
echo 5. ADDED: Task startup verification (prevents silent failures)
echo 6. ADDED: ECS service event monitoring for deployment errors
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:iam-fix-%TIMESTAMP%

echo [1/8] Building container with all fixes + all cache clearing methods...
echo Image: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=iam-fix-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/8] Pushing to ECR...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/8] Creating task definition with CORRECT IAM role...
echo CRITICAL: Using lumisignals-ecs-task-role (from TD 187)
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-role ^
--execution-role-arn arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 2048 ^
--memory 4096 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"%IMAGE_TAG%\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_CREDENTIALS\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials\"}]}]" ^
--region us-east-1 --query "taskDefinition.revision" --output text > new-iam-revision.txt

set /p NEW_REVISION=<new-iam-revision.txt
echo ✅ Created Task Definition: lumisignals-data-orchestrator:%NEW_REVISION%

echo.
echo [4/8] Verifying task definition configuration...
REM Verify IAM role
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.taskRoleArn" --output text') do set TASK_ROLE=%%i
echo Task Role ARN: %TASK_ROLE%
echo %TASK_ROLE% | findstr /C:"lumisignals-ecs-task-role" >nul
if %errorlevel%==0 (
    echo ✅ VERIFIED: Correct IAM role configured
) else (
    echo ❌ ERROR: Wrong IAM role! Expected lumisignals-ecs-task-role
    goto :error
)

REM Verify secrets
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "length(taskDefinition.containerDefinitions[0].secrets)" --output text') do set SECRETS_COUNT=%%i
echo Secrets count: %SECRETS_COUNT%
if "%SECRETS_COUNT%"=="4" (
    echo ✅ VERIFIED: 4 secrets configured correctly
) else (
    echo ❌ ERROR: Expected 4 secrets, got %SECRETS_COUNT%
    goto :error
)

echo.
echo [5/8] Deploying service with new task definition...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [6/8] Waiting 30 seconds for deployment to start...
timeout /t 30 /nobreak

echo.
echo [7/8] CRITICAL: Verifying task actually starts (not just TD creation)...
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
echo [8/8] Waiting additional 90 seconds for comprehensive orchestrator initialization...
timeout /t 90 /nobreak

echo.
echo ========================================
echo IAM ROLE FIX DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Definition: %NEW_REVISION%
echo IAM Role: lumisignals-ecs-task-role (CORRECT)
echo.
echo CHECKING FOR COMPREHENSIVE ORCHESTRATOR INITIALIZATION...

REM Get latest log stream
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream-iam.txt
set /p STREAM_NAME=<latest-stream-iam.txt

echo.
echo Looking for critical initialization messages...
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-50:].message" --output text | findstr /C:"parsed_database_host" /C:"DATABASE_CREDENTIALS JSON" /C:"Enhanced PostgreSQL" /C:"comprehensive orchestrator" /C:"cleanup complete" /C:"ERROR" /C:"Failed"

echo.
echo DEPLOYMENT VERIFICATION SUMMARY:
echo ✅ Task Definition Created: %NEW_REVISION%
echo ✅ IAM Role: lumisignals-ecs-task-role
echo ✅ Task Started Successfully
echo ✅ Service Updated
echo.
echo Next Steps:
echo 1. Monitor CloudWatch logs for comprehensive orchestrator initialization
echo 2. Check pipstop.org in 5 minutes for trade 1581 cleanup
echo 3. Verify no more silent failures with correct IAM role
echo.

del new-iam-revision.txt latest-stream-iam.txt current-task.txt current-task2.txt temp_token.txt 2>nul
pause
goto :end

:error
echo.
echo ========================================
echo IAM ROLE FIX DEPLOYMENT FAILED!
echo ========================================
echo Common failure causes:
echo 1. Wrong IAM role (check TD configuration)
echo 2. Task failed to start (check ECS service events)
echo 3. Container image issues (check ECR push)
echo 4. Network/subnet configuration issues
echo.
echo Run this command to check service events:
echo aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].events[:10]" --output table
echo.
del new-iam-revision.txt latest-stream-iam.txt current-task.txt current-task2.txt temp_token.txt 2>nul
pause

:end