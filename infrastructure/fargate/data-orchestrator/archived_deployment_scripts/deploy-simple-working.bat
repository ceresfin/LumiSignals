@echo off
REM Super Simple: Just switch back to the working task definition
REM We'll deal with updating the container later
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Super Simple: Use Working Task Definition
echo ========================================
echo.
echo Current problem: Task Definition 190 has no secrets
echo Solution: Switch to Task Definition 187 which has secrets
echo Trade-off: Uses older container, but OANDA will work
echo.

echo [1/2] Switching to Task Definition 187 (has secrets)...
echo This will use an older container but with working OANDA authentication

aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:187 --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [2/2] Waiting 2 minutes for deployment...
timeout /t 120 /nobreak

echo.
echo ========================================
echo SIMPLE SWITCH COMPLETED!
echo ========================================
echo.
echo What Changed:
echo - Now using Task Definition 187 (has OANDA secrets)
echo - OANDA authentication should work
echo - Comprehensive orchestrator may not have all latest fixes
echo.
echo Expected Results:
echo - No more "Illegal header value" errors
echo - OANDA data collection should work
echo - May need to rebuild container later with latest fixes
echo.
echo CHECKING LOGS...
powershell -Command "Start-Sleep -Seconds 10"
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream.txt
set /p STREAM_NAME=<latest-stream.txt
echo.
echo Recent log messages:
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-5:].message" --output text
echo.
del latest-stream.txt
pause