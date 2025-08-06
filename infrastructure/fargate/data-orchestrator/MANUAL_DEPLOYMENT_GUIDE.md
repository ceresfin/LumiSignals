# Manual Deployment Guide - Config Update (1200 M5 Candles)

## 🎯 Configuration Changes Applied

The following configuration changes have been made to increase historical data collection:

- **Historical Data Points**: `100` → `1200` M5 candles  
- **Data Retention (TTL)**: `7200 seconds (2 hours)` → `432000 seconds (5 days)`
- **Expected Result**: `5-8 H1 candles` → `80-100 H1 candles`

## 📋 Deployment Instructions

### Option 1: Automated Script (Recommended)
```bash
cd /mnt/c/Users/sonia/LumiSignals/infrastructure/fargate/data-orchestrator
./deploy-with-config-update.sh
```

### Option 2: Manual Steps

1. **Navigate to project directory:**
   ```bash
   cd /mnt/c/Users/sonia/LumiSignals/infrastructure/fargate/data-orchestrator
   ```

2. **Login to ECR:**
   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 816945674467.dkr.ecr.us-east-1.amazonaws.com
   ```

3. **Build Docker image with unique tags:**
   ```bash
   # Generate unique hash
   HASH=$(git rev-parse --short HEAD)-$(date +%Y%m%d-%H%M%S)
   VERSION="config-update-1200-candles-${HASH}"
   
   # Build image
   docker build \
     --build-arg VERSION="${VERSION}" \
     --build-arg BUILD_DATE="$(date +%Y%m%d-%H%M%S)" \
     --build-arg COMMIT_SHA="$(git rev-parse --short HEAD)" \
     --build-arg CACHEBUST="$(date +%s)" \
     --platform linux/amd64 \
     -t lumisignals-data-orchestrator:${HASH} \
     -t lumisignals-data-orchestrator:latest \
     .
   ```

4. **Tag for ECR:**
   ```bash
   docker tag lumisignals-data-orchestrator:${HASH} 816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals-data-orchestrator:${HASH}
   docker tag lumisignals-data-orchestrator:latest 816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals-data-orchestrator:latest
   ```

5. **Push to ECR (10 minute timeout):**
   ```bash
   timeout 600 docker push 816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals-data-orchestrator:${HASH}
   timeout 600 docker push 816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals-data-orchestrator:latest
   ```

6. **Update ECS service:**
   ```bash
   # Get current task definition
   aws ecs describe-task-definition --task-definition lumisignals-data-orchestrator --region us-east-1 > current-task-def.json
   
   # Create new task definition (manually edit JSON or use jq)
   # Update image URI to: 816945674467.dkr.ecr.us-east-1.amazonaws.com/lumisignals-data-orchestrator:${HASH}
   
   # Register new task definition
   aws ecs register-task-definition --region us-east-1 --cli-input-json file://updated-task-def.json
   
   # Update service
   aws ecs update-service \
     --cluster lumisignals-cluster \
     --service lumisignals-data-orchestrator \
     --task-definition lumisignals-data-orchestrator:NEW_REVISION \
     --region us-east-1
   ```

## 🔍 Verification Steps

1. **Check service status:**
   ```bash
   aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1
   ```

2. **Monitor deployment:**
   ```bash
   aws ecs wait services-stable --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1
   ```

3. **Check CloudWatch logs:**
   ```bash
   aws logs describe-log-groups --log-group-name-prefix "/ecs/lumisignals-data-orchestrator" --region us-east-1
   ```

## ⏱️ Expected Timeline

- **Immediate**: Service restart with new configuration
- **5-10 minutes**: New M5 data collection starts with 1200 candle capacity
- **2-4 hours**: Sufficient M5 data collected for 80-100 H1 candles
- **Result**: TradingView charts should show dramatically more historical data

## 📊 Configuration Summary

| Setting | Before | After | Impact |
|---------|---------|--------|--------|
| Historical Data Points | 100 | 1200 | 12x more data |
| Redis TTL | 2 hours | 5 days | 60x longer retention |
| M5 Data Coverage | ~8 hours | ~100 hours | 12x time coverage |
| Expected H1 Candles | 5-8 | 80-100 | 15x more candles |
| TradingView History | Limited | Full scrollable history | Much better UX |

## 🚨 Important Notes

- The deployment script includes **10-minute timeout** for Docker push operations
- Both `latest` and unique hash tags are applied for better version management  
- Service will restart during deployment (~2-3 minutes downtime)
- Full data collection benefits will be visible after 2-4 hours
- TradingView charts will automatically show more candles once data is available