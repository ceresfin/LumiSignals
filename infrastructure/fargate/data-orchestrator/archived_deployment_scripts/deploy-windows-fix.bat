@echo off
echo ========================================
echo LumiSignals Data Orchestrator Deployment  
echo With Stale Trade Cleanup Fix
echo ========================================
echo.

REM Continue from where build succeeded
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:20250908-202631
set LATEST_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:latest

echo [3/7] Getting ECR login token...
aws ecr get-login-password --region us-east-1 > %TEMP%\ecr-token.txt || goto :error

echo [4/7] Logging into ECR...
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < %TEMP%\ecr-token.txt || goto :error
del %TEMP%\ecr-token.txt

echo.
echo [5/7] Pushing timestamped image to ECR...
docker push %IMAGE_TAG% || goto :error

echo.
echo [6/7] Pushing latest tag to ECR...
docker push %LATEST_TAG% || goto :error

echo.
echo [7/7] Deploying to ECS...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --force-new-deployment --region us-east-1 || goto :error

echo.
echo ========================================
echo DEPLOYMENT COMPLETED SUCCESSFULLY\!
echo ========================================
goto :end

:error
echo ERROR: Deployment failed\!
if exist %TEMP%\ecr-token.txt del %TEMP%\ecr-token.txt

:end
pause
EOF < /dev/null
