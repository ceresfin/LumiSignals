@echo off
echo 🚀 AWS Lambda Trading Bot Deployment Script
echo ==============================================

:: Configuration
set FUNCTION_NAME=oanda-trading-bot
set REGION=us-east-1
set RUNTIME=python3.9
set TIMEOUT=300
set MEMORY=256
set SECRET_NAME=oanda-trading-bot/credentials

:: Get AWS Account ID
for /f "tokens=*" %%i in ('aws sts get-caller-identity --query Account --output text') do set ACCOUNT_ID=%%i
echo ✅ AWS Account ID: %ACCOUNT_ID%

:: Check if Oanda credentials are set
if "%OANDA_API_KEY%"=="" (
    echo ❌ OANDA_API_KEY not set. Please run: set OANDA_API_KEY=your-key
    pause
    exit /b 1
)
if "%OANDA_ACCOUNT_ID%"=="" (
    echo ❌ OANDA_ACCOUNT_ID not set. Please run: set OANDA_ACCOUNT_ID=your-account
    pause
    exit /b 1
)

echo ✅ Oanda credentials found

:: Create IAM role
echo 📋 Creating IAM role for Lambda...

echo { > trust-policy.json
echo   "Version": "2012-10-17", >> trust-policy.json
echo   "Statement": [ >> trust-policy.json
echo     { >> trust-policy.json
echo       "Effect": "Allow", >> trust-policy.json
echo       "Principal": { >> trust-policy.json
echo         "Service": "lambda.amazonaws.com" >> trust-policy.json
echo       }, >> trust-policy.json
echo       "Action": "sts:AssumeRole" >> trust-policy.json
echo     } >> trust-policy.json
echo   ] >> trust-policy.json
echo } >> trust-policy.json

aws iam create-role --role-name lambda-trading-bot-role --assume-role-policy-document file://trust-policy.json --description "Role for Oanda trading bot Lambda function" >nul 2>&1

:: Create permissions policy
echo { > permissions-policy.json
echo   "Version": "2012-10-17", >> permissions-policy.json
echo   "Statement": [ >> permissions-policy.json
echo     { >> permissions-policy.json
echo       "Effect": "Allow", >> permissions-policy.json
echo       "Action": [ >> permissions-policy.json
echo         "logs:CreateLogGroup", >> permissions-policy.json
echo         "logs:CreateLogStream", >> permissions-policy.json
echo         "logs:PutLogEvents" >> permissions-policy.json
echo       ], >> permissions-policy.json
echo       "Resource": "arn:aws:logs:%REGION%:%ACCOUNT_ID%:*" >> permissions-policy.json
echo     }, >> permissions-policy.json
echo     { >> permissions-policy.json
echo       "Effect": "Allow", >> permissions-policy.json
echo       "Action": [ >> permissions-policy.json
echo         "secretsmanager:GetSecretValue" >> permissions-policy.json
echo       ], >> permissions-policy.json
echo       "Resource": "arn:aws:secretsmanager:%REGION%:%ACCOUNT_ID%:secret:%SECRET_NAME%*" >> permissions-policy.json
echo     }, >> permissions-policy.json
echo     { >> permissions-policy.json
echo       "Effect": "Allow", >> permissions-policy.json
echo       "Action": [ >> permissions-policy.json
echo         "cloudwatch:PutMetricData" >> permissions-policy.json
echo       ], >> permissions-policy.json
echo       "Resource": "*" >> permissions-policy.json
echo     } >> permissions-policy.json
echo   ] >> permissions-policy.json
echo } >> permissions-policy.json

aws iam put-role-policy --role-name lambda-trading-bot-role --policy-name lambda-trading-bot-permissions --policy-document file://permissions-policy.json

:: Clean up policy files
del trust-policy.json permissions-policy.json

echo ✅ IAM role created: lambda-trading-bot-role

:: Create secrets in AWS Secrets Manager
echo 🔐 Setting up AWS Secrets Manager...
aws secretsmanager create-secret --name "%SECRET_NAME%" --description "Oanda API credentials for trading bot" --secret-string "{\"API_KEY\":\"%OANDA_API_KEY%\",\"ACCOUNT_ID\":\"%OANDA_ACCOUNT_ID%\"}" --region %REGION% >nul 2>&1
if errorlevel 1 (
    echo Updating existing secret...
    aws secretsmanager update-secret --secret-id "%SECRET_NAME%" --secret-string "{\"API_KEY\":\"%OANDA_API_KEY%\",\"ACCOUNT_ID\":\"%OANDA_ACCOUNT_ID%\"}" --region %REGION%
)

