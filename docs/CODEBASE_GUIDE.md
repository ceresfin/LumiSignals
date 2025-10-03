# LumiSignals Codebase Guide
*Understanding the Repository Structure & Development Workflow*

**Version**: 1.0  
**Last Updated**: October 2025  
**Purpose**: Help developers navigate and understand the LumiSignals codebase

---

## 🎯 Repository Overview

LumiSignals is a **scalable algorithmic trading platform** built on AWS that processes real-time market data and executes 100+ concurrent trading strategies. The codebase follows a **microservices architecture** with centralized data collection and distributed strategy execution.

### Core Architecture Pattern
```
OANDA API → Data Orchestrator (Fargate) → Redis Cluster → Lambda Strategies → pipstop.org
                     ↓
               PostgreSQL (Analytics)
```

---

## 📁 Repository Structure

### 🏗️ **Infrastructure** (Production Code)
```
infrastructure/
├── fargate/
│   └── data-orchestrator/          # Core data collection service
│       ├── src/                    # Python source code
│       │   ├── data_orchestrator.py   # Main orchestrator logic
│       │   ├── config.py              # Settings & configuration
│       │   ├── oanda_client.py        # OANDA API integration
│       │   ├── redis_manager.py       # Redis cluster management
│       │   └── main.py                # Application entry point
│       ├── Dockerfile              # Container definition
│       ├── requirements.txt        # Python dependencies
│       └── deploy_*.sh            # Deployment scripts
│
├── lambda/                         # AWS Lambda functions
│   ├── signal-analytics-api/       # Fibonacci analysis for pipstop.org
│   │   ├── lambda_function.py      # Main Lambda handler
│   │   └── lumisignals_trading_core/  # Core trading algorithms
│   ├── direct-candlestick-api/     # Candlestick data API
│   └── build/                      # Individual strategy builds
│
└── terraform/                     # Infrastructure as Code
    ├── main.tf                     # AWS resource definitions
    ├── variables.tf                # Configuration variables
    └── outputs.tf                  # Infrastructure outputs
```

### 📚 **Documentation** (Knowledge Base)
```
docs/
├── README.md                       # Documentation index
├── architecture/                   # System design & deployment
├── trading/                        # Trading strategies & analysis
│   ├── fibonacci/                  # Fibonacci methodology
│   ├── analytics/                  # Trading analytics
│   └── signals/                    # Signal configuration
├── fixes/                          # Historical bug fixes
└── operations/                     # Operational procedures
```

### 🗂️ **Root Directory** (Essential Files)
```
├── README.md                       # Project overview
├── .gitignore                      # Git exclusions
├── requirements.txt                # Global dependencies (if any)
└── docs/                          # Documentation hub
```

---

## 🔍 File Type Classification

### ✅ **Essential Files** (Keep Always)
| Pattern | Purpose | Location |
|---------|---------|----------|
| `infrastructure/` | Production infrastructure code | All subdirectories |
| `docs/` | Organized documentation | All subdirectories |
| `README.md` | Project overview | Root |
| `Dockerfile` | Container definitions | Various |
| `requirements.txt` | Dependencies | Various |
| `lambda_function.py` | Lambda entry points | Lambda directories |
| `deploy_*.sh` | Deployment scripts | Infrastructure |

### ⚠️ **Temporary/Development Files** (Can Clean Up)
| Pattern | Purpose | Action |
|---------|---------|---------|
| `test_*.py` | Test scripts | Move to `/tests` or delete |
| `debug_*.py` | Debug scripts | Delete after use |
| `analyze_*.py` | Analysis scripts | Archive or delete |
| `check_*.py` | Verification scripts | Delete after use |
| `Screenshot *.png` | Temporary images | Delete |
| `*.json` (data files) | Test/analysis data | Delete |
| `*.backup_*` | Backup files | Delete |
| `*.zip` | Deployment packages | Delete old ones |

### 🔧 **Development Artifacts** (Organize)
| Pattern | Purpose | Action |
|---------|---------|---------|
| `fix_*.py` | One-time fixes | Delete after deployment |
| `deploy_*.py` | Deployment scripts | Keep useful ones |
| `verify_*.py` | Verification scripts | Keep core ones |
| `*.md` (scattered) | Documentation | Moved to `docs/` |

---

## 🚀 Development Workflow

### 1. **Understanding the System**
Start with these files in order:
1. `docs/architecture/THE_LUMISIGNALS_ARCHITECTURE_BIBLE.md` - System overview
2. `docs/architecture/LUMISIGNALS-DEPLOYMENT-GUIDE.md` - Deployment process
3. `infrastructure/fargate/data-orchestrator/src/data_orchestrator.py` - Core logic
4. `docs/trading/fibonacci/` - Trading strategy details

### 2. **Making Changes**
Follow this pattern:
1. **Read documentation** first (relevant `docs/` section)
2. **Understand current state** (check recent commits, deployment status)
3. **Make changes** (infrastructure code, never temp files)
4. **Test thoroughly** (use deployment guide procedures)
5. **Document changes** (update relevant `docs/` files)
6. **Commit properly** (following established commit message format)

