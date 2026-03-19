# Partner API Guide

## 0. Overview
The partners module lets approved partners access selected LumiTrade data APIs with a partner API key instead of user OAuth.

Auth mechanism:
- Header: `Authorization: Bearer <partner_api_key>`
- Base prefix: `{{url}}/partners/...`
- Partner keys are issued by LumiTrade, do not auto-expire, and can be rotated on demand.
- Partner APIs are throttled per key.

## 1. Keys

### Get / issue a partner key
This is typically done by LumiTrade admin through the partner management API.

`POST {{url}}/partner-management/partners`

Headers:
- `Authorization: Bearer {{admin_token}}`
- `Content-Type: application/json`

Body params:
- `name`: string, required, any partner name
- `slug`: string, required, unique slug, example `alpha-partner`
- `contact_name`: string, optional, any string
- `contact_email`: string, optional, any valid email
- `metadata`: object, optional, any JSON object
- `notes`: string, optional, any string
- `is_active`: boolean, optional, values: `true`, `false`
- `issue_key`: boolean, optional, values: `true`, `false`

Example body:
```json
{
  "name": "Alpha Partner",
  "slug": "alpha-partner",
  "contact_name": "Alpha Team",
  "contact_email": "alpha@example.com",
  "metadata": {},
  "notes": "Initial onboarding",
  "is_active": true,
  "issue_key": true
}
```

Example response:
```json
{
  "partner": {
    "id": 1,
    "name": "Alpha Partner",
    "slug": "alpha-partner",
    "contact_name": "Alpha Team",
    "contact_email": "alpha@example.com",
    "metadata": {},
    "notes": "Initial onboarding",
    "is_active": true,
    "active_key_prefix": "trk_live_xxxxx",
    "created_at": "2026-03-18T00:00:00Z",
    "updated_at": "2026-03-18T00:00:00Z"
  },
  "api_key": "trk_live_xxxxx.yyyyy",
  "key_prefix": "trk_live_xxxxx"
}
```

### Rotate current partner key
`POST {{url}}/partners/auth/rotate-key`

Headers:
- `Authorization: Bearer {{partner_api_key}}`

Body params:
- none

Example response:
```json
{
  "partner": {
    "id": 1,
    "name": "Alpha Partner",
    "slug": "alpha-partner",
    "contact_name": "Alpha Team",
    "contact_email": "alpha@example.com",
    "metadata": {},
    "notes": "Initial onboarding",
    "is_active": true,
    "active_key_prefix": "trk_live_newprefix",
    "created_at": "2026-03-18T00:00:00Z",
    "updated_at": "2026-03-18T00:00:00Z"
  },
  "api_key": "trk_live_newprefix.newsecret",
  "key_prefix": "trk_live_newprefix"
}
```

## 2. Data APIs
All requests below require:
- `Authorization: Bearer {{partner_api_key}}`

### Top Tickers
`GET {{url}}/partners/technical-analysis/top-tickers/?reward_risk_ratio=1`

Query params:
- `reward_risk_ratio`: optional, number
  Possible values:
  - any numeric value, example: `1`, `1.5`, `2`, `3`
  - if omitted, API returns top 10 per market
  - if `>= 3`, API returns all records with ratio `>= 3`
  - if `< 3`, API returns records in range `value` to `value + 0.25`

Example response:
```json
{
  "success": true,
  "data": {
    "equity": [
      {
        "ticker": "SPY",
        "entry": 530.12,
        "target": 540.45,
        "stoploss": 525.1,
        "reward_risk_ratio": 1.2,
        "timeframe": "hourly",
        "market_type": "stock",
        "market_label": "equity"
      }
    ],
    "fx": [],
    "crypto": [],
    "futures": []
  },
  "message": "Top tickers retrieved successfully"
}
```

### SNR Frequency
`GET {{url}}/partners/technical-analysis/snr/frequency/?ticker=SPY&intervals=5m,15m,30m,1h,1d,1w,1mo,4h&days=256&type=stock`

Query params:
- `ticker`: required, string
  Possible values:
  - any valid LumiTrade ticker, example: `SPY`, `AAPL`, `BTCUSD`
- `intervals`: optional, comma-separated string
  Possible values:
  - `5m`
  - `15m`
  - `30m`
  - `1h`
  - `4h`
  - `1d`
  - `1w`
  - `1mo`
  - if omitted, default is `5m,15m,30m,1h,4h,1d,1w,1m`
  - note: unsupported values fall back internally and should be avoided
- `days`: optional, integer
  Possible values:
  - any positive integer, example: `30`, `90`, `252`, `256`
- `type`: optional, string
  Possible values:
  - `stock`
  - `crypto`
  - `forex`
  - any other value falls back to `stock`
- `start_date`: optional, ISO date string
  Possible values:
  - format `YYYY-MM-DD`, example `2026-01-01`
- `end_date`: optional, ISO date string
  Possible values:
  - format `YYYY-MM-DD`, example `2026-03-18`

Example response:
```json
{
  "5m": {
    "ticker": "SPY",
    "support_price": 520.5,
    "resistance_price": 533.2
  },
  "1h": {
    "ticker": "SPY",
    "support_price": 518.8,
    "resistance_price": 536.1
  },
  "1d": {
    "ticker": "SPY",
    "support_price": 510.4,
    "resistance_price": 542.9
  }
}
```

### Trade Builder Setup
`GET {{url}}/partners/technical-analysis/trade-builder-setup?ticker=SPY&period=14&market=stock&frequency=hourly`

Query params:
- `ticker`: required, string
  Possible values:
  - any valid LumiTrade ticker, example: `SPY`, `AAPL`, `BTCUSD`
- `period`: required, integer
  Possible values:
  - any positive integer, example: `14`, `20`, `50`
- `market`: required, string
  Possible values:
  - `stock`
  - `crypto`
  - `forex`
  - `futures`
- `frequency`: optional, string or comma-separated list
  Possible values:
  - `minute`
  - `fiveminute`
  - `fifteenminute`
  - `thirtyminute`
  - `hourly`
  - `fourhour`
  - `daily`
  - `weekly`
  - `monthly`
  - if omitted, API returns all frequencies above
- `adj_entry`: optional, number
  Possible values:
  - any numeric price, example: `530`, `530.25`
- `adj_stop`: optional, number
  Possible values:
  - any numeric price, example: `525`, `525.10`
- `adj_target`: optional, number
  Possible values:
  - any numeric price, example: `540`, `540.50`

Example response:
```json
{
  "hourly": {
    "frequency": "hourly",
    "calculated_frequency": "fourhour",
    "position": "long",
    "snr": {
      "support_price": 520.5,
      "resistance_price": 533.2
    },
    "atr_value": 4.12,
    "adx": {
      "trend": {
        "hourly": "bullish"
      }
    },
    "calculated": {
      "entry": 530.0,
      "stop": 525.0,
      "target": 540.0,
      "profit": 10.0,
      "potential_loss": 5.0,
      "max_loss": 20.0,
      "shares": 4,
      "real_potential_loss": 20.0,
      "real_potential_gain": 40.0,
      "risk_reward": 2.0,
      "capital_required": 2120.0,
      "is_too_much_risk": false
    }
  }
}
```
