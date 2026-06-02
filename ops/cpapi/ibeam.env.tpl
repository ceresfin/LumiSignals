# 1Password-injected template. Renders to ibeam.env via:
#   op inject -i ibeam.env.tpl -o ibeam.env --force
# DO NOT commit the rendered ibeam.env. The .tpl is safe to commit
# (contains only 1Password reference URIs, no plaintext secrets).

# IB Gateway login. Username + password come from 1Password.
# "Interactive Brokers" item = Ceres784 (real-time-data subscription).
# "Interactive Brokers Sim" item = Ceres5298 (paper-only login).
IBEAM_ACCOUNT={{ op://Lumi/Interactive Brokers/username }}
IBEAM_PASSWORD={{ op://Lumi/Interactive Brokers/password }}

# Trading mode. Keep paper until live cutover is explicitly verified.
# Even with TRADING_MODE=paper, the Ceres784 login's paper sub-account
# inherits the live account's real-time market data subscriptions, so
# this gets us better data without putting real money at risk.
IBEAM_TRADING_MODE=paper

# Gateway identity + IBeam knobs (not secrets).
IBEAM_GATEWAY_BASE_URL=https://localhost:5000
IBEAM_USE_PAPER_ACCOUNT=True
IBEAM_MAX_FAILED_AUTH=1
