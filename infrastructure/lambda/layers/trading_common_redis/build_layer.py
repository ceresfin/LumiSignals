#!/usr/bin/env python3
"""
Build script for trading_common Lambda layer with Redis support
This layer will be shared across all trading strategy Lambda functions
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path

def build_trading_common_layer():
    """Build the trading_common layer with Redis support"""
    
    layer_dir = Path(__file__).parent
    python_dir = layer_dir / "python"
    
    print("🔨 Building trading_common Lambda layer with Redis...")
    print(f"Layer directory: {layer_dir}")
    
    # Clean existing python directory
    if python_dir.exists():
        shutil.rmtree(python_dir)
    
    python_dir.mkdir(exist_ok=True)
    
    # Install requirements
    requirements_file = layer_dir / "requirements.txt"
    
    print("📦 Installing Python packages...")
    cmd = [
        sys.executable, "-m", "pip", "install", 
        "-r", str(requirements_file),
        "-t", str(python_dir),
        "--no-deps",  # We'll handle dependencies manually
        "--platform", "linux_x86_64",
        "--only-binary=:all:"
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ Package installation completed")
    except subprocess.CalledProcessError as e:
        print(f"❌ Package installation failed: {e}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        return False
    
    # Install dependencies separately to ensure compatibility
    dependencies = [
        "boto3>=1.28.0",
        "botocore>=1.31.0",
        "pytz>=2023.3", 
        "typing-extensions>=4.7.0",
        "requests>=2.32.0",
        "redis>=4.5.0",
        "urllib3>=1.26.0",
        "certifi>=2023.0.0",
        "charset-normalizer>=3.0.0",
        "idna>=3.0.0"
    ]
    
    for dep in dependencies:
        print(f"📦 Installing {dep}...")
        cmd = [
            sys.executable, "-m", "pip", "install",
            dep,
            "-t", str(python_dir),
            "--upgrade",
            "--platform", "linux_x86_64",
            "--only-binary=:all:"
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Warning: Could not install {dep}: {e}")
    
    # Copy existing common files from the original layer
    original_layer = Path("/mnt/c/Users/sonia/LumiSignals/infrastructure/lambda/layers/trading_common/python")
    
    if original_layer.exists():
        print("📋 Copying existing common files...")
        
        common_files = [
            "oanda_api.py",
            "oanda_config.py", 
            "metadata_storage.py",
            "momentum_calculator.py",
            "redis_integration.py",
            "strategy_integration_example.py"
        ]
        
        for file_name in common_files:
            src_file = original_layer / file_name
            if src_file.exists():
                dst_file = python_dir / file_name
                shutil.copy2(src_file, dst_file)
                print(f"  ✅ Copied {file_name}")
        
        # Copy strategy templates directory if it exists
        strategy_templates_src = original_layer / "strategy_templates"
        if strategy_templates_src.exists():
            strategy_templates_dst = python_dir / "strategy_templates"
            shutil.copytree(strategy_templates_src, strategy_templates_dst)
            print("  ✅ Copied strategy_templates/")
    
    # Create a zip file for AWS deployment
    zip_file = layer_dir / "trading_common_redis_layer.zip"
    if zip_file.exists():
        zip_file.unlink()
    
    print("📦 Creating layer ZIP file...")
    shutil.make_archive(str(zip_file.with_suffix('')), 'zip', layer_dir, 'python')
    
    print(f"✅ Layer built successfully!")
    print(f"📦 ZIP file: {zip_file}")
    print(f"📁 Layer contents: {list(python_dir.iterdir())[:10]}...")
    
    # Show Redis installation status
    redis_installed = any(p.name.startswith('redis') for p in python_dir.iterdir())
    print(f"🔴 Redis installed: {'✅ YES' if redis_installed else '❌ NO'}")
    
    return True

if __name__ == "__main__":
    build_trading_common_layer()