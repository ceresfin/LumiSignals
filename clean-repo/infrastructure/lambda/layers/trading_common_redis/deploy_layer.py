#!/usr/bin/env python3
"""
Deploy trading_common Lambda layer with Redis support to AWS
"""

import boto3
import json
from pathlib import Path

def deploy_trading_common_redis_layer():
    """Deploy the new layer with Redis support"""
    
    layer_dir = Path(__file__).parent
    zip_file = layer_dir / "trading_common_redis_layer.zip"
    
    if not zip_file.exists():
        print(f"❌ ZIP file not found: {zip_file}")
        return False
    
    print("🚀 Deploying trading_common layer with Redis support...")
    
    # Initialize AWS Lambda client
    lambda_client = boto3.client('lambda', region_name='us-east-1')
    
    try:
        # Read the ZIP file
        with open(zip_file, 'rb') as f:
            zip_content = f.read()
        
        print(f"📦 ZIP file size: {len(zip_content) / 1024 / 1024:.2f} MB")
        
        # Publish new layer version
        response = lambda_client.publish_layer_version(
            LayerName='trading_common_redis',
            Description='Common trading utilities with Redis support for Lambda functions',
            Content={
                'ZipFile': zip_content
            },
            CompatibleRuntimes=['python3.9', 'python3.10', 'python3.11', 'python3.12'],
            CompatibleArchitectures=['x86_64']
        )
        
        layer_arn = response['LayerArn']
        layer_version = response['Version']
        
        print(f"✅ Layer deployed successfully!")
        print(f"   Layer ARN: {layer_arn}")
        print(f"   Version: {layer_version}")
        print(f"   Full ARN: {layer_arn}:{layer_version}")
        
        # Save layer info for easy reference
        layer_info = {
            'layer_name': 'trading_common_redis',
            'layer_arn': layer_arn,
            'version': layer_version,
            'full_arn': f"{layer_arn}:{layer_version}",
            'compatible_runtimes': ['python3.9', 'python3.10', 'python3.11', 'python3.12'],
            'packages_included': [
                'boto3>=1.28.0',
                'pytz>=2023.3', 
                'typing-extensions>=4.7.0',
                'requests>=2.32.0',
                'redis>=4.5.0',
                'oanda_api.py',
                'metadata_storage.py',
                'momentum_calculator.py',
                'redis_integration.py'
            ]
        }
        
        with open(layer_dir / 'layer_info.json', 'w') as f:
            json.dump(layer_info, f, indent=2)
        
        print("📝 Layer info saved to layer_info.json")
        
        return True
        
    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        return False

if __name__ == "__main__":
    success = deploy_trading_common_redis_layer()
    if success:
        print("🎉 Ready to update Lambda functions with new layer!")
    else:
        print("💥 Deployment failed!")