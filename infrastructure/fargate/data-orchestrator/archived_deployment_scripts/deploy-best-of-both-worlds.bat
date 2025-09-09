@echo off
REM Best of Both Worlds: OANDA Secrets + Latest Code Fixes
REM Simple approach: Build new container, copy GOOD task definition manually
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Best of Both Worlds Deployment
echo OANDA Secrets + Latest Code Fixes
echo ========================================
echo.
echo Strategy:
echo 1. Build new container with ALL latest fixes
echo 2. Copy Task Definition 187 structure (has secrets)
echo 3. Manual task definition creation (avoid PowerShell JSON issues)
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:best-of-both-%TIMESTAMP%

echo [1/4] Building new container with ALL fixes...
echo Image tag: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=best-of-both-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/4] Pushing to ECR...
aws ecr get-login-password --region us-east-1 > temp_token.txt
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < temp_token.txt
docker push %IMAGE_TAG% || goto :error
del temp_token.txt

echo.
echo [3/4] Getting Task Definition 187 as template (has secrets)...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:187 --region us-east-1 --query "taskDefinition" > td-187-template.json

echo.
echo [4/4] Creating new task definition with BOTH secrets AND latest container...
echo.
echo MANUAL STEP REQUIRED:
echo 1. I've downloaded Task Definition 187 to td-187-template.json
echo 2. You need to manually edit this file to update the container image
echo 3. Change the "image" field from its current value to: %IMAGE_TAG%
echo 4. Then run: aws ecs register-task-definition --cli-input-json file://td-187-template.json --region us-east-1
echo.
echo This approach avoids PowerShell JSON parsing issues completely!
echo.

echo Container ready: %IMAGE_TAG%
echo Template file: td-187-template.json
echo.
pause
goto :end

:error
echo.
echo ========================================
echo BUILD FAILED!
echo ========================================
del temp_token.txt 2>nul

:end