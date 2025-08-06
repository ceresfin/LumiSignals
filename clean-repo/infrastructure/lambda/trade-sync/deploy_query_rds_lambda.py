#!/usr/bin/env python3
"""Deploy Lambda function to query RDS active trades"""

import boto3
import zipfile
import json
import os
import tempfile

def create_lambda_package():
    """Create Lambda deployment package"""
    
    # Create a temporary file for the zip
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
        with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add the main Lambda function
            zf.write('query_rds_active_trades_lambda.py', 'lambda_function.py')
            
        return temp_zip.name

def deploy_lambda():
    """Deploy the Lambda function"""
    
    lambda_client = boto3.client('lambda', region_name='us-east-1')
    
    function_name = 'query-rds-active-trades'
    
    # Create the package
    package_path = create_lambda_package()
    
    try:
    
        # Read the package
        with open(package_path, 'rb') as f:
            zip_content = f.read()
        
        # Check if function exists
        try:
            lambda_client.get_function(FunctionName=function_name)
            function_exists = True
            print(f"Function {function_name} exists, updating...")
        except lambda_client.exceptions.ResourceNotFoundException:
            function_exists = False
            print(f"Function {function_name} does not exist, creating...")
        
        if function_exists:
            # Update existing function
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=zip_content
            )
            print(f"✓ Updated function: {response['FunctionArn']}")
        else:
            # Create new function
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.11',
                Role='arn:aws:iam::816945674467:role/lumisignals-lambda-execution-role',
                Handler='lambda_function.lambda_handler',
                Code={'ZipFile': zip_content},
                Description='Query RDS active_trades table to identify discrepancies',
                Timeout=60,
                MemorySize=128,
                VpcConfig={
                    'SubnetIds': [
                        'subnet-0fd1345a05f2935c3',
                        'subnet-068ceefa7305e16ed'
                    ],
                    'SecurityGroupIds': [
                        'sg-0699c1e575e3272c4'
                    ]
                },
                Environment={
                    'Variables': {
                        'RDS_SECRET_NAME': 'lumisignals/rds/postgresql/credentials'
                    }
                }
            )
            print(f"✓ Created function: {response['FunctionArn']}")
        
        # Test the function
        print("\nTesting the function...")
        test_response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse'
        )
        
        result = json.loads(test_response['Payload'].read())
        print(f"✓ Function test completed with status: {test_response['StatusCode']}")
        
        if 'errorMessage' in result:
            print(f"✗ Function error: {result['errorMessage']}")
        else:
            response_body = json.loads(result.get('body', '{}'))
            if response_body.get('success'):
                analysis = response_body.get('analysis', {})
                print(f"\n📊 RDS Active Trades Analysis:")
                print(f"   Total trades in RDS: {analysis.get('total_trades_in_rds', 'unknown')}")
                print(f"   Expected from OANDA: {analysis.get('expected_trades_from_oanda', 'unknown')}")
                print(f"   Extra trades to remove: {analysis.get('extra_trades_count', 'unknown')}")
                
                if analysis.get('extra_trade_ids'):
                    print(f"   Extra trade IDs: {', '.join(analysis['extra_trade_ids'])}")
                
                return result
            else:
                print(f"✗ Function returned error: {response_body}")
                return result
        
    finally:
        # Clean up temp file
        if os.path.exists(package_path):
            os.remove(package_path)

if __name__ == "__main__":
    result = deploy_lambda()
    
    # Pretty print the full result
    if result:
        print(f"\n{'='*60}")
        print("FULL RESPONSE:")
        print(json.dumps(result, indent=2))