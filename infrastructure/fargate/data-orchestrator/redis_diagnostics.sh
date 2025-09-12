#!/bin/bash
"""
Redis Cluster Diagnostics Script

This script provides AWS CLI commands to diagnose the Redis cluster
and verify it's running properly from outside the VPC.

Run this script to check:
1. ElastiCache cluster status
2. Node health
3. Parameter group settings
4. Security group configuration
5. VPC and subnet information
"""

set -e

echo "🔍 Redis Cluster Diagnostics"
echo "=============================="

echo ""
echo "📊 ElastiCache Cluster Status"
echo "------------------------------"

# Check Redis replication groups
echo "🔍 Checking Redis replication groups..."
aws elasticache describe-replication-groups \
    --region us-east-1 \
    --query 'ReplicationGroups[*].{
        Id:ReplicationGroupId,
        Status:Status,
        NodeType:CacheNodeType,
        Engine:Engine,
        EngineVersion:EngineVersion,
        NumNodes:length(NodeGroups[0].NodeGroupMembers),
        ConfigEndpoint:ConfigurationEndpoint.Address
    }' \
    --output table

echo ""
echo "🔍 Checking specific trading cluster..."
aws elasticache describe-replication-groups \
    --replication-group-id lumisignals-trading-cluster \
    --region us-east-1 \
    --query 'ReplicationGroups[0].{
        Status:Status,
        Description:Description,
        ConfigEndpoint:ConfigurationEndpoint.Address,
        ConfigPort:ConfigurationEndpoint.Port,
        ClusterEnabled:ClusterEnabled,
        MultiAZ:MultiAZ,
        AutoFailover:AutomaticFailoverStatus
    }' \
    --output table 2>/dev/null || echo "❌ lumisignals-trading-cluster not found"

echo ""
echo "🔍 Checking manual shard nodes..."
for shard in 1 2 3 4; do
    echo "  Checking shard ${shard}..."
    aws elasticache describe-cache-clusters \
        --cache-cluster-id "lumisignals-main-vpc-trading-shard-${shard}-001" \
        --region us-east-1 \
        --query 'CacheClusters[0].{
            Id:CacheClusterId,
            Status:CacheClusterStatus,
            Engine:Engine,
            NodeType:CacheNodeType,
            Endpoint:RedisConfiguration.PrimaryEndpoint.Address
        }' \
        --output table 2>/dev/null || echo "    ❌ Shard ${shard} not found"
done

echo ""
echo "🔍 Getting node endpoints..."
echo "Manual shard endpoints:"
for shard in 1 2 3 4; do
    endpoint=$(aws elasticache describe-cache-clusters \
        --cache-cluster-id "lumisignals-main-vpc-trading-shard-${shard}-001" \
        --region us-east-1 \
        --query 'CacheClusters[0].RedisConfiguration.PrimaryEndpoint.Address' \
        --output text 2>/dev/null || echo "null")
    
    if [ "$endpoint" != "null" ] && [ "$endpoint" != "None" ]; then
        echo "  Shard ${shard}: ${endpoint}:6379"
    else
        echo "  Shard ${shard}: ❌ Not available"
    fi
done

echo ""
echo "🔒 Security Group Information"
echo "-----------------------------"

# Get security groups for ElastiCache
echo "🔍 ElastiCache security groups..."
aws elasticache describe-cache-clusters \
    --region us-east-1 \
    --query 'CacheClusters[?starts_with(CacheClusterId, `lumisignals`)].{
        Id:CacheClusterId,
        SecurityGroups:SecurityGroups[*].SecurityGroupId
    }' \
    --output table

echo ""
echo "🌐 VPC and Subnet Information"
echo "-----------------------------"

# Get subnet groups
echo "🔍 Cache subnet groups..."
aws elasticache describe-cache-subnet-groups \
    --region us-east-1 \
    --query 'CacheSubnetGroups[?contains(CacheSubnetGroupName, `lumisignals`)].{
        Name:CacheSubnetGroupName,
        VpcId:VpcId,
        Subnets:length(Subnets)
    }' \
    --output table

echo ""
echo "🔑 Parameter Groups"
echo "-------------------"

# Get parameter groups
echo "🔍 Redis parameter groups..."
aws elasticache describe-cache-parameter-groups \
    --region us-east-1 \
    --query 'CacheParameterGroups[?starts_with(CacheParameterGroupName, `lumisignals`) || Family==`redis7`].{
        Name:CacheParameterGroupName,
        Family:CacheParameterGroupFamily,
        Description:Description
    }' \
    --output table

echo ""
echo "📋 AWS Secrets Manager Check"
echo "-----------------------------"

echo "🔍 Checking for Redis credentials in Secrets Manager..."

# Check for Redis secrets
secrets=$(aws secretsmanager list-secrets \
    --region us-east-1 \
    --query 'SecretList[?contains(Name, `redis`) || contains(Name, `Redis`)].{
        Name:Name,
        Description:Description,
        LastChanged:LastChangedDate
    }' \
    --output table)

if [ -n "$secrets" ]; then
    echo "$secrets"
else
    echo "❌ No Redis secrets found"
fi

# Try to get the specific secret value (without exposing it)
echo ""
echo "🔍 Checking prod/redis/credentials secret..."
aws secretsmanager describe-secret \
    --secret-id "prod/redis/credentials" \
    --region us-east-1 \
    --query '{
        Name:Name,
        Description:Description,
        LastChanged:LastChangedDate,
        VersionsCount:length(VersionIdsToStages)
    }' \
    --output table 2>/dev/null || echo "❌ prod/redis/credentials secret not found"

echo ""
echo "🎯 Summary"
echo "----------"
echo "✓ Use these endpoints in your Redis connection:"
echo ""
for shard in 1 2 3 4; do
    endpoint=$(aws elasticache describe-cache-clusters \
        --cache-cluster-id "lumisignals-main-vpc-trading-shard-${shard}-001" \
        --region us-east-1 \
        --query 'CacheClusters[0].RedisConfiguration.PrimaryEndpoint.Address' \
        --output text 2>/dev/null || echo "null")
    
    if [ "$endpoint" != "null" ] && [ "$endpoint" != "None" ]; then
        echo "  lumisignals-main-vpc-trading-shard-${shard}-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
    fi
done

echo ""
echo "🚨 Important Notes:"
echo "  - Redis cluster is only accessible from within the VPC"
echo "  - Run verification scripts from EC2/ECS/Fargate in the same VPC"
echo "  - Auth token required from AWS Secrets Manager"
echo "  - Manual sharding is used across 4 nodes"