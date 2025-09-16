#!/usr/bin/env python3
import os
import zipfile
import sys

def create_layer_zip():
    """Create Lambda layer ZIP file manually"""
    
    build_dir = 'build'
    zip_filename = 'lumisignals-trading-core-layer.zip'
    
    if not os.path.exists(build_dir):
        print("❌ Build directory not found. Run the deployment script first (it will fail at zip step)")
        return False
    
    print(f"🗜️ Creating {zip_filename}...")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Walk through all files in build directory
        for root, dirs, files in os.walk(build_dir):
            for file in files:
                file_path = os.path.join(root, file)
                # Create archive name (relative to build directory)
                archive_name = os.path.relpath(file_path, build_dir)
                zipf.write(file_path, archive_name)
                print(f"  📄 Added {archive_name}")
    
    # Check file size
    size_bytes = os.path.getsize(zip_filename)
    size_mb = size_bytes / (1024 * 1024)
    
    print(f"✅ Created {zip_filename} ({size_mb:.2f} MB)")
    return True

if __name__ == "__main__":
    create_layer_zip()