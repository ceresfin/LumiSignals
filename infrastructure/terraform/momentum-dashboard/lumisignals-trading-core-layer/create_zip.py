#!/usr/bin/env python3
import zipfile
import os

def create_zip(source_dir, output_file):
    """Create a zip file from a directory"""
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)
    print(f"Created {output_file}")

if __name__ == "__main__":
    create_zip("python", "../lumisignals-trading-core-layer.zip")