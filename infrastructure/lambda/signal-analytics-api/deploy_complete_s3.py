#!/usr/bin/env python3
"""
Deploy complete package via S3 (required for packages >70MB)
Following ANALYTICS_DEVELOPMENT_METHODOLOGY.md guidelines
"""

import boto3
import zipfile
import os
from datetime import datetime

def deploy_complete_package_via_s3():
    """Deploy complete package via S3 to handle large deployment size"""
    
    print("🚀 Deploying complete package via S3...")
    print("📋 Following ANALYTICS_DEVELOPMENT_METHODOLOGY.md deployment process")
    
    # Step 1: Copy updated files to complete_package
    print("\n📁 Step 1: Updating complete_package directory...")
    if os.path.exists('lambda_function.py'):
        os.system('cp lambda_function.py complete_package/lambda_function.py')
        print("✅ Copied lambda_function.py to complete_package/")
    
    if os.path.exists('fibonacci_strategy_naming.py'):
        os.system('cp fibonacci_strategy_naming.py complete_package/fibonacci_strategy_naming.py')
        print("✅ Copied fibonacci_strategy_naming.py to complete_package/")
    
    # Step 2: Create deployment package
    print("\n📦 Step 2: Creating deployment package...")
    package_dir = "complete_package"
    if not os.path.exists(package_dir):
        print(f"❌ {package_dir} directory not found")
        return False
    
    zip_filename = "complete_package_deployment.zip"
    
    # Create zip from complete_package directory
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(package_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                file_path = os.path.join(root, file)
                # Remove the package_dir prefix from the archive path
                arcname = os.path.relpath(file_path, package_dir)
                zipf.write(file_path, arcname)
    
    print(f"✅ Created deployment package: {zip_filename}")
    
    # Get file size for verification
    size_mb = os.path.getsize(zip_filename) / (1024 * 1024)
    print(f"📊 Package size: {size_mb:.1f} MB")
    
    if size_mb < 70:
        print("⚠️  Package smaller than expected. Should be ~81MB with all dependencies.")
        print("    Ensure numpy, pandas, redis, pytz are all included.")
    
    # Step 3: Upload to S3
    print("\n☁️  Step 3: Uploading to S3...")
    s3_client = boto3.client('s3', region_name='us-east-1')
    bucket_name = 'lumisignals-backups-e5558a85'
    
    # Create S3 key with timestamp
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    s3_key = f'lambda/signal-analytics-complete-{timestamp}.zip'
    
    try:
        s3_client.upload_file(zip_filename, bucket_name, s3_key)
        print(f"✅ Uploaded to S3: s3://{bucket_name}/{s3_key}")
    except Exception as e:
        print(f"❌ S3 upload failed: {e}")
        return False
    
    # Step 4: Deploy to Lambda from S3
    print("\n🚀 Step 4: Deploying to Lambda from S3...")
    lambda_client = boto3.client('lambda', region_name='us-east-1')
    
    try:
        response = lambda_client.update_function_code(
            FunctionName='lumisignals-signal-analytics-api',
            S3Bucket=bucket_name,
            S3Key=s3_key
        )
        
        print("✅ Lambda function updated successfully!")
        print(f"   Version: {response['Version']}")
        print(f"   Last Modified: {response['LastModified']}")
        print(f"   Code Size: {response.get('CodeSize', 'Unknown')} bytes")
        
        # Clean up local zip
        os.remove(zip_filename)
        
        # Step 5: Prompt for testing
        print("\n📋 Step 5: MANDATORY - Test deployment immediately")
        print("Run: python3 test_deployed_fibonacci_lambda.py")
        print("Or test specific endpoint:")
        print("python3 test_trade_setups_endpoint.py")
        
        return True
        
    except Exception as e:
        print(f"❌ Lambda deployment failed: {e}")
        if os.path.exists(zip_filename):
            os.remove(zip_filename)
        return False

if __name__ == "__main__":
    print("=" * 80)
    print("COMPLETE PACKAGE DEPLOYMENT - Following S3 deployment process")
    print("Package includes: numpy, pandas, redis, pytz, lumisignals_trading_core")
    print("=" * 80)
    
    success = deploy_complete_package_via_s3()
    
    if success:
        print("\n" + "=" * 80)
        print("✅ DEPLOYMENT SUCCESSFUL")
        print("⚠️  IMPORTANT: Test immediately before committing to Git")
        print("=" * 80)
    else:
        print("\n❌ DEPLOYMENT FAILED")