### 3. **Deployment Process**
Use established scripts:
- **Infrastructure**: `infrastructure/fargate/data-orchestrator/deploy-correct-iam-role.bat`
- **Lambda Functions**: Function-specific deployment scripts
- **Emergency**: Revert to known good Task Definition (see deployment guide)

---

## 📊 Repository Statistics (October 2025)

**Current Repository Status**:
- **Temporary Python Scripts**: 377 files (`test_*.py`, `debug_*.py`, etc.)
- **Screenshot Files**: 29 files (`Screenshot *.png`)
- **JSON Data Files**: 1,653 files (excluding node_modules)
- **Documentation Files**: 27 files (organized in `docs/`)
- **Core Infrastructure**: ~50 essential files

**Cleanup Opportunity**: 
- **90%+ of files** are temporary development artifacts
- **Estimated cleanup**: Remove ~2,000+ temporary files
- **Core codebase**: <100 essential files for production system

---

## 🧹 Repository Cleanup Strategy

### Phase 1: Documentation (✅ Complete)
- ✅ Organized all `.md` files into `docs/` structure
- ✅ Created logical categories (architecture, trading, fixes, operations)
- ✅ Preserved all institutional knowledge

### Phase 2: Development Artifacts (Current)
**Target**: Remove temporary development files while preserving essential infrastructure

**Safe to Remove**:
```bash
# Test and debug scripts (400+ files)
test_*.py
debug_*.py
analyze_*.py
check_*.py
investigate_*.py
verify_*.py (some)

# Screenshots and temporary data
Screenshot *.png
*.json (analysis outputs)
*.backup_*
*summary.py (not .md files)

# Old deployment packages
*.zip (old ones)
```

**Preserve**:
```bash
# Core infrastructure
infrastructure/
docs/
README.md

# Active deployment scripts
deploy_*.sh (in infrastructure directories)
*deploy*.py (recent/useful ones)

# Current/useful analysis
# (Move useful ones to a tools/ directory)
```

### Phase 3: Organization (Future)
- Create `tools/` directory for useful analysis scripts
- Create `tests/` directory for test scripts (if we keep any)
- Archive old deployment artifacts
- Clean up node_modules and build artifacts

---

## 🛠️ Useful Development Commands

### Repository Navigation
```bash
# Main infrastructure code
cd infrastructure/fargate/data-orchestrator/src/

# Lambda functions
cd infrastructure/lambda/signal-analytics-api/

# Documentation
cd docs/
```

### Understanding Current State
```bash
# Check what's running in production
aws ecs describe-services --cluster lumisignals-cluster --services lumisignals-data-orchestrator --region us-east-1

# Check recent deployments
git log --oneline -10

# Find specific functionality
grep -r "bootstrap" infrastructure/ --include="*.py"
```

### Clean Development Environment
```bash
# See what files take up space
find . -name "*.py" | grep -E "(test_|debug_|analyze_)" | wc -l

# See all screenshots
find . -name "Screenshot*.png" | head -10

# Find large files
find . -type f -size +10M | head -10
```

---

## 📋 File Organization Rules

### 1. **Infrastructure Code**
- **Location**: `infrastructure/` directory only
- **Naming**: Descriptive, permanent names
- **Purpose**: Production systems
- **Changes**: Follow deployment guide, test thoroughly

### 2. **Documentation**
- **Location**: `docs/` directory with categories
- **Naming**: Descriptive, uppercase with underscores
- **Purpose**: Knowledge preservation and guidance
- **Changes**: Update when functionality changes

### 3. **Temporary Files**
- **Location**: Root directory (during development)
- **Naming**: Descriptive with prefixes (`test_`, `debug_`, etc.)
- **Purpose**: One-time analysis or debugging
- **Lifecycle**: Delete after use or move to tools/

### 4. **Development Tools**
- **Location**: `tools/` directory (future)
- **Naming**: Descriptive purpose-based names
- **Purpose**: Reusable analysis and debugging utilities
- **Changes**: Keep useful ones, document their purpose

---

## 🎯 Next Steps for Contributors

### New Developers
1. **Read this guide** and the Architecture Bible
2. **Explore** `infrastructure/fargate/data-orchestrator/src/` to understand core logic
3. **Review** recent commits to understand current development
4. **Follow** deployment guide for any infrastructure changes

### Experienced Developers
1. **Use this guide** to identify cleanup opportunities
2. **Move useful tools** to organized locations
3. **Update documentation** when making changes
4. **Help clean up** temporary files following the strategy above

### Repository Maintainers
1. **Enforce organization rules** during code reviews
2. **Regular cleanup** of temporary files
3. **Update this guide** as the codebase evolves
4. **Archive old versions** of deployment artifacts

---

## 📞 Support and References

- **Deployment Issues**: `docs/architecture/LUMISIGNALS-DEPLOYMENT-GUIDE.md`
- **System Architecture**: `docs/architecture/THE_LUMISIGNALS_ARCHITECTURE_BIBLE.md`
- **Trading Logic**: `docs/trading/fibonacci/`
- **Bug Fixes**: `docs/fixes/`
- **Recent Changes**: Git commit history

---

*This guide will be updated as we continue cleaning and organizing the repository. Last major update: October 2025 (Documentation reorganization and H1 collection fix)*