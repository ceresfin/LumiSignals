@echo off
REM LumiSignals Infrastructure Cleanup Preview
REM Shows what WOULD be cleaned up without actually doing it
REM Run this from: C:\Users\sonia\lumisignals\infrastructure\fargate\data-orchestrator

echo ========================================
echo LumiSignals Cleanup Preview
echo Showing What Would Be Cleaned Up
echo ========================================
echo.

echo [PREVIEW] Files that WOULD BE PRESERVED:
echo ✅ deploy-correct-iam-role.bat (working deployment script)
echo ✅ container-deployment-script.md (documentation)
echo ✅ MANUAL_DEPLOYMENT_GUIDE.md (manual procedures)
echo ✅ Dockerfile (build configuration)
echo ✅ requirements.txt (dependencies)
echo ✅ src\ directory (all source code)
echo.

echo [PREVIEW] Container images that WOULD BE KEPT:
aws ecr describe-images --repository-name lumisignals/institutional-orchestrator-postgresql17 --region us-east-1 --image-ids imageTag=iam-fix-20250909-131543 --query "imageDetails[0].{Tag:imageTags[0],Size:imageSizeInBytes,Pushed:imagePushedAt}" --output table 2>nul
aws ecr describe-images --repository-name lumisignals/institutional-orchestrator-postgresql17 --region us-east-1 --image-ids imageTag=aws-cli-20250909-095244 --query "imageDetails[0].{Tag:imageTags[0],Size:imageSizeInBytes,Pushed:imagePushedAt}" --output table 2>nul
aws ecr describe-images --repository-name lumisignals/institutional-orchestrator-postgresql17 --region us-east-1 --image-ids imageTag=latest --query "imageDetails[0].{Tag:imageTags[0],Size:imageSizeInBytes,Pushed:imagePushedAt}" --output table 2>nul

echo.
echo [PREVIEW] Container images that WOULD BE DELETED:
set OBSOLETE_IMAGES=final-fix-20250909-113345 json-secret-fix final-fix sql-syntax-fix-20250908-235216 syntax-fix sql-syntax-fix-20250908-235806 comprehensive-fix-20250908-230500 database-fix-20250908-220119 pydantic-fix config-fix-20250909-115519 db-creds-fix-20250909-110308 final-fix-20250908-221833 method-signature-fix-20250908-233608 iam-fix-20250909-130554

for %%i in (%OBSOLETE_IMAGES%) do (
    echo   🗑️ %%i
)

echo.
echo [PREVIEW] Deployment scripts that WOULD BE ARCHIVED:
if exist deploy-cleanup-fix.bat echo   📁 deploy-cleanup-fix.bat
if exist deploy-config-fix.bat echo   📁 deploy-config-fix.bat
if exist deploy-final-fix.bat echo   📁 deploy-final-fix.bat
if exist deploy-method-signature-fix.bat echo   📁 deploy-method-signature-fix.bat
if exist deploy-sql-syntax-fix.bat echo   📁 deploy-sql-syntax-fix.bat
if exist deploy-windows-fix.bat echo   📁 deploy-windows-fix.bat
if exist deploy-aws-cli-only.bat echo   📁 deploy-aws-cli-only.bat
if exist continue-deploy.bat echo   📁 continue-deploy.bat

echo.
echo [PREVIEW] Temporary files that WOULD BE ARCHIVED:
if exist current-task-def.json echo   📁 current-task-def.json
if exist hotfix-manual-task-def.json echo   📁 hotfix-manual-task-def.json
if exist time-fix-task-def.json echo   📁 time-fix-task-def.json
if exist test_h1_data.py echo   📁 test_h1_data.py

echo.
echo [PREVIEW] Task definitions that WOULD BE KEPT:
echo ✅ lumisignals-data-orchestrator:196 (Golden Template - Production Active)
echo ✅ lumisignals-data-orchestrator:187 (Reference - Good IAM roles)

echo.
echo [PREVIEW] Task definitions that WOULD BE DEREGISTERED:
aws ecs list-task-definitions --family lumisignals-data-orchestrator --status ACTIVE --region us-east-1 --query "taskDefinitionArns[?!contains(@, ':196') && !contains(@, ':187')]" --output text | head -10

echo.
echo ========================================
echo ESTIMATED CLEANUP BENEFITS:
echo ========================================
echo 📉 ECR Storage Savings: ~8-15GB (13 old container images)
echo 📉 File Organization: ~30 files archived into organized directories
echo 📉 ECS History: Cleaner task definition list
echo 🧹 Maintenance: Easier to find working resources
echo 📚 Documentation: Clear separation of working vs historical
echo.
echo TO ACTUALLY PERFORM CLEANUP:
echo   Run: cleanup-stale-resources.bat
echo.
echo SAFETY FEATURES:
echo ✅ Archives files instead of deleting them
echo ✅ Preserves all working resources 
echo ✅ Keeps TD 196 (golden template) and TD 187 (reference)
echo ✅ Maintains all source code and documentation

pause