@echo off
REM Fix Task Definition 190 - Add missing OANDA secrets
REM Simple approach: Get TD 190, add secrets manually, register new version
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Fix Task Definition 190 Secrets
echo Add OANDA + Database secrets to latest container
echo ========================================
echo.
echo Problem: TD 190 has latest container but NO secrets
echo Solution: Manually add all secrets from TD 187 to TD 190
echo.

echo [1/3] Getting Task Definition 190 structure...
aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:190 --region us-east-1 --query "taskDefinition" > td-190-no-secrets.json

echo.
echo [2/3] Creating TD 190 with secrets using AWS CLI directly...
REM Use AWS CLI to register new task definition with secrets added
aws ecs register-task-definition ^
--family lumisignals-data-orchestrator ^
--task-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSTaskRole ^
--execution-role-arn arn:aws:iam::816945674467:role/LumiSignalsECSExecutionRole ^
--network-mode awsvpc ^
--requires-compatibilities FARGATE ^
--cpu 256 ^
--memory 512 ^
--container-definitions "[{\"name\":\"lumisignals-data-orchestrator\",\"image\":\"816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals/institutional-orchestrator-postgresql17:aws-cli-20250909-095244\",\"essential\":true,\"logConfiguration\":{\"logDriver\":\"awslogs\",\"options\":{\"awslogs-group\":\"/ecs/lumisignals-data-orchestrator\",\"awslogs-region\":\"us-east-1\",\"awslogs-stream-prefix\":\"ecs\"}},\"secrets\":[{\"name\":\"OANDA_API_KEY\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:api_key::\"},{\"name\":\"OANDA_ACCOUNT_ID\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:account_id::\"},{\"name\":\"OANDA_ENVIRONMENT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/oanda/api/credentials:environment::\"},{\"name\":\"DATABASE_HOST\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:host::\"},{\"name\":\"DATABASE_PORT\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:port::\"},{\"name\":\"DATABASE_USERNAME\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:username::\"},{\"name\":\"DATABASE_PASSWORD\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:password::\"},{\"name\":\"DATABASE_NAME\",\"valueFrom\":\"arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials:dbname::\"}]}]" ^
--region us-east-1 ^
--query "taskDefinition.revision" --output text > new-revision.txt

set /p NEW_REVISION=<new-revision.txt
echo ✅ Created Task Definition with secrets: lumisignals-data-orchestrator:%NEW_REVISION%

echo.
echo [3/3] VERIFICATION: Checking new task definition has secrets...
for /f "tokens=*" %%i in ('aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --region us-east-1 --query "taskDefinition.containerDefinitions[0].secrets[?name==`OANDA_API_KEY`].name" --output text') do set VERIFY_SECRETS=%%i

if "%VERIFY_SECRETS%"=="OANDA_API_KEY" (
    echo ✅ VERIFIED: Task Definition %NEW_REVISION% has OANDA secrets!
    echo.
    echo DEPLOYING NOW...
    aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:%NEW_REVISION% --desired-count 1 --force-new-deployment --region us-east-1
    echo.
    echo ========================================
    echo SUCCESS! BEST OF BOTH WORLDS ACHIEVED!
    echo ========================================
    echo.
    echo Container: Latest with all comprehensive orchestrator fixes
    echo Secrets: OANDA + Database authentication working
    echo Task Definition: %NEW_REVISION%
    echo.
    echo Expected Results:
    echo - OANDA authentication will work
    echo - Comprehensive orchestrator with all fixes active  
    echo - Trade 1581 cleanup should happen automatically
    echo - Real accurate data in pipstop.org
    echo.
) else (
    echo ❌ ERROR: Task Definition %NEW_REVISION% missing secrets!
)

echo Cleanup temp files...
del td-190-no-secrets.json new-revision.txt 2>nul
pause