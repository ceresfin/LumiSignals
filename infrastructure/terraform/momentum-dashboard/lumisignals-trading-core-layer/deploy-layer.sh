#!/bin/bash
set -e

# LumiSignals Trading Core - Lambda Layer Deployment Script
# This script packages and deploys the lumisignals-trading-core Lambda layer

LAYER_NAME="lumisignals-trading-core"
DESCRIPTION="Shared trading infrastructure for LumiSignals Lambda functions - Market-aware momentum calculations"
COMPATIBLE_RUNTIMES="python3.9 python3.10 python3.11"

echo "🚀 Deploying LumiSignals Trading Core Lambda Layer"
echo "=================================================="

# Clean up any existing build artifacts
echo "🧹 Cleaning up previous builds..."
rm -rf build/
rm -f lumisignals-trading-core-layer.zip

# Create build directory structure
echo "📦 Creating build structure..."
mkdir -p build/python

# Copy source code to build directory
echo "📋 Copying source code..."
cp -r python/lumisignals_trading_core build/python/

# Install dependencies if requirements.txt has actual packages
echo "📥 Installing dependencies..."
if grep -v '^#' requirements.txt | grep -v '^$' | wc -l | grep -q '^0$'; then
    echo "ℹ️  No external dependencies to install (using Python standard library only)"
else
    pip install -r requirements.txt -t build/python/
fi

# Create deployment package
echo "🗜️  Creating deployment package..."
cd build
python3 ../create_zip.py
cd ..

# Get package size
PACKAGE_SIZE=$(du -h lumisignals-trading-core-layer.zip | cut -f1)
echo "📊 Package size: $PACKAGE_SIZE"

# Deploy to AWS Lambda
echo "☁️  Deploying to AWS Lambda..."
aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "$DESCRIPTION" \
    --zip-file fileb://lumisignals-trading-core-layer.zip \
    --compatible-runtimes $COMPATIBLE_RUNTIMES \
    --compatible-architectures "x86_64"

# Get the new layer version ARN
echo "🔍 Getting layer information..."
LAYER_ARN=$(aws lambda list-layer-versions --layer-name "$LAYER_NAME" --query 'LayerVersions[0].LayerVersionArn' --output text)

echo ""
echo "✅ Layer deployment completed successfully!"
echo "=================================================="
echo "Layer Name: $LAYER_NAME"  
echo "Layer ARN: $LAYER_ARN"
echo "Compatible Runtimes: $COMPATIBLE_RUNTIMES"
echo "Package Size: $PACKAGE_SIZE"
echo ""
echo "📝 To use this layer in your Lambda functions, add the Layer ARN to your function configuration:"
echo "   AWS Console: Add Layer > Specify ARN > $LAYER_ARN"
echo "   CLI: aws lambda update-function-configuration --function-name YOUR_FUNCTION --layers $LAYER_ARN"
echo "   Terraform: layers = [\"$LAYER_ARN\"]"
echo ""
echo "💡 Import in your Lambda function code:"
echo "   from lumisignals_trading_core import MarketAwareMomentumCalculator, ForexMarketSchedule"
echo ""

# Clean up build artifacts
echo "🧹 Cleaning up build artifacts..."
rm -rf build/

echo "🎉 Deployment complete!"