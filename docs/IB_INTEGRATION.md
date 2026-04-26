# IB Gateway Integration — Current Setup & Product Roadmap

## Current Architecture (Single User)

### How It Works Today

```
Digital Ocean Server (bot.lumitrade.ai)
├── IB Gateway (Docker) — headless IB desktop app
│   ├── Port 4002 (TWS API) → ib_insync connects here
│   └── Port 5900 (VNC) → for browser-based login
├── noVNC (Docker) — web-based VNC client
│   └── Port 6080 → proxied via nginx at /ib-vnc/
├── ibkr_sync.py — polls IB every 10s, pushes to server
├── lumisignals web app — Flask on port 8000
├── lumisignals-bot — currency trading + swing scanner
├── Redis — order queue, position cache, signal storage
├── PostgreSQL — user accounts, settings
└── nginx — SSL termination, reverse proxy
```

### Connection Flow
1. IB Gateway runs in Docker (`ghcr.io/gnzsnz/ib-gateway:10.30.1t`)
2. User logs in via browser VNC at `bot.lumitrade.ai/ib-vnc/vnc_lite.html`
3. Once authenticated, IB Gateway exposes TWS API on port 4004 (mapped to 4002)
4. `ibkr_sync.py` connects via ib_insync, syncs positions/orders every 10 seconds
5. Web app serves dashboard, scanner, trades pages

### Re-Authentication
- IB sessions expire ~24 hours
- User opens VNC in any browser (phone/tablet/desktop)
- Logs in to IB Gateway directly
- Sync service auto-reconnects (RestartSec=30)

### Docker Setup
```
/opt/lumisignals/cpapi/docker-compose.yml
├── ib-gateway: ghcr.io/gnzsnz/ib-gateway:10.30.1t
│   ├── Ports: 4002→4004 (API), 5900 (VNC)
│   ├── 768MB memory limit
│   └── Env: TRADING_MODE=paper, VNC_SERVER_PASSWORD
└── novnc: theasp/novnc
    ├── Port: 6080→8080
    ├── websockify proxies to ib-gateway:5900
    └── 64MB memory limit
```

---

## Steps to Make This a Multi-User Product

### Phase 1: Per-User IB Gateway Instances

**Problem:** Currently one IB Gateway serves one IB account. For multiple users, each needs their own gateway instance.

**Solution:** Dynamically spawn a Docker container per user.

```
User signs up → enters IB credentials → system creates:
├── ib-gateway-{user_id} container (unique ports)
├── novnc-{user_id} container
└── ibkr_sync-{user_id} process
```

**Implementation:**
- Store user's IB settings (trading mode, account type) in PostgreSQL
- On "Connect IB" button click, spin up Docker containers with unique port ranges
- Port allocation: user_id * 10 + base_port (e.g., user 1 = 14002, user 2 = 14012)
- Each user gets their own VNC URL for re-authentication
- Sync process per user pushes to `ibkr:data:{user_id}` in Redis

**Estimated effort:** 2-3 days

### Phase 2: IB OAuth / Third-Party Provider Registration

**Problem:** Currently users enter IB credentials in a VNC window. Not scalable or professional.

**Solution:** Register as an IB Third-Party Provider to use OAuth flow.

**Steps:**
1. Apply to IB's Third-Party Provider program
2. Get OAuth client credentials from IB
3. Users authorize LumiSignals to access their IB account via OAuth
4. Receive long-lived tokens (no VNC login needed)
5. Use IB Client Portal API with OAuth tokens

**Benefits:**
- No VNC — clean web-based authorization
- Tokens persist longer than gateway sessions
- Users never enter IB credentials on our platform
- Professional, trustworthy user experience

**Requirements from IB:**
- Business entity registration
- Compliance documentation
- Technical integration review
- May require specific insurance/licensing

**Estimated effort:** 2-4 weeks (mostly IB approval process)

### Phase 3: Multi-Broker Support

**Future consideration:** Support Schwab, Tradier, Alpaca alongside IB.

**Architecture:**
```python
class BrokerInterface:
    def get_positions(self) -> list
    def place_order(self, order) -> dict
    def get_account_summary(self) -> dict
    def search_options(self, ticker, exp, strike) -> int
```

Each broker implements this interface. The sync/trading logic is broker-agnostic.

---

## Security: Protecting Broker API Keys & Credentials

### Current State (Single User)
- IB credentials entered directly in VNC (not stored by our app)
- VNC password stored in docker-compose.yml on server
- No credentials in source code or environment variables
- IB Gateway manages its own auth session internally

### Risks to Address for Production

| Risk | Current | Production Fix |
|------|---------|----------------|
| VNC password in plaintext | docker-compose.yml | Per-user generated passwords, stored encrypted in DB |
| IB credentials visible in VNC | User types them | OAuth flow (no credentials on our platform) |
| Server compromise | Single server | Encrypt credentials at rest, separate auth service |
| Redis data exposure | Unencrypted | Redis AUTH password, encrypted sensitive fields |
| Database credentials | Plaintext in env | Use secrets manager (AWS SSM, DO Secrets, Vault) |
| API keys in code | Environment vars | Secrets manager with rotation |
| Inter-service communication | HTTP on localhost | mTLS between services |

