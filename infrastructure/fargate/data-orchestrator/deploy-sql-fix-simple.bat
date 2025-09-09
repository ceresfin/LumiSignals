@echo off
REM Deploy Data Orchestrator with SQL Syntax Fix (Simplified)
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo LumiSignals Data Orchestrator Deployment
echo With SQL Syntax Fix (SIMPLIFIED)
echo ========================================
echo.

REM Generate timestamp for unique container tag
for /f "tokens=*" %%i in ('powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"') do set TIMESTAMP=%%i
set IMAGE_TAG=816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:sql-syntax-fix-%TIMESTAMP%

echo [1/8] Building new container with SQL syntax fix...
echo Image tag: %IMAGE_TAG%
docker build --no-cache --build-arg VERSION=sql-syntax-fix-%TIMESTAMP% --build-arg CACHEBUST=%TIMESTAMP% -t %IMAGE_TAG% . || goto :error

echo.
echo [2/8] Getting ECR login and pushing...
aws ecr get-login-password --region us-east-1 > %TEMP%\ecr-token.txt || goto :error
docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com < %TEMP%\ecr-token.txt || goto :error
del %TEMP%\ecr-token.txt
docker push %IMAGE_TAG% || goto :error

echo.
echo [3/8] Getting current task definition...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 --query "taskDefinition" > task-def.json

echo.
echo [4/8] Creating new task definition manually...
echo {> new-task-def.json
echo   "family": "lumisignals-data-orchestrator",>> new-task-def.json
echo   "taskRoleArn": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-role",>> new-task-def.json
echo   "executionRoleArn": "arn:aws:iam::816945674467:role/lumisignals-ecs-task-execution-role",>> new-task-def.json
echo   "networkMode": "awsvpc",>> new-task-def.json
echo   "cpu": "2048",>> new-task-def.json
echo   "memory": "4096",>> new-task-def.json
echo   "requiresCompatibilities": ["FARGATE"],>> new-task-def.json
echo   "containerDefinitions": [>> new-task-def.json
echo     {>> new-task-def.json
echo       "name": "lumisignals-data-orchestrator",>> new-task-def.json
echo       "image": "%IMAGE_TAG%",>> new-task-def.json
echo       "essential": true,>> new-task-def.json
echo       "portMappings": [>> new-task-def.json
echo         {>> new-task-def.json
echo           "containerPort": 8080,>> new-task-def.json
echo           "protocol": "tcp">> new-task-def.json
echo         }>> new-task-def.json
echo       ],>> new-task-def.json
echo       "logConfiguration": {>> new-task-def.json
echo         "logDriver": "awslogs",>> new-task-def.json
echo         "options": {>> new-task-def.json
echo           "awslogs-group": "/ecs/lumisignals-data-orchestrator",>> new-task-def.json
echo           "awslogs-region": "us-east-1",>> new-task-def.json
echo           "awslogs-stream-prefix": "ecs">> new-task-def.json
echo         }>> new-task-def.json
echo       }>> new-task-def.json
echo     }>> new-task-def.json
echo   ]>> new-task-def.json
echo }>> new-task-def.json

echo.
echo [5/8] Registering new task definition...
for /f "tokens=*" %%i in ('aws ecs register-task-definition --cli-input-json file://new-task-def.json --region us-east-1 --query "taskDefinition.revision" --output text') do set NEW_REVISION=%%i
echo New task definition revision: %NEW_REVISION%

echo.
echo [6/8] Stopping current service...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --desired-count 0 --region us-east-1
timeout /t 15 /nobreak

echo.
echo [7/8] Starting service with new task definition...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [8/8] Waiting 3 minutes for startup...
timeout /t 180 /nobreak

echo.
echo CHECKING LOGS FOR SUCCESS...
aws logs filter-log-events --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --start-time %((Get-Date).AddMinutes(-3) | Get-Date -UFormat %%s) --query "events[].message" --output text | findstr /C:"Comprehensive orchestrator completed successfully" /C:"🧹"

echo.
echo DEPLOYMENT COMPLETED!
echo Container: %IMAGE_TAG%
echo Task Revision: %NEW_REVISION%
echo.
echo Clean up temp files...
del task-def.json new-task-def.json 2>nul

goto :end

:error
echo.
echo DEPLOYMENT FAILED!
del %TEMP%\ecr-token.txt task-def.json new-task-def.json 2>nul

:end
pause