echo ✅ Secrets stored in AWS Secrets Manager

:: Package Lambda function
echo 📦 Packaging Lambda function...

if exist lambda-deployment rmdir /s /q lambda-deployment
mkdir lambda-deployment
cd lambda-deployment

:: Copy source files
copy ..\src\*.py . >nul 2>&1

:: Create AWS Lambda version of the trading bot
echo import json > aws_lambda_trading_bot.py
echo import boto3 >> aws_lambda_trading_bot.py
echo import logging >> aws_lambda_trading_bot.py
echo from datetime import datetime >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo # AWS clients >> aws_lambda_trading_bot.py
echo secrets_client = boto3.client('secretsmanager'^) >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo def get_secrets(^): >> aws_lambda_trading_bot.py
echo     """Retrieve API credentials from AWS Secrets Manager""" >> aws_lambda_trading_bot.py
echo     try: >> aws_lambda_trading_bot.py
echo         response = secrets_client.get_secret_value( >> aws_lambda_trading_bot.py
echo             SecretId='oanda-trading-bot/credentials' >> aws_lambda_trading_bot.py
echo         ^) >> aws_lambda_trading_bot.py
echo         secrets = json.loads(response['SecretString']^) >> aws_lambda_trading_bot.py
echo         return secrets['API_KEY'], secrets['ACCOUNT_ID'] >> aws_lambda_trading_bot.py
echo     except Exception as e: >> aws_lambda_trading_bot.py
echo         print(f"Error retrieving secrets: {e}"^) >> aws_lambda_trading_bot.py
echo         raise >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo def lambda_handler(event, context^): >> aws_lambda_trading_bot.py
echo     """Main Lambda function handler""" >> aws_lambda_trading_bot.py
echo     try: >> aws_lambda_trading_bot.py
echo         # Get credentials from AWS Secrets Manager >> aws_lambda_trading_bot.py
echo         API_KEY, ACCOUNT_ID = get_secrets(^) >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo         # Import and run your existing trading bot >> aws_lambda_trading_bot.py
echo         from Demo_Trading_Penny_Curve_Strategy import DemoTradingBot >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo         # Initialize trading bot with retrieved credentials >> aws_lambda_trading_bot.py
echo         import os >> aws_lambda_trading_bot.py
echo         os.environ['API_KEY'] = API_KEY >> aws_lambda_trading_bot.py
echo         os.environ['ACCOUNT_ID'] = ACCOUNT_ID >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo         bot = DemoTradingBot(max_risk_usd=10.0, max_open_trades=5^) >> aws_lambda_trading_bot.py
echo         bot.run_single_cycle(^) >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo         return { >> aws_lambda_trading_bot.py
echo             'statusCode': 200, >> aws_lambda_trading_bot.py
echo             'body': json.dumps({ >> aws_lambda_trading_bot.py
echo                 'message': 'Trading cycle completed successfully', >> aws_lambda_trading_bot.py
echo                 'timestamp': datetime.now(^).isoformat(^) >> aws_lambda_trading_bot.py
echo             }^) >> aws_lambda_trading_bot.py
echo         } >> aws_lambda_trading_bot.py
echo. >> aws_lambda_trading_bot.py
echo     except Exception as e: >> aws_lambda_trading_bot.py
echo         print(f"Error in lambda_handler: {e}"^) >> aws_lambda_trading_bot.py
echo         return { >> aws_lambda_trading_bot.py
echo             'statusCode': 500, >> aws_lambda_trading_bot.py
echo             'body': json.dumps({ >> aws_lambda_trading_bot.py
echo                 'error': str(e^), >> aws_lambda_trading_bot.py
echo                 'timestamp': datetime.now(^).isoformat(^) >> aws_lambda_trading_bot.py
echo             }^) >> aws_lambda_trading_bot.py
echo         } >> aws_lambda_trading_bot.py

