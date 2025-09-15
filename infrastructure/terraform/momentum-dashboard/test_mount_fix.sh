#!/bin/bash

echo "🔧 Testing mounting fix for charts..."
echo ""

# Build the project
echo "📦 Building project..."
npm run build

if [ $? -eq 0 ]; then
    echo "✅ Build successful!"
    echo ""
    echo "📋 Summary of changes:"
    echo "1. Enhanced React.memo comparison for chart components"
    echo "2. Memoized graph component in App.tsx to prevent re-creation"
    echo "3. Added stable keys for chart components"
    echo "4. Added debugging logs to track mounting/unmounting"
    echo ""
    echo "🔍 Expected improvements:"
    echo "- Charts should mount only once (not 4 times)"
    echo "- Better performance with 28 charts"
    echo "- Reduced API calls"
    echo ""
    echo "📝 Next steps:"
    echo "1. Deploy to S3: aws s3 sync dist/ s3://pipstop.org-website/"
    echo "2. Invalidate CloudFront: aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths '/*'"
    echo "3. Test on pipstop.org and check console logs"
else
    echo "❌ Build failed! Check errors above."
    echo ""
    echo "To restore working version, run: ./restore_working_charts.sh"
fi