@echo off
echo ========================================
echo Robust PostgreSQL Tunnel / Bastion Tool
echo ========================================
echo.
echo Choose an option:
echo 1. Start PostgreSQL tunnel (for pgAdmin)
echo 2. Connect to bastion host (for RDS queries)
echo.
set /p choice="Enter your choice (1 or 2): "

if "%choice%"=="2" goto bastion
if "%choice%"=="1" goto tunnel
echo Invalid choice. Defaulting to tunnel...

:tunnel
REM Kill any existing session manager processes
echo Cleaning up old sessions...
taskkill /F /IM session-manager-plugin.exe 2>nul
timeout /t 2 >nul

echo.
echo Starting fresh tunnel...
echo Host: lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com
echo Local Port: 5433
echo.

REM Set AWS region explicitly
set AWS_DEFAULT_REGION=us-east-1

REM Start tunnel with explicit parameters
aws ssm start-session ^
    --target i-082bf92c7ffb3af30 ^
    --document-name AWS-StartPortForwardingSessionToRemoteHost ^
    --parameters "{\"host\":[\"lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"5433\"]}" ^
    --region us-east-1

echo.
echo Tunnel closed. Press any key to exit...
pause
exit

:bastion
echo.
echo Connecting to bastion host...
echo.
echo Once connected, here are the RDS commands:
echo =========================================
echo.
echo # Quick setup (all in one line):
echo export RDS_HOST="lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com" RDS_USER="lumisignals" RDS_DB="lumisignals_trading" RDS_PASSWORD="LumiSignals2025"
echo.
echo # Check distance_to_entry column:
echo psql -h $RDS_HOST -U $RDS_USER -d $RDS_DB -c "SELECT COUNT(*) as total, COUNT(distance_to_entry) as with_distance, COUNT(CASE WHEN distance_to_entry IS NOT NULL THEN 1 END) as non_null FROM active_trades WHERE state = 'OPEN';"
echo.
echo # Show recent trades:
echo psql -h $RDS_HOST -U $RDS_USER -d $RDS_DB -c "SELECT trade_id, instrument, pips_moved, distance_to_entry, TO_CHAR(update_timestamp, 'MM/DD HH24:MI') as updated FROM active_trades WHERE state = 'OPEN' ORDER BY update_timestamp DESC LIMIT 10;"
echo.
echo # Check for ANY non-null distance values:
echo psql -h $RDS_HOST -U $RDS_USER -d $RDS_DB -c "SELECT trade_id, distance_to_entry FROM active_trades WHERE distance_to_entry IS NOT NULL LIMIT 5;"
echo.
echo =========================================
echo.

REM Connect to bastion
aws ssm start-session --target i-04194c32a766994c6 --region us-east-1

echo.
echo Session ended. Press any key to exit...
pause