### Recommended Security Architecture for Production

#### 1. Secrets Management
```
Current:  Environment variables in systemd service files
Target:   HashiCorp Vault or AWS Secrets Manager

Store:
- Database credentials
- Redis password
- Oanda API keys (per user)
- Massive/Polygon API keys (per user)
- SMTP credentials
- IB OAuth tokens (per user)
- JWT signing keys
```

#### 2. Credential Encryption at Rest
```python
# Per-user sensitive fields encrypted before storage
from cryptography.fernet import Fernet

class EncryptedField:
    """Encrypts/decrypts user credentials in the database."""
    
    def encrypt(self, value: str) -> str:
        key = get_encryption_key()  # From secrets manager
        return Fernet(key).encrypt(value.encode()).decode()
    
    def decrypt(self, token: str) -> str:
        key = get_encryption_key()
        return Fernet(key).decrypt(token.encode()).decode()

# Database columns to encrypt:
# - user.oanda_api_key
# - user.oanda_api_secret
# - user.massive_api_key
# - user.lumitrade_api_key
# - user.ib_oauth_token
# - user.ib_oauth_refresh_token
```

#### 3. Per-User API Key Isolation
```
Each user's API keys:
├── Stored encrypted in PostgreSQL
├── Decrypted only in-memory when needed
├── Never logged or exposed in API responses
├── Never sent to the browser
└── Rotatable without downtime
```

#### 4. Network Security
```
Current:
- IB Gateway on localhost only (good)
- Redis on localhost only (good)
- PostgreSQL on localhost only (good)
- nginx SSL termination (good)

Add for production:
- Redis AUTH password
- PostgreSQL SSL connections
- Rate limiting on API endpoints
- CORS restrictions (bot.lumitrade.ai only)
- CSP headers
- Session tokens with short TTL + refresh
```

#### 5. Authentication & Authorization
```
Current:  Flask-Login with session cookies
Add:
- JWT tokens with short expiry (15 min) + refresh tokens
- 2FA (TOTP) for dashboard login
- Role-based access (admin vs user)
- API key scoping (read-only vs trading)
- Session invalidation on password change
- Login attempt rate limiting
- IP allowlisting option
```

#### 6. Audit Trail
```
Log all sensitive operations:
- Order placement (who, what, when)
- Position changes
- Settings modifications
- API key rotations
- Login/logout events
- Failed authentication attempts
- IB re-authentication events
```

#### 7. Infrastructure
```
Current:  Single $12/mo Digital Ocean droplet
Production:
├── App server (Flask + sync processes)
├── Database server (managed PostgreSQL)
├── Redis server (managed Redis)
├── Docker host for IB Gateway instances
├── Load balancer with SSL
├── Automated backups
├── Monitoring (Datadog/Grafana)
└── Estimated: $100-200/mo for 10-50 users
```

---

## Migration Checklist: Single User → Product

### Must Have (Before First External User)
- [ ] Per-user encrypted API key storage
- [ ] Redis AUTH password
- [ ] Remove hardcoded credentials from code/configs
- [ ] Rate limiting on webhook endpoints
- [ ] User registration with email verification
- [ ] Terms of Service / Disclaimer (not investment advice)
- [ ] Error monitoring (Sentry or similar)
- [ ] Automated database backups

### Should Have (First 10 Users)
- [ ] Per-user IB Gateway containers
- [ ] Stripe billing integration
- [ ] Admin dashboard (user management, system health)
- [ ] 2FA for login
- [ ] Audit logging
- [ ] Managed PostgreSQL (not on app server)
- [ ] Managed Redis

### Nice to Have (Scale to 50+ Users)
- [ ] IB OAuth (Third-Party Provider registration)
- [ ] Multi-broker support (Schwab, Tradier)
- [ ] Kubernetes for container orchestration
- [ ] CDN for static assets
- [ ] Geographic redundancy
- [ ] SOC 2 compliance preparation

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `lumisignals/ibkr_sync.py` | Original sync (ib_insync) — currently running on server |
| `lumisignals/ibkr_sync_cpapi.py` | CPAPI REST version (ready, not active) |
| `lumisignals/ibkr_cpapi.py` | CPAPI REST client library |
| `lumisignals/ibkr_client.py` | Legacy IB client wrapper |
| `lumisignals/ibkr_analyzer.py` | Options spread analysis via IB |
| `/opt/lumisignals/cpapi/docker-compose.yml` | Docker config (server only) |
| `/etc/systemd/system/lumisignals-sync.service` | Sync systemd service |
| `/etc/nginx/sites-enabled/lumisignals` | Nginx config with VNC proxy |
