#!/usr/bin/env python3
"""
Deploy complete package using S3 (based on methodology document)
Creates and uploads complete package with fibonacci level enhancements
"""

import boto3
import zipfile
import os
import time

def create_complete_package_zip():
    """Create the complete package zip file"""
    zip_filename = "complete_package_deployment_fibonacci_levels.zip"
    package_dir = "complete_package"
    
    if not os.path.exists(package_dir):
        print(f"❌ {package_dir} directory not found")
        return None
    
    print("📦 Creating complete package with Fibonacci level enhancements...")
    
    # Create zip from complete_package directory
    with zipfile.ZipFile(zip_filename, 'w') as zipf:
        for root, dirs, files in os.walk(package_dir):
            for file in files:
                file_path = os.path.join(root, file)
                # Remove the package_dir prefix from the archive path
                arcname = os.path.relpath(file_path, package_dir)
                zipf.write(file_path, arcname)
        
        # Also add our updated lambda_function.py and fibonacci_strategy_naming.py from root
        if os.path.exists('lambda_function.py'):
            zipf.write('lambda_function.py')
            print("✅ Added updated lambda_function.py")
        
        if os.path.exists('fibonacci_strategy_naming.py'):
            zipf.write('fibonacci_strategy_naming.py')
            print("✅ Added fibonacci_strategy_naming.py")
    
    print(f"✅ Created complete package: {zip_filename}")
    return zip_filename

def deploy_s3_complete():
    """Deploy using S3 as mentioned in methodology"""
    
    print("🚀 Deploying complete package via S3...")
    
    # Create the zip file
    zip_filename = create_complete_package_zip()
    if not zip_filename:
        return False
    
    # Check size
    size_mb = os.path.getsize(zip_filename) / (1024 * 1024)
    print(f"📦 Package size: {size_mb:.1f} MB")
    
    try:
        s3_client = boto3.client('s3', region_name='us-east-1')
        lambda_client = boto3.client('lambda', region_name='us-east-1')
        
        # Use the existing bucket (confirmed to exist)
        bucket_name = 'lumisignals-backups-e5558a85'
        s3_key = f'lambda/{zip_filename}'
        
        # Upload to S3
        print(f"📤 Uploading to S3: s3://{bucket_name}/{s3_key}")
        s3_client.upload_file(zip_filename, bucket_name, s3_key)
        print("✅ Uploaded to S3 successfully")
        
        # Update Lambda from S3
        print("🔄 Updating Lambda function from S3...")
        response = lambda_client.update_function_code(
            FunctionName='lumisignals-signal-analytics-api',
            S3Bucket=bucket_name,
            S3Key=s3_key
        )
        
        print("✅ Lambda deployment via S3 successful!")
        print(f"   Function: {response['FunctionName']}")
        print(f"   Last Modified: {response['LastModified']}")
        print(f"   Code Size: {response.get('CodeSize', 'Unknown')} bytes")
        
        # Clean up local zip file
        os.remove(zip_filename)
        print(f"🧹 Cleaned up local {zip_filename}")
        
        return True
        
    except Exception as e:
        print(f"❌ S3 deployment failed: {e}")
        # Clean up on failure
        if os.path.exists(zip_filename):
            os.remove(zip_filename)
        return False

if __name__ == "__main__":
    deploy_s3_complete()