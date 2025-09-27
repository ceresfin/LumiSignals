#!/usr/bin/env python3
"""
Deploy signal-analytics-api Lambda with trading core modules
"""

import os
import shutil
import zipfile
import boto3
from datetime import datetime

def create_deployment_package():
    """Create a complete deployment package with trading core modules"""
    
    # Create package directory
    package_dir = "/mnt/c/Users/sonia/LumiSignals/infrastructure/lambda/signal-analytics-api/complete_package"
    if os.path.exists(package_dir):
        shutil.rmtree(package_dir)
    os.makedirs(package_dir)
    
    # Copy main Lambda function
    shutil.copy2("lambda_function.py", package_dir)
    
    # Copy fibonacci strategy naming module (required for lambda_function.py)
    shutil.copy2("fibonacci_strategy_naming.py", package_dir)
    
    # Copy Redis module
    if os.path.exists("redis"):
        shutil.copytree("redis", os.path.join(package_dir, "redis"))
        print("✅ Redis module copied")
    
    # Install numpy properly using pip to avoid source file issues
    print("📦 Installing numpy via pip...")
    import subprocess
    subprocess.run([
        "pip", "install", "--target", package_dir, 
        "--platform", "manylinux2014_x86_64", 
        "--implementation", "cp",
        "--python-version", "3.11",
        "--only-binary=:all:",
        "--upgrade",
        "numpy==1.26.4"
    ], check=True)
    print("✅ NumPy installed via pip")
    
    # Copy trading core modules
    if os.path.exists("lumisignals_trading_core"):
        shutil.copytree("lumisignals_trading_core", os.path.join(package_dir, "lumisignals_trading_core"))
        print("✅ LumiSignals trading core modules copied")
    
    # Copy pytz module (required by trading core)
    if os.path.exists("pytz"):
        shutil.copytree("pytz", os.path.join(package_dir, "pytz"))
        print("✅ pytz module copied")
    
    # Create deployment ZIP
    zip_path = "signal-analytics-complete-with-trading-core.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(package_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arc_name = os.path.relpath(file_path, package_dir)
                zipf.write(file_path, arc_name)
    
    print(f"✅ Created deployment package: {zip_path}")
    return zip_path

def deploy_lambda(zip_path):
    """Deploy the Lambda function"""
    lambda_client = boto3.client('lambda', region_name='us-east-1')
    s3_client = boto3.client('s3', region_name='us-east-1')
    
    function_name = 'lumisignals-signal-analytics-api'
    bucket_name = 'lumisignals-lambda-deployments'
    s3_key = f'signal-analytics/{os.path.basename(zip_path)}'
    
    try:
        # Check file size
        file_size = os.path.getsize(zip_path)
        size_mb = file_size / 1024 / 1024
        print(f"Package size: {size_mb:.1f} MB")
        
        if size_mb > 50:  # If larger than 50MB, use S3
            print("📦 Package too large for direct upload, using S3...")
            
            # Upload to S3
            print(f"📤 Uploading to S3: s3://{bucket_name}/{s3_key}")
            s3_client.upload_file(zip_path, bucket_name, s3_key)
            print("✅ Uploaded to S3")
            
            # Update Lambda from S3
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                S3Bucket=bucket_name,
                S3Key=s3_key
            )
        else:
            # Direct upload for smaller files
            print("📤 Direct upload to Lambda...")
            with open(zip_path, 'rb') as f:
                zip_content = f.read()
            
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=zip_content
            )
        
        print(f"✅ Lambda function updated successfully")
        print(f"Version: {response['Version']}")
        print(f"CodeSize: {response.get('CodeSize', 0) / 1024 / 1024:.1f} MB")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to deploy Lambda: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Creating deployment package with trading core modules...")
    
    # Change to Lambda directory
    os.chdir("/mnt/c/Users/sonia/LumiSignals/infrastructure/lambda/signal-analytics-api")
    
    # Create deployment package
    zip_path = create_deployment_package()
    
    # Deploy to AWS
    print("\n🚀 Deploying to AWS Lambda...")
    success = deploy_lambda(zip_path)
    
    if success:
        print("\n✅ Deployment complete! The flexible Fibonacci analysis should now work.")
        print("🎯 Both Fixed and ATR modes are now available.")
    else:
        print("\n❌ Deployment failed. Check AWS credentials and permissions.")