@echo off
REM Deploy Data Orchestrator with Cleanup Fix
REM Run this from: C:\Users\sonia\lumisignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo LumiSignals Data Orchestrator Deployment
echo With Stale Trade Cleanup Fix
echo ========================================
echo.

REM Set timestamp for unique image tag
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TIMESTAMP=%datetime:~0,8%-%datetime:~8,6%

REM Set image tag
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:%TIMESTAMP%
set LATEST_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:latest

echo [1/7] Building Docker image with cleanup fix...
echo Image tag: %IMAGE_TAG%
docker build -t %IMAGE_TAG% . || goto :error

echo.
echo [2/7] Tagging image as latest...
docker tag %IMAGE_TAG% %LATEST_TAG% || goto :error

echo.
echo [3/7] Logging into ECR...
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com || goto :error

echo.
echo [4/7] Pushing timestamped image to ECR...
docker push %IMAGE_TAG% || goto :error

echo.
echo [5/7] Pushing latest tag to ECR...
docker push %LATEST_TAG% || goto :error

echo.
echo [6/7] Verifying push to ECR...
aws ecr describe-images --repository-name lumisignals/institutional-orchestrator-postgresql17 --region us-east-1 --query "imageDetails[0].imageTags" || goto :error

echo.
echo [7/7] Deploying to ECS (forcing new deployment)...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --force-new-deployment --region us-east-1 || goto :error

echo.
echo ========================================
echo DEPLOYMENT INITIATED SUCCESSFULLY!
echo ========================================
echo.
echo Next steps:
echo 1. Wait 3-5 minutes for ECS to deploy the new container
echo 2. Monitor logs: aws logs tail /ecs/lumisignals-data-orchestrator --follow
echo 3. Look for "comprehensive data orchestrator" in logs
echo 4. Trade 1581 should be cleaned up on next data cycle
echo.
echo To check deployment status:
echo aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1
echo.
goto :end

:error
echo.
echo ========================================
echo ERROR: Deployment failed!
echo ========================================
echo Please check the error message above.
echo Common issues:
echo - Docker not running
echo - AWS credentials not configured
echo - No internet connection
echo.

:end
pause