@echo off
REM Simple Container Update Deployment (Approach 1)
REM This updates ONLY the container image, keeping all existing configuration
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo LumiSignals Simple Image Update Deploy
echo Approach 1: Keep Task Definition, Update Container
echo ========================================
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:v-%TIMESTAMP%

echo [1/6] Building new container...
echo Image tag: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=v-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/6] Pushing to ECR...
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com || goto :error
docker push %IMAGE_TAG% || goto :error

echo.
echo [3/6] Finding the GOOD task definition with secrets...
REM Find a task definition that has OANDA secrets configured
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:187 --region us-east-1 --query "taskDefinition.containerDefinitions[0].secrets[?name==''OANDA_API_KEY''].name" --output text') do set HAS_SECRETS=%%i

if "%HAS_SECRETS%"=="OANDA_API_KEY" (
    set GOOD_TASK_DEF=187
    echo Found task definition 187 with OANDA secrets configured
) else (
    echo ERROR: Task definition 187 does not have OANDA secrets!
    goto :error
)

echo.
echo [4/6] Creating new task definition with updated container image...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%GOOD_TASK_DEF% --region us-east-1 --query "taskDefinition" > temp-task-def.json

REM Update container image in the task definition
powershell -Command "& {$json = Get-Content 'temp-task-def.json' | ConvertFrom-Json; $json.PSObject.Properties.Remove('taskDefinitionArn'); $json.PSObject.Properties.Remove('revision'); $json.PSObject.Properties.Remove('status'); $json.PSObject.Properties.Remove('requiresAttributes'); $json.PSObject.Properties.Remove('placementConstraints'); $json.PSObject.Properties.Remove('compatibilities'); $json.PSObject.Properties.Remove('registeredAt'); $json.PSObject.Properties.Remove('registeredBy'); $json.containerDefinitions[0].image = '%IMAGE_TAG%'; $json | ConvertTo-Json -Depth 10 | Out-File 'updated-task-def.json' -Encoding UTF8}"

for /f "tokens=*" %%i in ('aws ecs register-task-definition --cli-input-json file://updated-task-def.json --region us-east-1 --query "taskDefinition.revision" --output text') do set NEW_REVISION=%%i
echo New task definition revision: %NEW_REVISION%

echo.
echo [5/6] VERIFICATION: Checking new task definition has secrets...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.containerDefinitions[0].secrets[?name==''OANDA_API_KEY''].name" --output text') do set VERIFY_SECRETS=%%i

if "%VERIFY_SECRETS%"=="OANDA_API_KEY" (
    echo ✅ VERIFIED: New task definition has OANDA secrets!
) else (
    echo ❌ ERROR: New task definition missing secrets!
    goto :error
)

echo.
echo [6/6] Deploying with force new deployment...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo Waiting 2 minutes for deployment...
timeout /t 120 /nobreak

echo.
echo ========================================
echo SIMPLE IMAGE UPDATE COMPLETED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Definition: lumisignals-data-orchestrator:%NEW_REVISION%
echo Base Configuration: Copied from revision %GOOD_TASK_DEF% (has secrets)
echo.
echo Expected Results:
echo - OANDA authentication should work (secrets preserved)
echo - Comprehensive orchestrator should activate
echo - Trade cleanup should happen automatically
echo.
echo Clean up temp files...
del temp-task-def.json updated-task-def.json 2>nul
echo.
pause
goto :end

:error
echo.
echo ========================================
echo DEPLOYMENT FAILED!
echo ========================================
del temp-task-def.json updated-task-def.json 2>nul

:end