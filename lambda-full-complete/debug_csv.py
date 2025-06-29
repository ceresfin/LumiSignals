#!/usr/bin/env python3
"""
Debug script to check CSV file structure
"""

import pandas as pd
import os

# Check the CSV file
csv_file = "LumiTrade Trading Setups.csv"

try:
    print(f"🔍 Checking CSV file: {csv_file}")
    
    # Read the CSV
    df = pd.read_csv(csv_file)
    
    print(f"✅ CSV loaded successfully!")
    print(f"📊 Shape: {df.shape} (rows, columns)")
    print()
    
    print("📋 Column names found:")
    for i, col in enumerate(df.columns):
        print(f"  {i+1}. '{col}'")
    print()
    
    print("📄 First few rows:")
    print(df.head())
    print()
    
    print("🔍 Data types:")
    print(df.dtypes)
    print()
    
    # Check for expected columns
    expected_columns = ['Instrument', 'Units', 'Entry_Price', 'Stop_Loss', 'Target_Price', 'Setup_Name', 'Direction']
    missing_columns = []
    
    for col in expected_columns:
        if col not in df.columns:
            missing_columns.append(col)
    
    if missing_columns:
        print("❌ Missing expected columns:")
        for col in missing_columns:
            print(f"   • {col}")
    else:
        print("✅ All expected columns found!")
    
    # Check for any null values
    print("\n🔍 Null values per column:")
    print(df.isnull().sum())
    
except FileNotFoundError:
    print(f"❌ File not found: {csv_file}")
    print("📁 Files in current directory:")
    for f in os.listdir('.'):
        if f.endswith('.csv'):
            print(f"   • {f}")

except Exception as e:
    print(f"❌ Error reading CSV: {e}")
    print(f"Error type: {type(e).__name__}")