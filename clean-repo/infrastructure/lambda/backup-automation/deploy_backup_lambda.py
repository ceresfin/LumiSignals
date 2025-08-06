#!/usr/bin/env python3
"""
Deploy backup automation Lambda function
"""
import boto3
import json
import zipfile
import os
from datetime import datetime

def create_lambda_zip():
    """Create deployment package"""
    with zipfile.ZipFile('backup_lambda.zip', 'w') as zf:
        zf.write('rds_backup_to_s3.py', 'lambda_function.py')
    return 'backup_lambda.zip'

def create_iam_role():
    """Create IAM role for backup Lambda"""
    iam = boto3.client('iam')
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "rds:DescribeDBInstances",
                    "rds:DescribeDBSnapshots",
                    "rds:ListTagsForResource"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:ListBucket"
                ],
                "Resource": [
                    "arn:aws:s3:::lumisignals-backups-e5558a85",
                    "arn:aws:s3:::lumisignals-backups-e5558a85/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "lambda:GetFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:ListFunctions"
                ],
                "Resource": "*"
            }
        ]
    }
    
    try:
        # Create role
        role_name = 'lumisignals-backup-automation-role'
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description='Role for LumiSignals backup automation'
        )
        
        # Create and attach policy
        policy_name = 'lumisignals-backup-automation-policy'
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document)
        )
        
        print(f"Created IAM role: {role_name}")
        return iam.get_role(RoleName=role_name)['Role']['Arn']
        
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"Role already exists, using existing role")
        return iam.get_role(RoleName=role_name)['Role']['Arn']

def deploy_lambda(zip_file, role_arn):
    """Deploy the Lambda function"""
    lambda_client = boto3.client('lambda')
    
    function_name = 'lumisignals-backup-automation'
    
    with open(zip_file, 'rb') as f:
        zip_content = f.read()
    
    try:
        # Create function
        response = lambda_client.create_function(
            FunctionName=function_name,
            Runtime='python3.11',
            Role=role_arn,
            Handler='lambda_function.lambda_handler',
            Code={'ZipFile': zip_content},
            Description='Automated backup system for LumiSignals RDS and Lambda configs',
            Timeout=300,
            MemorySize=256,
            Environment={
                'Variables': {
                    'BACKUP_BUCKET': 'lumisignals-backups-e5558a85'
                }
            }
        )
        print(f"Created Lambda function: {function_name}")
        return response['FunctionArn']
        
    except lambda_client.exceptions.ResourceConflictException:
        # Update existing function
        lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=zip_content
        )
        print(f"Updated Lambda function: {function_name}")
        return lambda_client.get_function(FunctionName=function_name)['Configuration']['FunctionArn']

def create_schedule_rule(lambda_arn):
    """Create EventBridge rule to run daily at 2 AM UTC"""
    events = boto3.client('events')
    lambda_client = boto3.client('lambda')
    
    rule_name = 'lumisignals-daily-backup'
    
    # Create rule
    events.put_rule(
        Name=rule_name,
        ScheduleExpression='cron(0 2 * * ? *)',  # 2 AM UTC daily
        State='ENABLED',
        Description='Daily backup of LumiSignals RDS and Lambda configurations'
    )
    
    # Add Lambda permission
    try:
        lambda_client.add_permission(
            FunctionName='lumisignals-backup-automation',
            StatementId='AllowEventBridgeInvoke',
            Action='lambda:InvokeFunction',
            Principal='events.amazonaws.com',
            SourceArn=f'arn:aws:events:us-east-1:{boto3.client("sts").get_caller_identity()["Account"]}:rule/{rule_name}'
        )
    except lambda_client.exceptions.ResourceConflictException:
        pass  # Permission already exists
    
    # Add Lambda target
    events.put_targets(
        Rule=rule_name,
        Targets=[{
            'Id': '1',
            'Arn': lambda_arn
        }]
    )
    
    print(f"Created schedule rule: {rule_name} (runs daily at 2 AM UTC)")

def main():
    print("Deploying LumiSignals Backup Automation...")
    
    # Create deployment package
    zip_file = create_lambda_zip()
    
    # Create IAM role
    role_arn = create_iam_role()
    
    # Wait for role to propagate
    import time
    time.sleep(10)
    
    # Deploy Lambda
    lambda_arn = deploy_lambda(zip_file, role_arn)
    
    # Create schedule
    create_schedule_rule(lambda_arn)
    
    # Clean up
    os.remove(zip_file)
    
    print("\nBackup automation deployed successfully!")
    print("Backups will run daily at 2 AM UTC")
    print(f"Backup bucket: lumisignals-backups-e5558a85")

if __name__ == '__main__':
    main()