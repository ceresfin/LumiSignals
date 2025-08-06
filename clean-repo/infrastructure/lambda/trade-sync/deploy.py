#!/usr/bin/env python3
"""
Deploy the trade-sync Lambda function to AWS
"""

import os
import sys
import json
import boto3
import zipfile
import subprocess
from datetime import datetime

def create_lambda_package():
    """Create a deployment package for Lambda"""
    
    print("📦 Creating Lambda deployment package...")
    
    # Create a temporary directory for the package
    package_dir = "/tmp/lambda-package"
    os.makedirs(package_dir, exist_ok=True)
    
    # Install dependencies
    print("📥 Installing dependencies...")
    subprocess.run([
        sys.executable, "-m", "pip", "install", 
        "-r", "requirements.txt", 
        "-t", package_dir
    ], check=True)
    
    # Copy the trade-sync code
    print("📋 Copying trade-sync code...")
    subprocess.run([
        "cp", "-r", 
        ".", package_dir + "/."
    ], check=True)
    
    # Create the zip file
    zip_path = "/tmp/trade-sync-lambda.zip"
    print(f"🗜️  Creating zip file: {zip_path}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(package_dir):
            for file in files:
                if not file.endswith('.pyc') and '__pycache__' not in root:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, package_dir)
                    zipf.write(file_path, arcname)
    
    # Get file size
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"📏 Package size: {size_mb:.2f} MB")
    
    return zip_path

def deploy_to_lambda(zip_path, function_name="oanda-airtable-sync"):
    """Deploy the package to AWS Lambda"""
    
    print(f"🚀 Deploying to Lambda function: {function_name}")
    
    # Create Lambda client
    lambda_client = boto3.client('lambda', region_name='us-east-1')
    
    # Read the zip file
    with open(zip_path, 'rb') as f:
        zip_data = f.read()
    
    try:
        # Update the function code
        response = lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=zip_data
        )
        
        print(f"✅ Deployment successful!")
        print(f"   Function ARN: {response['FunctionArn']}")
        print(f"   Last Modified: {response['LastModified']}")
        print(f"   Code Size: {response['CodeSize']} bytes")
        
        return True
        
    except lambda_client.exceptions.ResourceNotFoundException:
        print(f"❌ Lambda function '{function_name}' not found!")
        print("   Please create the function first or specify correct name.")
        return False
        
    except Exception as e:
        print(f"❌ Deployment failed: {str(e)}")
        return False

def update_function_configuration(function_name="oanda-airtable-sync"):
    """Update Lambda function configuration"""
    
    print(f"⚙️  Updating function configuration...")
    
    lambda_client = boto3.client('lambda', region_name='us-east-1')
    
    try:
        response = lambda_client.update_function_configuration(
            FunctionName=function_name,
            Handler='main.lambda_handler',
            Runtime='python3.9',
            Timeout=300,  # 5 minutes
            MemorySize=512,
            Environment={
                'Variables': {
                    'LOG_LEVEL': 'INFO'
                }
            }
        )
        
        print(f"✅ Configuration updated!")
        return True
        
    except Exception as e:
        print(f"❌ Configuration update failed: {str(e)}")
        return False

def main():
    """Main deployment process"""
    
    print("🚀 OANDA-Airtable Trade Sync Lambda Deployment")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists("main.py"):
        print("❌ Error: main.py not found!")
        print("   Please run this script from the trade-sync directory.")
        sys.exit(1)
    
    # Parse command line arguments
    function_name = "oanda-airtable-sync"
    if len(sys.argv) > 1:
        function_name = sys.argv[1]
    
    # Create the deployment package
    zip_path = create_lambda_package()
    
    # Deploy to Lambda
    if deploy_to_lambda(zip_path, function_name):
        # Update configuration
        update_function_configuration(function_name)
        
        print("\n✅ Deployment complete!")
        print(f"   Timestamp: {datetime.now().isoformat()}")
    else:
        print("\n❌ Deployment failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()