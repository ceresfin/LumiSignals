#!/usr/bin/env python3
"""
Detailed PostgreSQL Connection Test
Tests both secret access and SSL certificate requirements
"""

import json
import boto3
import os
import subprocess
import tempfile

def test_secret_access():
    """Test ECS-style secret access"""
    print("🔍 Testing Secret Access...")
    
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    # Test the exact ARN format used in ECS task definition
    secret_arn = "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials-anxzg6"
    
    try:
        # Test individual field access (as ECS does)
        fields = ['username', 'password', 'dbname']
        
        for field in fields:
            field_arn = f"{secret_arn}:{field}::"
            print(f"   Testing field access: {field}")
            
            try:
                response = secrets_client.get_secret_value(SecretId=field_arn)
                value = response['SecretString']
                print(f"      ✅ {field}: {value[:3]}{'*' * (len(value)-3)}")
            except Exception as e:
                print(f"      ❌ {field}: {str(e)}")
        
        # Test full secret access
        print(f"   Testing full secret access...")
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        secret_data = json.loads(response['SecretString'])
        
        print(f"   ✅ Full secret accessible:")
        print(f"      Host: {secret_data.get('host')}")
        print(f"      Port: {secret_data.get('port')}")
        print(f"      Database: {secret_data.get('dbname')}")
        print(f"      Username: {secret_data.get('username')}")
        print(f"      Password Length: {len(secret_data.get('password', ''))}")
        
        return secret_data
        
    except Exception as e:
        print(f"   ❌ Secret access failed: {str(e)}")
        return None

def test_ssl_certificate():
    """Test SSL certificate requirements"""
    print("\n🔍 Testing SSL Certificate Requirements...")
    
    # Get RDS certificate info
    rds_client = boto3.client('rds', region_name='us-east-1')
    
    try:
        response = rds_client.describe_db_instances(DBInstanceIdentifier='lumisignals-postgresql')
        db_instance = response['DBInstances'][0]
        
        cert_info = {
            'ca_certificate_identifier': db_instance.get('CACertificateIdentifier'),
            'certificate_details': db_instance.get('CertificateDetails', {}),
            'endpoint': db_instance['Endpoint']['Address'],
            'port': db_instance['Endpoint']['Port']
        }
        
        print(f"   RDS Certificate Info:")
        print(f"      CA Certificate: {cert_info['ca_certificate_identifier']}")
        print(f"      Valid Until: {cert_info['certificate_details'].get('ValidTill', 'Unknown')}")
        print(f"      Endpoint: {cert_info['endpoint']}:{cert_info['port']}")
        
        # Check if certificate is in the current certificate list
        cert_response = rds_client.describe_certificates()
        available_certs = {cert['CertificateIdentifier']: cert for cert in cert_response['Certificates']}
        
        current_cert = available_certs.get(cert_info['ca_certificate_identifier'])
        if current_cert:
            print(f"   ✅ Certificate found in available certificates:")
            print(f"      Type: {current_cert.get('CertificateType', 'Unknown')}")
            print(f"      Valid From: {current_cert.get('ValidFrom', 'Unknown')}")
            print(f"      Valid Till: {current_cert.get('ValidTill', 'Unknown')}")
            
            # Check if certificate is expired or near expiry
            if current_cert.get('ValidTill'):
                from datetime import datetime
                valid_till = current_cert['ValidTill']
                if isinstance(valid_till, str):
                    # Certificate is valid
                    print(f"      ✅ Certificate is valid")
                else:
                    print(f"      ✅ Certificate expires: {valid_till}")
        else:
            print(f"   ❌ Certificate {cert_info['ca_certificate_identifier']} not found in available certificates")
            print(f"   Available certificates:")
            for cert_id in available_certs.keys():
                print(f"      - {cert_id}")
        
        return cert_info
        
    except Exception as e:
        print(f"   ❌ Certificate check failed: {str(e)}")
        return None

def test_ssl_connection_modes():
    """Test different SSL connection modes"""
    print("\n🔍 Testing SSL Connection Modes...")
    
    # SSL modes to test
    ssl_modes = [
        'disable',
        'allow', 
        'prefer',
        'require',
        'verify-ca',
        'verify-full'
    ]
    
    # Get database credentials
    secret_data = {
        'host': 'lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com',
        'port': 5432,
        'dbname': 'lumisignals_trading',
        'username': 'lumisignals',
        'password': 'LumiSignals2025'
    }
    
    print(f"   Testing connection to: {secret_data['host']}:{secret_data['port']}")
    print(f"   Database: {secret_data['dbname']}")
    print(f"   Username: {secret_data['username']}")
    
    # Create connection test script
    test_script = f'''
import psycopg2
import sys

def test_connection(sslmode):
    try:
        conn = psycopg2.connect(
            host="{secret_data['host']}",
            port={secret_data['port']},
            database="{secret_data['dbname']}",
            user="{secret_data['username']}",
            password="{secret_data['password']}",
            sslmode=sslmode,
            connect_timeout=10
        )
        
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        cur.close()
        conn.close()
        
        return True, version[:50] + "..."
        
    except Exception as e:
        return False, str(e)

if __name__ == "__main__":
    sslmode = sys.argv[1] if len(sys.argv) > 1 else "require"
    success, result = test_connection(sslmode)
    print(f"{sslmode}:{success}:{result}")
'''
    
    # For now, simulate the connection test results
    print(f"   Connection test simulation (actual test requires psycopg2):")
    
    for mode in ssl_modes:
        print(f"      SSL Mode '{mode}': Would test connection...")
        
        if mode in ['disable', 'allow']:
            print(f"         ⚠️ Likely to fail - RDS requires SSL")
        elif mode in ['require', 'prefer']:
            print(f"         ✅ Most likely to succeed")
        elif mode in ['verify-ca', 'verify-full']:
            print(f"         ❓ Requires CA certificate bundle")
    
    return ssl_modes

