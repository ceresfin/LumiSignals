# 1Password-injected template. Renders to ibeam.env via:
#   op inject -i ibeam.env.tpl -o ibeam.env --force
# DO NOT commit the rendered ibeam.env. The .tpl is safe to commit
# (contains only 1Password reference URIs, no plaintext secrets).

# IB Gateway login. Username + password come from 1Password.
# "Interactive Brokers" item = Ceres784 (live, real-time-data subscription).
# "Interactive Brokers Sim" item = Ceres5299 (post-merger paper username,
#   inherits Ceres784's market data subs).
#
# 2026-06-03: switched from Ceres784 to Ceres5299 direct login. Logging
# in as Ceres784 + USE_PAPER_ACCOUNT=True triggered IBKR's "Welcome to
# Paper Trading — I Understand and Accept" disclaimer on every session,
# which IBeam's selenium can't click. Ceres5299 is already paper so the
# disclaimer doesn't appear.
IBEAM_ACCOUNT={{ op://Lumi/Interactive Brokers Sim/username }}
IBEAM_PASSWORD={{ op://Lumi/Interactive Brokers Sim/password }}

# Trading mode. Keep paper until live cutover is explicitly verified.
# Even with TRADING_MODE=paper, the Ceres784 login's paper sub-account
# inherits the live account's real-time market data subscriptions, so
# this gets us better data without putting real money at risk.
IBEAM_TRADING_MODE=paper

# Gateway identity + IBeam knobs (not secrets).
IBEAM_GATEWAY_BASE_URL=https://localhost:5000
IBEAM_USE_PAPER_ACCOUNT=True
IBEAM_MAX_FAILED_AUTH=1
