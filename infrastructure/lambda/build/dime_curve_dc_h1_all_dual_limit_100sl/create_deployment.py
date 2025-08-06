#!/usr/bin/env python3
"""Create deployment package for Dime Curve Lambda"""

import zipfile
import os

# Get current directory
current_dir = os.path.dirname(os.path.abspath(__file__))

# Files to include in the deployment package
files_to_include = [
    'lambda_function.py',
    'dc_h1_all_dual_limit_100sl.py',
    'centralized_market_data_client.py',
    'momentum_calculator.py',
    'base_strategy.py',
    'dual_limit_curve_template.py',
]

# Create zip file
zip_path = os.path.join(current_dir, 'dime_curve_strategy.zip')
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for file in files_to_include:
        file_path = os.path.join(current_dir, file)
        if os.path.exists(file_path):
            zipf.write(file_path, file)
            print(f"Added {file}")
        else:
            print(f"Warning: {file} not found")

print(f"\nDeployment package created: {zip_path}")
print(f"Package size: {os.path.getsize(zip_path) / 1024:.2f} KB")