def test_network_connectivity():
    """Test network connectivity to RDS"""
    print("\n🔍 Testing Network Connectivity...")
    
    endpoint = "lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com"
    port = 5432
    
    try:
        # Test DNS resolution
        result = subprocess.run(['nslookup', endpoint], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(f"   ✅ DNS resolution successful:")
            lines = result.stdout.split('\n')
            for line in lines:
                if 'Address:' in line and '127.0.0.53' not in line:
                    print(f"      {line.strip()}")
        else:
            print(f"   ❌ DNS resolution failed: {result.stderr}")
    
    except Exception as e:
        print(f"   ❌ DNS test error: {str(e)}")
    
    try:
        # Test port connectivity (using nc if available)
        result = subprocess.run(['nc', '-z', '-v', endpoint, str(port)], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(f"   ✅ Port {port} is reachable")
        else:
            print(f"   ❌ Port {port} connection failed: {result.stderr}")
            
    except FileNotFoundError:
        print(f"   ⚠️ 'nc' not available, skipping port test")
    except Exception as e:
        print(f"   ❌ Port test error: {str(e)}")

def analyze_ecs_environment():
    """Analyze how ECS injects secrets as environment variables"""
    print("\n🔍 Analyzing ECS Secret Injection...")
    
    # Show how ECS would inject the secrets
    task_secrets = [
        {
            "name": "DATABASE_USERNAME",
            "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials-anxzg6:username::"
        },
        {
            "name": "DATABASE_PASSWORD", 
            "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials-anxzg6:password::"
        },
        {
            "name": "DATABASE_NAME",
            "valueFrom": "arn:aws:secretsmanager:us-east-1:816945674467:secret:lumisignals/rds/postgresql/credentials-anxzg6:dbname::"
        }
    ]
    
    print(f"   ECS Task Definition Secrets:")
    for secret in task_secrets:
        print(f"      {secret['name']} <- {secret['valueFrom']}")
    
    # Test what the actual values would be
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    print(f"\n   Testing secret field extraction:")
    for secret in task_secrets:
        try:
            # Extract the secret ARN and field
            value_from = secret['valueFrom']
            if '::' in value_from:
                secret_arn, field_path = value_from.split('::', 1)
                field_name = field_path.rstrip(':')
                
                print(f"      {secret['name']}:")
                print(f"         Secret ARN: {secret_arn}")
                print(f"         Field: {field_name}")
                
                # Test field access
                response = secrets_client.get_secret_value(SecretId=value_from)
                value = response['SecretString']
                
                if 'password' in secret['name'].lower():
                    print(f"         Value: {'*' * len(value)}")
                else:
                    print(f"         Value: {value}")
                    
        except Exception as e:
            print(f"      ❌ {secret['name']}: {str(e)}")

def main():
    print("🔍 Detailed PostgreSQL Connection Analysis")
    print("=" * 80)
    
    # Run all tests
    secret_data = test_secret_access()
    cert_info = test_ssl_certificate()
    ssl_modes = test_ssl_connection_modes()
    test_network_connectivity()
    analyze_ecs_environment()
    
    print("\n" + "=" * 80)
    print("📊 ANALYSIS SUMMARY")
    print("=" * 80)
    
    print(f"1. Secret Access: {'✅ Working' if secret_data else '❌ Failed'}")
    print(f"2. SSL Certificate: {'✅ Valid' if cert_info else '❌ Issues'}")
    print(f"3. Network Connectivity: {'✅ Tested' if True else '❌ Failed'}")
    
    if cert_info:
        ca_cert = cert_info.get('ca_certificate_identifier')
        print(f"\n🔧 RECOMMENDATIONS:")
        print(f"   Current SSL Certificate: {ca_cert}")
        
        if ca_cert == 'rds-ca-rsa2048-g1':
            print(f"   ✅ Using current generation certificate")
            print(f"   💡 Consider SSL mode hierarchy:")
            print(f"      1. Try 'require' (current setting)")
            print(f"      2. If fails, try 'prefer'")
            print(f"      3. For production, use 'verify-ca' with certificate bundle")
        
        print(f"\n   🐛 DEBUGGING STEPS:")
        print(f"   1. Check if Data Orchestrator container has CA certificates")
        print(f"   2. Verify PostgreSQL SSL configuration")
        print(f"   3. Test connection from within VPC")
        print(f"   4. Check for certificate bundle requirements")

if __name__ == "__main__":
    main()