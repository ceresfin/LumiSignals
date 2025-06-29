# Contributing to OANDA Trading Project

## Version Control Guidelines

### Branching Strategy

We follow a simplified Git Flow:

1. **main** - Stable, production-ready code
2. **develop** - Integration branch for features
3. **feature/*** - New features (e.g., `feature/enhanced-trade-logging`)
4. **fix/*** - Bug fixes (e.g., `fix/airtable-sync-errors`)
5. **hotfix/*** - Urgent fixes to production

### Commit Message Format

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```bash
feat(sync): add comprehensive trade logging system
fix(metadata): correct momentum direction mapping to Airtable
docs(readme): update installation instructions
refactor(strategies): consolidate duplicate code in PCM strategy
```

### Making Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes and commit:**
   ```bash
   git add .
   git commit -m "feat(scope): description of change"
   ```

3. **Update CHANGELOG.md:**
   - Add your changes under the "Unreleased" section
   - Follow the existing format

4. **Push your branch:**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create a Pull Request** (if using GitHub)

### Code Standards

1. **Python Code:**
   - Follow PEP 8
   - Use type hints where possible
   - Add docstrings to all functions/classes
   - Handle exceptions appropriately

2. **TypeScript Code:**
   - Follow ESLint configuration
   - Use proper types (avoid `any`)
   - Document complex logic

3. **Testing:**
   - Write tests for new features
   - Ensure existing tests pass
   - Test with small positions first

### Documentation

1. **Code Documentation:**
   - Clear docstrings for all public functions
   - Inline comments for complex logic
   - Update type definitions

2. **User Documentation:**
   - Update README.md for new features
   - Add examples to relevant guides
   - Update TRADE_LOGGING_FIX_GUIDE.md if modifying logging

### Release Process

1. **Version Bump:**
   - Update version in package.json
   - Update CHANGELOG.md with release date

2. **Create Release Commit:**
   ```bash
   git commit -m "chore(release): v1.1.0"
   git tag v1.1.0
   ```

3. **Push Tags:**
   ```bash
   git push origin main --tags
   ```

### Important Files to Track

Always commit changes to:
- Source code (`src/`)
- Configuration files (`config/`)
- Documentation (`docs/`, `*.md`)
- Package files (`package.json`, `requirements.txt`)

Never commit:
- `.env` files (use `.env.example`)
- API keys or credentials
- Large log files
- `node_modules/` or Python virtual environments
- Temporary files or caches

### Before Committing

1. **Run Tests:**
   ```bash
   npm test
   ```

2. **Check Code Style:**
   ```bash
   npm run lint
   npm run typecheck
   ```

3. **Test Your Changes:**
   - Run a single trading cycle
   - Verify Airtable sync works
   - Check logs for errors

### Getting Help

- Check existing issues on GitHub
- Review the documentation
- Ask in discussions or create an issue