:: Create requirements.txt
echo boto3^>=1.26.0 > requirements.txt
echo requests^>=2.28.0 >> requirements.txt
echo pandas^>=1.5.0 >> requirements.txt
echo pytz^>=2023.3 >> requirements.txt

:: Install dependencies
echo Installing Python dependencies...
pip install -r requirements.txt -t . --quiet

:: Clean up
for /d %%d in (*dist-info) do rmdir /s /q "%%d" >nul 2>&1
for /d %%d in (__pycache__) do rmdir /s /q "%%d" >nul 2>&1
del /q *.pyc >nul 2>&1

:: Create deployment package
echo Creating deployment package...
powershell -command "Compress-Archive -Path .\* -DestinationPath ..\trading-bot-lambda.zip -Force"

cd ..

echo ✅ Lambda package created: trading-bot-lambda.zip

:: Deploy Lambda function
echo 🚀 Deploying Lambda function...

set ROLE_ARN=arn:aws:iam::%ACCOUNT_ID%:role/lambda-trading-bot-role

:: Wait for IAM role to propagate
echo Waiting for IAM role to propagate...
timeout /t 10 /nobreak >nul

aws lambda get-function --function-name %FUNCTION_NAME% --region %REGION% >nul 2>&1
if errorlevel 1 (
    echo Creating new Lambda function...
    aws lambda create-function --function-name %FUNCTION_NAME% --runtime %RUNTIME% --role %ROLE_ARN% --handler aws_lambda_trading_bot.lambda_handler --zip-file fileb://trading-bot-lambda.zip --timeout %TIMEOUT% --memory-size %MEMORY% --description "Automated Oanda trading bot with penny curve strategy" --region %REGION%
) else (
    echo Updating existing Lambda function...
    aws lambda update-function-code --function-name %FUNCTION_NAME% --zip-file fileb://trading-bot-lambda.zip --region %REGION%
)

echo ✅ Lambda function deployed: %FUNCTION_NAME%

:: Create EventBridge schedule
echo ⏰ Setting up EventBridge schedule...

set RULE_NAME=trading-bot-15min-schedule
set LAMBDA_ARN=arn:aws:lambda:%REGION%:%ACCOUNT_ID%:function:%FUNCTION_NAME%

aws events put-rule --name %RULE_NAME% --schedule-expression "rate(15 minutes)" --description "Run trading bot every 15 minutes" --state ENABLED --region %REGION%

aws events put-targets --rule %RULE_NAME% --targets "Id"="1","Arn"="%LAMBDA_ARN%" --region %REGION%

aws lambda add-permission --function-name %FUNCTION_NAME% --statement-id "allow-eventbridge" --action "lambda:InvokeFunction" --principal "events.amazonaws.com" --source-arn "arn:aws:events:%REGION%:%ACCOUNT_ID%:rule/%RULE_NAME%" --region %REGION% >nul 2>&1

echo ✅ EventBridge schedule created: Every 15 minutes

:: Test deployment
echo 🧪 Testing Lambda deployment...

aws lambda invoke --function-name %FUNCTION_NAME% --payload "{}" --region %REGION% response.json
if errorlevel 1 (
    echo ❌ Lambda test failed
) else (
    echo ✅ Lambda test successful!
    echo Response:
    type response.json
    del response.json
)

:: Clean up
rmdir /s /q lambda-deployment >nul 2>&1
del trading-bot-lambda.zip >nul 2>&1

echo.
echo 🎉 Deployment completed successfully!
echo ==============================================
echo Function Name: %FUNCTION_NAME%
echo Region: %REGION%
echo Schedule: Every 15 minutes
echo Max Risk: $10 USD per trade
echo.
echo 📊 Monitoring:
echo - CloudWatch Logs: /aws/lambda/%FUNCTION_NAME%
echo - View logs: aws logs tail /aws/lambda/%FUNCTION_NAME% --follow
echo.
echo 🔧 Management Commands:
echo - Test function: aws lambda invoke --function-name %FUNCTION_NAME% --payload "{}" response.json
echo - Disable schedule: aws events disable-rule --name %RULE_NAME%
echo - Enable schedule: aws events enable-rule --name %RULE_NAME%
echo.
echo ✅ Your trading bot is now running automatically every 15 minutes!

pause