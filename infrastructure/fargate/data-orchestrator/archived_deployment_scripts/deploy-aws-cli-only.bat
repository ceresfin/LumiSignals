@echo off
REM AWS CLI Only Approach - No PowerShell JSON manipulation
REM Build container, then use AWS CLI to clone and update task definition
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo AWS CLI Only Deployment
echo No PowerShell JSON manipulation
echo ========================================
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:aws-cli-%TIMESTAMP%

echo [1/5] Building new container with all fixes...
echo Image: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=aws-cli-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/5] Pushing to ECR...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/5] Cloning Task Definition 187 structure with new container image...
REM Use AWS CLI to create new task definition based on 187 but with new image
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:187 --region us-east-1 --query "taskDefinition.{family: family, taskRoleArn: taskRoleArn, executionRoleArn: executionRoleArn, networkMode: networkMode, requiresCompatibilities: requiresCompatibilities, cpu: cpu, memory: memory, containerDefinitions: containerDefinitions}" > temp-base.json

echo.
echo [4/5] Using Python to update container image (avoiding PowerShell)...
python -c "
import json
import sys

# Read the base task definition
with open('temp-base.json', 'r') as f:
    task_def = json.load(f)

# Update the container image
task_def['containerDefinitions'][0]['image'] = '%IMAGE_TAG%'

# Write the updated task definition
with open('updated-task-def.json', 'w') as f:
    json.dump(task_def, f, indent=2)

print('✅ Task definition updated with new container image')
"

echo.
echo [5/5] Registering and deploying new task definition...
for /f "tokens=*" %%i in ('aws ecs register-task-definition --cli-input-json file://updated-task-def.json --region us-east-1 --query "taskDefinition.revision" --output text') do set NEW_REVISION=%%i
echo New revision: %NEW_REVISION%

aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo Waiting 4 minutes for deployment...
timeout /t 240 /nobreak

echo.
echo ========================================
echo AWS CLI DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Definition: lumisignals-data-orchestrator:%NEW_REVISION%
echo Secrets: Copied from Task Definition 187
echo.
echo Expected Results:
echo - OANDA authentication working (secrets preserved)
echo - Comprehensive orchestrator with all latest fixes
echo - Trade cleanup should happen automatically
echo.

echo AUTOMATIC LOG CHECK...
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream.txt
set /p STREAM_NAME=<latest-stream.txt
echo.
echo Recent logs:
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-8:].message" --output text
echo.

echo Cleanup temp files...
del temp-base.json updated-task-def.json latest-stream.txt temp_token.txt 2>nul
pause
goto :end

:error
echo.
echo ========================================
echo DEPLOYMENT FAILED!
echo ========================================
del temp-base.json updated-task-def.json latest-stream.txt temp_token.txt 2>nul

:end