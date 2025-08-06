#!/usr/bin/env python3
"""Test PostgreSQL connection with different credentials"""

import psycopg2
import json
import boto3
from botocore.exceptions import ClientError

def test_connection(host, database, username, password):
    """Test PostgreSQL connection"""
    print(f"\nTesting connection to {host}")
    print(f"Database: {database}")
    print(f"Username: {username}")
    print(f"Password: {'*' * len(password)}")
    
    try:
        # Try with SSL
        print("\nTrying with SSL required...")
        conn = psycopg2.connect(
            host=host,
            database=database,
            user=username,
            password=password,
            sslmode='require',
            connect_timeout=10
        )
        print("✅ Connection successful with SSL!")
        
        # Test query
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"PostgreSQL version: {version[0]}")
        
        # Check tables
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        tables = cur.fetchall()
        print(f"\nTables found: {len(tables)}")
        for table in tables[:5]:  # Show first 5 tables
            print(f"  - {table[0]}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ SSL connection failed: {str(e)}")
        
        # Try without SSL
        try:
            print("\nTrying without SSL...")
            conn = psycopg2.connect(
                host=host,
                database=database,
                user=username,
                password=password,
                sslmode='disable',
                connect_timeout=10
            )
            print("✅ Connection successful without SSL!")
            conn.close()
            return True
        except Exception as e2:
            print(f"❌ Non-SSL connection failed: {str(e2)}")
            return False

def main():
    # Initialize boto3 client
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    # Test both secrets
    secrets_to_test = [
        'lumisignals/postgresql',
        'lumisignals/rds/postgresql/credentials'
    ]
    
    for secret_name in secrets_to_test:
        print(f"\n{'='*60}")
        print(f"Testing secret: {secret_name}")
        print('='*60)
        
        try:
            response = secrets_client.get_secret_value(SecretId=secret_name)
            secret = json.loads(response['SecretString'])
            
            # Extract connection details
            host = secret.get('host')
            database = secret.get('database') or secret.get('dbname')
            username = secret.get('username')
            password = secret.get('password')
            
            # Test connection
            test_connection(host, database, username, password)
            
        except ClientError as e:
            print(f"❌ Failed to retrieve secret: {str(e)}")
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    # Also test the current endpoint with both passwords
    print(f"\n{'='*60}")
    print("Testing current endpoint with both passwords")
    print('='*60)
    
    endpoint = "lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com"
    database = "lumisignals_trading"
    username = "lumisignals"
    
    passwords_to_test = [
        ("LumiSignals2025", "from lumisignals/rds/postgresql/credentials"),
        ("O6ZFRmwR9vn54Zpg6Z7dWha8V", "from lumisignals/postgresql")
    ]
    
    for password, source in passwords_to_test:
        print(f"\nTesting password {source}:")
        test_connection(endpoint, database, username, password)

if __name__ == "__main__":
    main()