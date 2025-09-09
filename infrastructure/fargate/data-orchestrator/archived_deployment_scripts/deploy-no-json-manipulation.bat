@echo off
REM Ultra Simple: Just switch to Task Definition 187 (no JSON manipulation)
REM We know TD 187 has secrets and works, we'll upgrade container separately later
REM Run this from: C:\Users\sonia\LumiSignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo Ultra Simple Fix: Use Working Task Definition
echo NO PowerShell JSON manipulation required
echo ========================================
echo.
echo Problem: PowerShell JSON parsing keeps failing
echo Solution: Use Task Definition 187 which we KNOW has secrets
echo Trade-off: Older container, but OANDA authentication will work
echo.

echo [1/2] Switching to Task Definition 187 (has OANDA secrets)...
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:187 --desired-count 1 --force-new-deployment --region us-east-1

echo.
echo [2/2] Waiting 4 minutes for deployment (automated wait)...
timeout /t 240 /nobreak

echo.
echo ========================================
echo ULTRA SIMPLE FIX COMPLETED!
echo ========================================
echo.
echo What Changed:
echo - Now using Task Definition 187 (has OANDA secrets)
echo - NO JSON manipulation errors
echo - OANDA authentication should work immediately
echo.
echo Expected Results:
echo - No more "Illegal header value b'Bearer '" errors
echo - OANDA data collection should work
echo - May not have all latest code fixes, but auth will work
echo.

echo AUTOMATIC LOG CHECK (after 4 minutes)...
aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text > latest-stream.txt
set /p STREAM_NAME=<latest-stream.txt
echo.
echo Recent log messages (should show working OANDA auth):
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "%STREAM_NAME%" --region us-east-1 --query "events[-8:].message" --output text
echo.
del latest-stream.txt
pause