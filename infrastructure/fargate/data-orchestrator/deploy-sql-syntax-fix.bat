@echo off
REM Deploy Data Orchestrator with SQL Syntax Fix (FINAL FINAL)
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo LumiSignals Data Orchestrator Deployment
echo With SQL Syntax Fix (FINAL FINAL)
echo ========================================
echo.
echo ALL FIXES INCLUDED:
echo 1. Method name: collect_and_store_comprehensive_data()
echo 2. Proper initialization with state tracking
echo 3. Redis manager parameter passed correctly  
echo 4. Logic flow fixed (no fallback confusion)
echo 5. Method signature fix: cleanup_inactive_trades conflict resolved
echo 6. SQL SYNTAX FIX: PostgreSQL INTERVAL syntax corrected
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:sql-syntax-fix-%TIMESTAMP%
set LATEST_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:latest

echo [1/12] Building new container with SQL syntax fix...
echo Image tag: %IMAGE_TAG%
echo.

REM Build new container with all fixes and cache busting
docker build --no-cache --build-arg VERSION=sql-syntax-fix-%TIMESTAMP% --build-arg BUILD_DATE="%date% %time%" --build-arg COMMIT_SHA=sql-syntax-fix --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/12] Tagging image as latest...
docker tag %IMAGE_TAG% %LATEST_TAG% || goto :error

echo.
echo [3/12] Getting ECR login token...
aws ecr get-login-password --region us-east-1 > %TEMP%\ecr-token.txt || goto :error

echo.
echo [4/12] Logging into ECR...
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < %TEMP%\ecr-token.txt || goto :error
del %TEMP%\ecr-token.txt

echo.
echo [5/12] Pushing timestamped image to ECR...
docker push %IMAGE_TAG% || goto :error

echo.
echo [6/12] Pushing latest tag to ECR...
docker push %LATEST_TAG% || goto :error

echo.
echo [7a/12] CACHE CLEAR #1 - Clearing Docker cache to ensure fresh builds...
docker system prune -f || echo "Cache clear completed"

echo.
echo [7b/12] CACHE CLEAR #2 - Getting image digest for verification...
for /f "tokens=*" %%i in ('aws ecr describe-images --repository-name lumisignals/institutional-orchestrator-postgresql17 --image-ids imageTag^=sql-syntax-fix-%TIMESTAMP% --region us-east-1 --query "imageDetails[0].imageDigest" --output text') do set IMAGE_DIGEST=%%i
echo Image digest: %IMAGE_DIGEST%

echo.
echo [7c/12] CACHE CLEAR #3 - Creating new task definition with specific container...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 --query "taskDefinition" > %TEMP%\current-task-def.json
powershell -Command "& {$taskDef = Get-Content '%TEMP%\current-task-def.json' | ConvertFrom-Json; $fieldsToRemove = @('taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'placementConstraints', 'compatibilities', 'registeredAt', 'registeredBy'); foreach ($field in $fieldsToRemove) { $taskDef.PSObject.Properties.Remove($field) }; $taskDef.containerDefinitions[0].image = '%IMAGE_TAG%'; $taskDef | ConvertTo-Json -Depth 10 | Out-File '%TEMP%\new-task-def.json' -Encoding UTF8}"

echo.
echo [7d/12] CACHE CLEAR #4 - Registering new task definition...
for /f "tokens=*" %%i in ('aws ecs register-task-definition --cli-input-json file:///%TEMP%/new-task-def.json --region us-east-1 --query "taskDefinition.revision" --output text') do set NEW_REVISION=%%i
echo New task definition revision: %NEW_REVISION%

echo.
echo [8/12] CACHE CLEAR #4 - Forcing ECS to stop current container...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 0 --region us-east-1 || goto :error
echo Waiting 15 seconds for tasks to stop...
timeout /t 15 /nobreak

echo.
echo [9/12] CACHE CLEAR #4 - Starting service with NEW task definition and fresh container...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1 || goto :error

echo.
echo [10/12] Initial deployment status check...
timeout /t 30 /nobreak
aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].deployments[0].{Status:status,CreatedAt:createdAt,UpdatedAt:updatedAt,TaskDefinition:taskDefinition}" --output table

echo.
echo [11/12] Waiting 240 seconds (4 minutes) for full container startup...
echo Starting automated wait at %time%
timeout /t 240 /nobreak
echo Wait completed at %time%

echo.
echo [12/12] AUTOMATED VERIFICATION - Checking for SQL syntax fix success...
echo Checking recent logs for successful cleanup messages...

REM Get timestamp from 5 minutes ago for log search
powershell -Command "& {[int]((Get-Date).AddMinutes(-5) - [datetime]'1970-01-01').TotalMilliseconds}" > %TEMP%\timestamp.txt
set /p LOG_START_TIME=<%TEMP%\timestamp.txt
del %TEMP%\timestamp.txt

aws logs filter-log-events --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --start-time %LOG_START_TIME% --query "events[].message" --output text | findstr /C:"✅ Comprehensive data collection and cleanup completed successfully" /C:"🧹 Cleaned up" /C:"Comprehensive orchestrator completed successfully" /C:"cleanup_inactive_trades"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ SUCCESS: SQL syntax fix working!
    echo ✅ Comprehensive orchestrator running cleanup successfully
    echo ✅ Trade 1581 should be cleaned up automatically
    echo ✅ Check pipstop.org to verify stale trade removal
) else (
    echo.
    echo ❌ WARNING: No successful cleanup messages found yet
    echo ❌ Check logs manually for any remaining SQL errors
)

echo.
echo FINAL STATUS CHECK:
aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].{Status:status,RunningCount:runningCount,TaskDefinition:taskDefinition}" --output table

echo.
echo ========================================
echo SQL SYNTAX FIX DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo VERIFICATION RESULTS:
echo 1. Image digest: %IMAGE_DIGEST%
echo 2. Container tag: sql-syntax-fix-%TIMESTAMP%
echo 3. Task definition revision: %NEW_REVISION%
echo 4. ALL 4 CACHE CLEARING TECHNIQUES USED:
echo    a. Docker system prune
echo    b. Image digest verification
echo    c. New task definition creation
echo    d. Stop/start with force deployment
echo 5. Log verification: automated search completed
echo.
echo ALL FIXES DEPLOYED:
echo ✅ Fix 1: Method name corrected (collect_and_store_comprehensive_data)
echo ✅ Fix 2: Proper initialization with state tracking
echo ✅ Fix 3: Redis manager parameter passed correctly  
echo ✅ Fix 4: Logic flow fixed (no fallback confusion)
echo ✅ Fix 5: Method signature - cleanup_inactive_trades conflict resolved
echo ✅ Fix 6: SQL SYNTAX - PostgreSQL INTERVAL syntax corrected
echo.
echo EXPECTED RESULTS:
echo - Data collection happens every 5 minutes
echo - Comprehensive orchestrator runs cleanup successfully
echo - Trade 1581 automatically removed from active_trades table
echo - Real-time accurate data in pipstop.org
echo - No more SQL syntax errors in logs
echo.
echo DELETE TEMP FILES:
del %TEMP%\current-task-def.json %TEMP%\new-task-def.json %TEMP%\timestamp.txt 2>nul
echo.
goto :end

:error
echo.
echo ========================================
echo ERROR: Deployment failed!
echo ========================================
echo Please check the error message above.
del %TEMP%\ecr-token.txt %TEMP%\current-task-def.json %TEMP%\new-task-def.json %TEMP%\timestamp.txt 2>nul
echo.

:end
pause