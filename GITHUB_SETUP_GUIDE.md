# GitHub Repository Setup Guide

## Creating a New GitHub Repository

### Option 1: Using GitHub Web Interface

1. **Go to GitHub.com** and log in to your account

2. **Create New Repository:**
   - Click the "+" icon in the top right
   - Select "New repository"
   - Repository name: `oanda-trading-bot` (or your preferred name)
   - Description: "Automated forex trading bot with OANDA API integration and Airtable journaling"
   - Choose: **Private** (recommended for trading bots)
   - Initialize with README: **No** (we already have one)
   - .gitignore: **No** (we already have one)
   - License: Choose one if desired (MIT is common)

3. **After Creation, GitHub will show you commands. Use these:**

### Option 2: Using GitHub CLI

If you have GitHub CLI installed:

```bash
# Create a new private repository
gh repo create oanda-trading-bot --private --description "Automated forex trading bot with OANDA API integration and Airtable journaling"
```

## Connecting Your Local Repository to GitHub

Since you already have a local Git repository, we need to add GitHub as a remote:

```bash
# Remove existing remote if there is one
git remote remove origin

# Add your new GitHub repository as origin
git remote add origin https://github.com/YOUR_USERNAME/oanda-trading-bot.git

# Verify the remote was added
git remote -v
```

## Organizing Your Commits

Before pushing to GitHub, let's organize the commits properly:

### 1. Create Initial Project Structure Commit

```bash
# Add core project files
git add package.json package-lock.json tsconfig.json
git add .gitignore README.md CHANGELOG.md CONTRIBUTING.md
git add src/index.ts src/config/ src/api/ src/services/ src/types/ src/utils/
git add config/

# Commit
git commit -m "feat: initial project structure with TypeScript setup

- Add Node.js/TypeScript configuration
- Add project documentation (README, CHANGELOG, CONTRIBUTING)
- Add basic source structure for trading bot
- Configure ESLint and Jest for code quality"
```

### 2. Add Trading Strategies Commit

```bash
# Add strategy files
git add src/*Strategy*.py
git add src/momentum_calculator.py
git add src/psychological_levels_trader.py
git add src/metadata_storage.py

# Commit
git commit -m "feat: add trading strategies implementation

- Penny Curve Momentum (PCM) strategy
- Dime Curve strategies with variants
- Quarter Curve Butter strategy
- Market momentum and psychological levels analysis"
```

### 3. Add Enhanced Trade Logging System

```bash
# Add new logging system
git add src/enhanced_trade_logger.py
git add src/enhanced_sync_all.py
git add src/trade_logger_integration.py
git add src/TRADE_LOGGING_FIX_GUIDE.md

# Commit
git commit -m "feat: add comprehensive trade logging system

- Enhanced trade logger with complete lifecycle tracking
- Fixed metadata classification for Airtable sync
- Integration wrapper for existing strategies
- Comprehensive documentation for fixes"
```

### 4. Add OANDA API and Utilities

```bash
# Add API and utility files
git add src/oanda_api.py
git add src/airtable_utils.py
git add src/sync_all.py
git add src/batch_orders.py

# Commit
git commit -m "feat: add OANDA API integration and utilities

- OANDA API wrapper for order execution
- Airtable synchronization utilities
- Batch order processing
- Trade synchronization scripts"
```

## Push to GitHub

After organizing commits:

```bash
# Push to main branch
git push -u origin main

# If you get an error about branch names, try:
git branch -M main
git push -u origin main
```

## Setting Up Branch Protection (Recommended)

1. Go to your repository on GitHub
2. Settings → Branches
3. Add rule for `main` branch:
   - Require pull request reviews before merging
   - Dismiss stale pull request approvals
   - Require status checks to pass

## GitHub Actions for CI/CD (Optional)

Create `.github/workflows/test.yml`:

```yaml
name: Test and Lint

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Use Node.js
      uses: actions/setup-node@v3
      with:
        node-version: '18.x'
        
    - name: Install dependencies
      run: npm ci
      
    - name: Run tests
      run: npm test
      
    - name: Run linter
      run: npm run lint
      
    - name: Type check
      run: npm run typecheck
```

## Security Considerations

### 1. **Never Commit Secrets**
- Use GitHub Secrets for API keys
- Keep `.env` files local only
- Use `.env.example` for templates

### 2. **Add Security Scanning**
- Enable Dependabot alerts
- Enable code scanning
- Use GitHub secret scanning

### 3. **Protected Files**
Create `.github/CODEOWNERS`:
```
# Global owners
* @yourusername

# Trading strategies
/src/*Strategy*.py @yourusername
/src/oanda_api.py @yourusername
```

## Repository Structure Best Practices

```
oanda-trading-bot/
├── .github/           # GitHub specific files
│   ├── workflows/     # CI/CD workflows
│   └── CODEOWNERS     # Code ownership
├── src/               # Source code
│   ├── strategies/    # Trading strategies
│   ├── api/          # API integrations
│   ├── utils/        # Utilities
│   └── types/        # TypeScript types
├── tests/            # Test files
├── docs/             # Documentation
├── config/           # Configuration
└── scripts/          # Utility scripts
```

## Next Steps

1. **Set up GitHub Projects** for task tracking
2. **Create initial issues** for known bugs/features
3. **Set up GitHub Wiki** for detailed documentation
4. **Configure webhooks** for deployment notifications
5. **Add collaborators** if working with a team

## Useful GitHub Features for Trading Bots

1. **GitHub Secrets**: Store API keys securely
2. **GitHub Actions**: Automate testing and deployment
3. **GitHub Packages**: Host private packages
4. **GitHub Insights**: Track code frequency
5. **GitHub Discussions**: Community support

Remember: Keep your trading strategies and API keys secure!