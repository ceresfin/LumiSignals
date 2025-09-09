# LumiSignals - Institutional Trading Platform

Institutional-grade quantitative trading platform with Fargate-based data orchestration and comprehensive trade management.

## Architecture

- **Data Orchestrator**: Single OANDA API connection serving 100+ Lambda strategies
- **Redis Cluster**: 4-node cluster for real-time market data distribution  
- **PostgreSQL RDS**: Comprehensive trade data storage and analysis
- **OANDA Integration**: Professional API integration for FX trading
- **PipStop Dashboard**: Real-time trading dashboard at pipstop.org

## Production Status ✅

**Current Deployment (September 2025)**:
- Task Definition 196: Optimal golden template configuration
- Comprehensive orchestrator: Active with automated trade cleanup
- High performance: CPU 2048, Memory 4096
- AWS Secrets Manager: JSON credential format compliance

## 📚 Documentation

- **[Deployment Guide](./LUMISIGNALS-DEPLOYMENT-GUIDE.md)** - Complete ECS deployment procedures
- **[Architecture Bible](./THE_LUMISIGNALS_ARCHITECTURE_BIBLE.md)** - Full system documentation
- **Working Deployment Script**: `infrastructure/fargate/data-orchestrator/deploy-correct-iam-role.bat`

## 🚀 Quick Deploy

### Emergency Deployment (Use Current Golden Template)
```bash
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:196 --desired-count 1 --force-new-deployment --region us-east-1
```

### Full Deployment (With Verification)
```bash
cd infrastructure/fargate/data-orchestrator
./deploy-correct-iam-role.bat
```

### Infrastructure Setup (Initial)
```bash
# Deploy infrastructure (if needed)
cd infrastructure/terraform/redis-cluster
terraform init && terraform apply

cd ../fargate-trade-executor  
terraform init && terraform apply
```

## 🔐 AWS Secrets Manager Setup

**Required Secrets**:
- `lumisignals/oanda/api/credentials` (JSON format)
- `lumisignals/rds/postgresql/credentials` (JSON format)

See [Deployment Guide](./LUMISIGNALS-DEPLOYMENT-GUIDE.md) for complete configuration details.

## 🎯 System Health Check

```bash
# Check current task definition
aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1 --query "services[0].taskDefinition" --output text

# View application logs
STREAM_NAME=$(aws logs describe-log-streams --log-group-name /ecs/lumisignals-data-orchestrator --region us-east-1 --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text)
aws logs get-log-events --log-group-name /ecs/lumisignals-data-orchestrator --log-stream-name "${STREAM_NAME}" --region us-east-1 --query "events[-10:].message" --output text
```
