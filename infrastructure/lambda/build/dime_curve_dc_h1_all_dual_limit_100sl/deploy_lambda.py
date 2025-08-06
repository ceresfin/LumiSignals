#!/usr/bin/env python3
"""
Deploy Lambda function with SL/TP fixes
"""
import boto3
import zipfile
import os

def create_lambda_zip():
    """Create ZIP file for Lambda deployment"""
    print('Creating Lambda deployment package...')
    zip_filename = 'lambda_sl_tp_fix.zip'
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Skip __pycache__ and existing zip files
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                if not file.endswith('.zip') and not file.endswith('.pyc'):
                    file_path = os.path.join(root, file)
                    # Add to zip with relative path
                    arcname = os.path.relpath(file_path, '.')
                    zipf.write(file_path, arcname)
    
    print(f'Created {zip_filename}')
    return zip_filename

def deploy_lambda():
    """Deploy Lambda function"""
    zip_file = create_lambda_zip()
    
    lambda_client = boto3.client('lambda', region_name='us-east-1')
    
    try:
        with open(zip_file, 'rb') as f:
            response = lambda_client.update_function_code(
                FunctionName='lumisignals-dime_curve_dc_h1_all_dual_limit_100sl',
                ZipFile=f.read()
            )
        
        print('✅ Lambda function updated successfully')
        print(f'   Version: {response.get("Version")}')
        print(f'   Last Modified: {response.get("LastModified")}')
        print(f'   Code Size: {response.get("CodeSize")} bytes')
        
        return True
        
    except Exception as e:
        print(f'❌ Failed to deploy Lambda: {e}')
        return False

if __name__ == "__main__":
    if deploy_lambda():
        print('\n🎉 SL/TP Lambda fix deployed successfully!')
        print('   The Lambda function now includes:')
        print('   ✅ Redis storage via centralized_market_data_client.py')
        print('   ✅ Enhanced metadata with SL/TP fields')
        print('   ✅ Complete signal data preservation')
    else:
        print('❌ Deployment failed')