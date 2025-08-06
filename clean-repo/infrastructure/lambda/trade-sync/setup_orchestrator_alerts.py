#!/usr/bin/env python3
"""
Set up CloudWatch alerts for Data Orchestrator failures
"""

import boto3
import json

def create_orchestrator_alerts():
    """Create CloudWatch alarms for Data Orchestrator monitoring"""
    
    cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')
    sns = boto3.client('sns', region_name='us-east-1')
    
    # Create SNS topic for alerts (if it doesn't exist)
    topic_name = 'lumisignals-orchestrator-alerts'
    
    try:
        # Try to create topic
        response = sns.create_topic(Name=topic_name)
        topic_arn = response['TopicArn']
        print(f"✅ Created/found SNS topic: {topic_arn}")
    except Exception as e:
        print(f"❌ Error creating SNS topic: {str(e)}")
        return False
    
    # Define CloudWatch alarms
    alarms = [
        {
            'AlarmName': 'LumiSignals-DataOrchestrator-TaskFailures',
            'AlarmDescription': 'Data Orchestrator tasks are failing repeatedly',
            'MetricName': 'TaskCount',
            'Namespace': 'AWS/ECS',
            'Statistic': 'Average',
            'Dimensions': [
                {'Name': 'ServiceName', 'Value': 'institutional-orchestrator-postgresql17'},
                {'Name': 'ClusterName', 'Value': 'LumiSignals-prod-cluster'}
            ],
            'Period': 300,  # 5 minutes
            'EvaluationPeriods': 2,
            'Threshold': 0.5,
            'ComparisonOperator': 'LessThanThreshold',
            'AlarmActions': [topic_arn]
        },
        {
            'AlarmName': 'LumiSignals-DataOrchestrator-PostgreSQLErrors',
            'AlarmDescription': 'PostgreSQL connection errors in Data Orchestrator logs',
            'MetricName': 'ErrorCount',
            'Namespace': 'AWS/Logs',
            'Statistic': 'Sum',
            'Dimensions': [
                {'Name': 'LogGroupName', 'Value': '/ecs/lumisignals-institutional-postgresql'}
            ],
            'Period': 300,  # 5 minutes
            'EvaluationPeriods': 1,
            'Threshold': 5,
            'ComparisonOperator': 'GreaterThanThreshold',
            'AlarmActions': [topic_arn]
        },
        {
            'AlarmName': 'LumiSignals-DataOrchestrator-NoLogs',
            'AlarmDescription': 'Data Orchestrator has stopped logging (may be down)',
            'MetricName': 'IncomingLogEvents',
            'Namespace': 'AWS/Logs',
            'Statistic': 'Sum',
            'Dimensions': [
                {'Name': 'LogGroupName', 'Value': '/ecs/lumisignals-institutional-postgresql'}
            ],
            'Period': 600,  # 10 minutes
            'EvaluationPeriods': 1,
            'Threshold': 1,
            'ComparisonOperator': 'LessThanThreshold',
            'AlarmActions': [topic_arn],
            'TreatMissingData': 'breaching'
        }
    ]
    
    # Create alarms
    created_alarms = []
    for alarm_config in alarms:
        try:
            cloudwatch.put_metric_alarm(**alarm_config)
            created_alarms.append(alarm_config['AlarmName'])
            print(f"✅ Created alarm: {alarm_config['AlarmName']}")
        except Exception as e:
            print(f"❌ Error creating alarm {alarm_config['AlarmName']}: {str(e)}")
    
    # Create log metric filters for PostgreSQL errors
    logs_client = boto3.client('logs', region_name='us-east-1')
    
    metric_filters = [
        {
            'filterName': 'PostgreSQL-Authentication-Failures',
            'filterPattern': '"password authentication failed"',
            'logGroupName': '/ecs/lumisignals-institutional-postgresql',
            'metricTransformations': [
                {
                    'metricName': 'PostgreSQLAuthFailures',
                    'metricNamespace': 'LumiSignals/DataOrchestrator',
                    'metricValue': '1',
                    'defaultValue': 0
                }
            ]
        },
        {
            'filterName': 'Orchestrator-Initialization-Failures',
            'filterPattern': '"Failed to initialize orchestrator"',
            'logGroupName': '/ecs/lumisignals-institutional-postgresql',
            'metricTransformations': [
                {
                    'metricName': 'InitializationFailures',
                    'metricNamespace': 'LumiSignals/DataOrchestrator',
                    'metricValue': '1',
                    'defaultValue': 0
                }
            ]
        },
        {
            'filterName': 'Orchestrator-Success-Events',
            'filterPattern': '"✅" OR "Connected" OR "SUCCESS" OR "initialized successfully"',
            'logGroupName': '/ecs/lumisignals-institutional-postgresql',
            'metricTransformations': [
                {
                    'metricName': 'SuccessfulConnections',
                    'metricNamespace': 'LumiSignals/DataOrchestrator',
                    'metricValue': '1',
                    'defaultValue': 0
                }
            ]
        }
    ]
    
    # Create metric filters
    created_filters = []
    for filter_config in metric_filters:
        try:
            logs_client.put_metric_filter(**filter_config)
            created_filters.append(filter_config['filterName'])
            print(f"✅ Created metric filter: {filter_config['filterName']}")
        except Exception as e:
            print(f"❌ Error creating metric filter {filter_config['filterName']}: {str(e)}")
    
    # Create additional alarms based on custom metrics
    custom_alarms = [
        {
            'AlarmName': 'LumiSignals-DataOrchestrator-PostgreSQL-Auth-Failures',
            'AlarmDescription': 'High rate of PostgreSQL authentication failures',
            'MetricName': 'PostgreSQLAuthFailures',
            'Namespace': 'LumiSignals/DataOrchestrator',
            'Statistic': 'Sum',
            'Period': 300,  # 5 minutes
            'EvaluationPeriods': 1,
            'Threshold': 3,
            'ComparisonOperator': 'GreaterThanThreshold',
            'AlarmActions': [topic_arn],
            'TreatMissingData': 'notBreaching'
        },
        {
            'AlarmName': 'LumiSignals-DataOrchestrator-No-Success-Events',
            'AlarmDescription': 'No successful connections detected in logs',
            'MetricName': 'SuccessfulConnections',
            'Namespace': 'LumiSignals/DataOrchestrator',
            'Statistic': 'Sum',
            'Period': 900,  # 15 minutes
            'EvaluationPeriods': 1,
            'Threshold': 1,
            'ComparisonOperator': 'LessThanThreshold',
            'AlarmActions': [topic_arn],
            'TreatMissingData': 'breaching'
        }
    ]
    
    # Create custom metric alarms
    for alarm_config in custom_alarms:
        try:
            cloudwatch.put_metric_alarm(**alarm_config)
            created_alarms.append(alarm_config['AlarmName'])
            print(f"✅ Created custom alarm: {alarm_config['AlarmName']}")
        except Exception as e:
            print(f"❌ Error creating custom alarm {alarm_config['AlarmName']}: {str(e)}")
    
    print(f"\n📊 Summary:")
    print(f"   SNS Topic: {topic_arn}")
    print(f"   Alarms Created: {len(created_alarms)}")
    print(f"   Metric Filters Created: {len(created_filters)}")
    
    print(f"\n💡 To receive alerts, subscribe to the SNS topic:")
    print(f"   aws sns subscribe --topic-arn {topic_arn} --protocol email --notification-endpoint your-email@example.com")
    
    return {
        'topic_arn': topic_arn,
        'alarms': created_alarms,
        'metric_filters': created_filters
    }

def test_alerts():
    """Test the alerting system by checking current alarm states"""
    print("\n🔍 Testing Alert System...")
    
    cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')
    
    # Get alarm states
    alarm_names = [
        'LumiSignals-DataOrchestrator-TaskFailures',
        'LumiSignals-DataOrchestrator-PostgreSQL-Auth-Failures',
        'LumiSignals-DataOrchestrator-No-Success-Events'
    ]
    
    try:
        response = cloudwatch.describe_alarms(AlarmNames=alarm_names)
        
        for alarm in response['MetricAlarms']:
            state = alarm['StateValue']
            reason = alarm['StateReason']
            print(f"   {alarm['AlarmName']}: {state}")
            if state == 'ALARM':
                print(f"      Reason: {reason}")
    
    except Exception as e:
        print(f"❌ Error checking alarms: {str(e)}")

def main():
    print("🚨 Setting up Data Orchestrator CloudWatch Alerts...")
    print("=" * 60)
    
    result = create_orchestrator_alerts()
    test_alerts()
    
    print(f"\n✅ Alert system setup complete!")
    print(f"   Monitor Data Orchestrator health in CloudWatch Console")
    print(f"   Alerts will trigger when connection issues are detected")

if __name__ == "__main__":
    main()