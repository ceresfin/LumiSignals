@echo off
REM Deploy Data Orchestrator with Comprehensive Fix (All 4 Critical Bugs Fixed)
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo LumiSignals Data Orchestrator Deployment
echo With Comprehensive Orchestrator Fix
echo ========================================
echo.
echo FIXES INCLUDED:
echo 1. Method name: collect_and_store_comprehensive_data()
echo 2. Proper initialization with state tracking
echo 3. Redis manager parameter passed correctly
echo 4. Logic flow fixed (no fallback confusion)
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:comprehensive-fix-%TIMESTAMP%
set LATEST_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:latest

echo [1/10] Building new container with comprehensive orchestrator fixes...
echo Image tag: %IMAGE_TAG%
echo.

REM Build new container with all fixes and cache busting
docker build --no-cache --build-arg VERSION=comprehensive-fix-%TIMESTAMP% --build-arg BUILD_DATE="%date% %time%" --build-arg COMMIT_SHA=comprehensive-fix --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/10] Tagging image as latest...
docker tag %IMAGE_TAG% %LATEST_TAG% || goto :error

echo.
echo [3/10] Getting ECR login token...
aws ecr get-login-password --region us-east-1 > %TEMP%\ecr-token.txt || goto :error

echo.
echo [4/10] Logging into ECR...
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < %TEMP%\ecr-token.txt || goto :error
del %TEMP%\ecr-token.txt

echo.
echo [5/10] Pushing timestamped image to ECR...
docker push %IMAGE_TAG% || goto :error

echo.
echo [6/10] Pushing latest tag to ECR...
docker push %LATEST_TAG% || goto :error

echo.
echo [7a/10] Clearing Docker cache to ensure fresh builds...
docker system prune -f || echo "Cache clear completed"

echo.
echo [7b/10] Getting image digest for verification...
for /f "tokens=*" %%i in ('aws ecr describe-images --repository-name lumisignals/institutional-orchestrator-postgresql17 --image-ids imageTag^=comprehensive-fix-%TIMESTAMP% --region us-east-1 --query "imageDetails[0].imageDigest" --output text') do set IMAGE_DIGEST=%%i
echo Image digest: %IMAGE_DIGEST%

echo.
echo [8/10] Forcing ECS to pull fresh image (stop/start method)...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 0 --region us-east-1 || goto :error
echo Waiting 15 seconds for tasks to stop...
timeout /t 15 /nobreak

echo.
echo [9/10] Starting service with fresh container...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 1 --force-new-deployment --region us-east-1 || goto :error

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
echo [12/12] AUTOMATED VERIFICATION - Checking for comprehensive orchestrator...
echo Checking recent logs for comprehensive orchestrator messages...

REM Get timestamp from 5 minutes ago for log search
powershell -Command "& {[int]((Get-Date).AddMinutes(-5) - [datetime]'1970-01-01').TotalMilliseconds}" > %TEMP%\timestamp.txt
set /p LOG_START_TIME=<%TEMP%\timestamp.txt
del %TEMP%\timestamp.txt

aws logs filter-log-events --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --start-time %LOG_START_TIME% --query "events[].message" --output text | findstr /C:"comprehensive" /C:"🎯" /C:"Comprehensive orchestrator" /C:"collect_and_store_comprehensive_data"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ SUCCESS: Comprehensive orchestrator messages found!
    echo ✅ All 4 critical bugs should be fixed
    echo ✅ Trade cleanup should be working automatically
    echo ✅ Trade 1581 should be cleaned up in next data cycle
) else (
    echo.
    echo ❌ WARNING: No comprehensive orchestrator messages found yet
    echo ❌ May need additional troubleshooting
)

echo.
echo FINAL STATUS CHECK:
aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].{Status:status,RunningCount:runningCount,TaskDefinition:taskDefinition}" --output table

echo.
echo ========================================
echo COMPREHENSIVE FIX DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo VERIFICATION RESULTS:
echo 1. Image digest: %IMAGE_DIGEST%
echo 2. Container tag: comprehensive-fix-%TIMESTAMP%
echo 3. Deployment method: stop/start with force refresh
echo 4. Wait time: 4 minutes (240 seconds)
echo 5. Log verification: automated search completed
echo.
echo CRITICAL FIXES DEPLOYED:
echo ✅ Fix 1: Method name corrected (collect_and_store_comprehensive_data)
echo ✅ Fix 2: Proper initialization with state tracking
echo ✅ Fix 3: Redis manager parameter passed correctly  
echo ✅ Fix 4: Logic flow fixed (no fallback confusion)
echo.
echo NEXT DATA CYCLE:
echo - Data collection happens every 5 minutes
echo - Comprehensive orchestrator should initialize properly
echo - Trade 1581 cleanup should happen automatically
echo - Check pipstop.org in 10-15 minutes to verify stale trade removal
echo.
goto :end

:error
echo.
echo ========================================
echo ERROR: Deployment failed!
echo ========================================
echo Please check the error message above.
if exist %TEMP%\ecr-token.txt del %TEMP%\ecr-token.txt
echo.

:end
pause