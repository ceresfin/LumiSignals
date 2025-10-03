# Repository Cleanup Guide
*Safe procedures for cleaning up the LumiSignals codebase*

## 🎯 Objective
Clean up 2,000+ temporary development files while preserving all essential infrastructure and documentation.

## 📋 Pre-Cleanup Checklist

### ✅ Before Starting
1. **Verify current deployment is stable**
   ```bash
   aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1
   ```

2. **Check recent commits are working**
   ```bash
   git log --oneline -5
   ```

3. **Create backup branch**
   ```bash
   git checkout -b backup-before-cleanup
   git push origin backup-before-cleanup
   git checkout main
   ```

4. **Confirm H1 data is updating**
   ```bash
   curl -s "https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/H1?count=5"
   ```

## 🗂️ File Categories for Cleanup

### 🔥 Safe to Delete (377+ files)
```bash
# Test scripts - used for one-time testing
test_*.py
debug_*.py
analyze_*.py
check_*.py
investigate_*.py

# Screenshots - temporary images
Screenshot*.png

# Analysis outputs - generated data
*summary.py
*.json (data files, not config)
*_export.json
*_analysis.py
```

### ⚠️ Review Before Deleting
```bash
# Deployment scripts - keep useful ones
deploy_*.py
fix_*.py
verify_*.py

# Backup files - safe to delete after verification
*.backup_*
*.zip (old deployment packages)
```

### ✅ Never Delete
```bash
# Core infrastructure
infrastructure/
docs/
README.md

# Essential configs
Dockerfile
requirements.txt
main.tf
```

## 🧹 Cleanup Process

### Phase 1: Screenshots (Low Risk)
```bash
# Count screenshots
find . -name "Screenshot*.png" | wc -l

# Preview what will be deleted
find . -name "Screenshot*.png" | head -10

# Delete screenshots (safe)
find . -name "Screenshot*.png" -delete
```

### Phase 2: Test Scripts (Medium Risk)
```bash
# Count test files
find . -name "test_*.py" | wc -l

# Review largest test files (might be important)
find . -name "test_*.py" -exec ls -lh {} \; | sort -k5 -hr | head -10

# Move to cleanup folder first (safer than delete)
mkdir -p cleanup/test_scripts
find . -name "test_*.py" -exec mv {} cleanup/test_scripts/ \;
```

### Phase 3: Debug Scripts (Medium Risk)
```bash
# Move debug scripts
mkdir -p cleanup/debug_scripts
find . -name "debug_*.py" -exec mv {} cleanup/debug_scripts/ \;
find . -name "analyze_*.py" -exec mv {} cleanup/debug_scripts/ \;
find . -name "check_*.py" -exec mv {} cleanup/debug_scripts/ \;
find . -name "investigate_*.py" -exec mv {} cleanup/debug_scripts/ \;
```

### Phase 4: Analysis Data (Low Risk)
```bash
# Count JSON files
find . -name "*.json" | grep -v node_modules | grep -v infrastructure | wc -l

# Move analysis data
mkdir -p cleanup/analysis_data
find . -name "*summary.py" -exec mv {} cleanup/analysis_data/ \;
find . -name "*_export.json" -exec mv {} cleanup/analysis_data/ \;
find . -name "*_analysis.py" -exec mv {} cleanup/analysis_data/ \;
```

### Phase 5: Verification Scripts (High Risk)
```bash
# Review verification scripts manually - some might be useful
ls -la verify_*.py fix_*.py

# Keep useful ones, move others
mkdir -p cleanup/verification_scripts
# Move case-by-case after review
```

## 🛠️ Automated Cleanup Script

