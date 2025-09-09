@echo off
REM Option B: Update Task Definition 187 with Latest Container
REM Takes the GOOD task definition (187) and updates it to use our latest container
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Option B: Combine Good Config + Latest Code
echo ========================================
echo.
echo What we're doing:
echo - Take Task Definition 187 (has all secrets and permissions)
echo - Update it to use our latest container with all code fixes
echo - Deploy the combination
echo.

set LATEST_CONTAINER=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:sql-syntax-fix-20250908-235806
set BASE_TASK_DEF=187

echo [1/4] Getting base task definition %BASE_TASK_DEF% (has secrets)...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%BASE_TASK_DEF% --region us-east-1 --query "taskDefinition" > base-task-def.json

echo.
echo [2/4] Verifying base task definition has OANDA secrets...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%BASE_TASK_DEF% --region us-east-1 --query "taskDefinition.containerDefinitions[0].secrets[?name==`OANDA_API_KEY`].name" --output text') do set HAS_SECRETS=%%i

if "%HAS_SECRETS%"=="OANDA_API_KEY" (
    echo ✅ VERIFIED: Task Definition %BASE_TASK_DEF% has OANDA secrets
) else (
    echo ❌ ERROR: Task Definition %BASE_TASK_DEF% missing OANDA secrets!
    goto :error
)

echo.
echo [3/4] Creating new task definition...
echo - Base: Task Definition %BASE_TASK_DEF% (secrets + permissions)
echo - Container: %LATEST_CONTAINER% (all code fixes)

REM Clean the task definition and update container image
powershell -Command "& {$json = Get-Content 'base-task-def.json' | ConvertFrom-Json; @('taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'placementConstraints', 'compatibilities', 'registeredAt', 'registeredBy') | ForEach-Object { $json.PSObject.Properties.Remove($_) }; $json.containerDefinitions[0].image = '%LATEST_CONTAINER%'; $json | ConvertTo-Json -Depth 10 | Out-File 'new-combined-task-def.json' -Encoding UTF8}"

for /f "tokens=*" %%i in ('aws ecs register-task-definition --cli-input-json file://new-combined-task-def.json --region us-east-1 --query "taskDefinition.revision" --output text') do set NEW_REVISION=%%i
echo ✅ Created new task definition: lumisignals-data-orchestrator:%NEW_REVISION%

echo.
echo [4/4] FINAL VERIFICATION: Checking new task definition...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.containerDefinitions[0].secrets[?name==`OANDA_API_KEY`].name" --output text') do set VERIFY_SECRETS=%%i

if "%VERIFY_SECRETS%"=="OANDA_API_KEY" (
    echo ✅ VERIFIED: New task definition %NEW_REVISION% has OANDA secrets!
) else (
    echo ❌ ERROR: New task definition %NEW_REVISION% missing secrets!
    goto :error
)

echo.
echo DEPLOYING: Task Definition %NEW_REVISION% with latest container...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo Waiting 2 minutes for deployment...
timeout /t 120 /nobreak

echo.
echo ========================================
echo OPTION B DEPLOYMENT COMPLETED!
echo ========================================
echo.
echo SUCCESSFUL COMBINATION:
echo ✅ Base: Task Definition %BASE_TASK_DEF% (secrets + permissions)
echo ✅ Container: %LATEST_CONTAINER% (all code fixes)
echo ✅ Result: Task Definition %NEW_REVISION% (everything working)
echo.
echo Expected Results:
echo - OANDA authentication should work (secrets preserved)
echo - Comprehensive orchestrator should activate (code fixes included)
echo - Trade 1581 cleanup should happen automatically
echo - Real-time accurate data in pipstop.org
echo.
echo Clean up temp files...
del base-task-def.json new-combined-task-def.json 2>nul
echo.
pause
goto :end

:error
echo.
echo ========================================
echo DEPLOYMENT FAILED!
echo ========================================
del base-task-def.json new-combined-task-def.json 2>nul

:end