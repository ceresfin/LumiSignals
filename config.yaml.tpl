oanda:
  account_id: {{ op://Lumi/LumiSignals - OANDA/username }}
  api_key: {{ op://Lumi/LumiSignals - OANDA/credential }}
  environment: practice
signals:
  mode: polling
  strategy: levels
  api_url: https://app.lumitrade.ai/api/v1/partners/technical-analysis/top-tickers/
  api_key: trk_live_cu7vj7nyYrc.toO5kCkvaw59f_eWNaMQ1XGph5-lbbk-8OIYz8zH3Ps
  poll_interval_seconds: 60
  market_filter: fx
  min_reward_risk: 1.5
  trading_timeframe: 1d
  webhook_port: 8080
  webhook_secret: ''
  mock_file: test_signals.json
snr:
  min_grade: B
  tolerance_pct: 0.002
  market_type: forex
risk:
  risk_percent: 1.0
  max_position_units: 100000
  max_open_positions: 20
levels:
  min_score: 50
  atr_stop_multiplier: 1.0
  trading_timeframe: 1d
  zone_tolerance_daily: 0.003
  zone_tolerance_weekly: 0.006
  zone_tolerance_monthly: 0.009
  watchlist_interval: 300
  monitor_interval: 30
  trigger_candle_count: 10
  min_risk_reward: 1.5
  zone_timeout: 14400
massive:
  api_key: iuT5Pj3thRCf6dRliPm4cGlzolW99E2n
  stock_atr_multiplier: 0.5
schwab:
  client_id: 63gzbYNANfMMCb6t71GGUPIAZzt1UN9GKIlw9nF84YPxaSIC
  client_secret: B5yON4pcdwEjPwsPAkAEiPKIpxnT8IjOAEHrHQu9aI5jZixDqjdjhIPIds1fOIqA
  redirect_uri: "https://127.0.0.1"
bot:
  dry_run: true
  log_level: INFO