Create `cleanup_repository.sh`:
```bash
#!/bin/bash
# Repository Cleanup Script
set -e

echo "🧹 Starting LumiSignals Repository Cleanup"
echo "=========================================="

# Create cleanup directory
mkdir -p cleanup/{screenshots,test_scripts,debug_scripts,analysis_data,backup_files}

# Phase 1: Screenshots (Safe)
echo "📸 Cleaning screenshots..."
SCREENSHOT_COUNT=$(find . -name "Screenshot*.png" | wc -l)
echo "Found $SCREENSHOT_COUNT screenshots"
find . -name "Screenshot*.png" -exec mv {} cleanup/screenshots/ \;

# Phase 2: Test Scripts (Review)
echo "🧪 Moving test scripts..."
TEST_COUNT=$(find . -name "test_*.py" | wc -l)
echo "Found $TEST_COUNT test scripts"
find . -name "test_*.py" -exec mv {} cleanup/test_scripts/ \;

# Phase 3: Debug Scripts (Review)
echo "🐛 Moving debug scripts..."
DEBUG_COUNT=$(find . -name "debug_*.py" -o -name "analyze_*.py" -o -name "check_*.py" -o -name "investigate_*.py" | wc -l)
echo "Found $DEBUG_COUNT debug/analysis scripts"
find . -name "debug_*.py" -exec mv {} cleanup/debug_scripts/ \;
find . -name "analyze_*.py" -exec mv {} cleanup/debug_scripts/ \;
find . -name "check_*.py" -exec mv {} cleanup/debug_scripts/ \;
find . -name "investigate_*.py" -exec mv {} cleanup/debug_scripts/ \;

# Phase 4: Backup Files (Safe)
echo "💾 Moving backup files..."
find . -name "*.backup_*" -exec mv {} cleanup/backup_files/ \;

echo ""
echo "✅ Cleanup Summary:"
echo "  Screenshots: $SCREENSHOT_COUNT files moved"
echo "  Test scripts: $TEST_COUNT files moved"
echo "  Debug scripts: $DEBUG_COUNT files moved"
echo ""
echo "📁 Files moved to cleanup/ directory for review"
echo "🔍 Review cleanup/ contents before permanent deletion"
echo "✅ Repository is now cleaner and more organized"
```

## 🔍 Post-Cleanup Verification

### 1. Test System Still Works
```bash
# Check infrastructure files are intact
ls -la infrastructure/fargate/data-orchestrator/src/

# Check documentation is intact
ls -la docs/

# Verify deployment still possible
cd infrastructure/fargate/data-orchestrator
./deploy-correct-iam-role.bat --dry-run  # If available
```

### 2. Review Cleanup Directory
```bash
# Review what was moved
find cleanup/ -type f | head -20

# Check if any important files were accidentally moved
grep -r "production\|deploy\|critical" cleanup/ --include="*.py"
```

### 3. Commit Clean Repository
```bash
git add .
git commit -m "CLEANUP: Remove temporary development files and organize repository

Cleanup Summary:
- Removed 377+ temporary Python scripts (test_*, debug_*, analyze_*)
- Removed 29 screenshot files
- Moved analysis data files to cleanup directory
- Preserved all essential infrastructure and documentation

Repository now contains only essential files for production system.
Files moved to cleanup/ directory for review before permanent deletion."

git push origin main
```

## 🚨 Emergency Recovery

If something breaks after cleanup:

### 1. Restore from Backup Branch
```bash
git checkout backup-before-cleanup
git checkout -b emergency-restore
git push origin emergency-restore
```

### 2. Restore Specific Files
```bash
# If you need specific files back from cleanup/
cp cleanup/test_scripts/important_test.py ./
git add important_test.py
git commit -m "RESTORE: Recover important test file"
```

### 3. Emergency Deployment
```bash
# Use known good task definition
aws ecs update-service --cluster lumisignals-cluster --service lumisignals-data-orchestrator --task-definition lumisignals-data-orchestrator:219 --region us-east-1
```

## 📋 Final Checklist

After cleanup completion:
- [ ] Repository size significantly reduced
- [ ] Only essential files remain in root
- [ ] All infrastructure code preserved
- [ ] All documentation preserved in docs/
- [ ] System still functioning (H1 data updating)
- [ ] Cleanup directory reviewed
- [ ] Changes committed and pushed
- [ ] Backup branch exists for recovery

---

*This cleanup process is designed to be conservative and reversible. When in doubt, move files to cleanup/ rather than deleting them.*