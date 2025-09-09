@echo off
echo Continuing deployment from successful build...
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:20250908-202631
set LATEST_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:latest

echo [3/7] Getting ECR login token...
aws ecr get-login-password --region us-east-1 > %TEMP%\ecr-token.txt

echo [4/7] Logging into ECR...
type %TEMP%\ecr-token.txt  < /dev/null |  docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com
del %TEMP%\ecr-token.txt

echo [5/7] Pushing timestamped image...
docker push %IMAGE_TAG%

echo [6/7] Pushing latest tag...  
docker push %LATEST_TAG%

echo [7/7] Deploying to ECS...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --force-new-deployment --region us-east-1

echo DEPLOYMENT COMPLETED\!
pause
