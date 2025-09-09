@echo off
REM Deploy Data Orchestrator with Secrets Configuration Fix
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo LumiSignals Data Orchestrator Deployment
echo With Secrets Configuration Fix
echo ========================================
echo.
echo FIXING: Missing AWS Secrets Manager configuration
echo This will enable OANDA API authentication
echo.

REM Use the existing container that has all fixes
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:sql-syntax-fix-20250908-235806

echo [1/5] Using existing container with all fixes...
echo Image: %IMAGE_TAG%

echo.
echo [2/5] Getting base task definition from revision 187 (has secrets)...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:187 --region us-east-1 --query "taskDefinition" > base-task-def.json

echo.
echo [3/5] Updating task definition with new container and secrets...
powershell -Command "& {$taskDef = Get-Content 'base-task-def.json' | ConvertFrom-Json; $fieldsToRemove = @('taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'placementConstraints', 'compatibilities', 'registeredAt', 'registeredBy'); foreach ($field in $fieldsToRemove) { $taskDef.PSObject.Properties.Remove($field) }; $taskDef.containerDefinitions[0].image = '%IMAGE_TAG%'; $taskDef | ConvertTo-Json -Depth 10 | Out-File 'new-task-def-with-secrets.json' -Encoding UTF8}"

echo.
echo [4/5] Registering new task definition WITH SECRETS...
for /f "tokens=*" %%i in ('aws ecs register-task-definition --cli-input-json file://new-task-def-with-secrets.json --region us-east-1 --query "taskDefinition.revision" --output text') do set NEW_REVISION=%%i
echo New task definition revision: %NEW_REVISION%

echo.
echo [5/5] Updating service with new task definition...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo Waiting 2 minutes for deployment...
timeout /t 120 /nobreak

echo.
echo VERIFICATION: Checking for OANDA authentication...
powershell -Command "& {[int]((Get-Date).AddMinutes(-3) - [datetime]'1970-01-01').TotalMilliseconds}" > %TEMP%\timestamp.txt
set /p LOG_START_TIME=<%TEMP%\timestamp.txt
del %TEMP%\timestamp.txt

aws logs filter-log-events --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --start-time %LOG_START_TIME% --query "events[].message" --output text | findstr /C:"Illegal header value" /C:"OANDA API key length:" /C:"comprehensive" /C:"🎯"

echo.
echo ========================================
echo SECRETS CONFIGURATION FIX DEPLOYED!
echo ========================================
echo.
echo Container: %IMAGE_TAG%
echo Task Revision: %NEW_REVISION%
echo.
echo Expected Results:
echo - OANDA API authentication should work
echo - No more "Illegal header value" errors  
echo - Comprehensive orchestrator should activate
echo - Trade 1581 cleanup should happen automatically
echo.
echo Clean up temp files...
del base-task-def.json new-task-def-with-secrets.json 2>nul
echo.
pause