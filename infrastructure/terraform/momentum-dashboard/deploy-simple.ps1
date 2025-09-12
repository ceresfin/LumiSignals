# Deploy Y-axis fix to pipstop.org
Write-Host "Building dashboard..."
npm run build

Write-Host "Deploying to S3..."
aws s3 sync dist/ s3://pipstop.org-website/ --delete --cache-control "max-age=31536000" --exclude "index.html" --region us-east-1
aws s3 cp dist/index.html s3://pipstop.org-website/index.html --cache-control "no-cache" --region us-east-1

Write-Host "Invalidating CloudFront..."
aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths "/*" --region us-east-1

Write-Host "Deployment complete! Check https://pipstop.org"