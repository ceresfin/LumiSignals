-- LumiSignals Supabase Schema
-- Run this in the Supabase SQL Editor (Dashboard → SQL Editor → New Query)

-- ============================================================
-- 1. PROFILES (extends Supabase auth.users)
-- ============================================================
create table if not exists profiles (
  id uuid references auth.users on delete cascade primary key,
  email text not null,
  plan text default 'free',
  bot_active boolean default false,
  -- Broker credentials
  oanda_account_id text,
  oanda_api_key text,
  oanda_environment text default 'practice',
  -- Per-model strategy settings
  scalp_min_score int default 50,
  scalp_min_rr float default 1.5,
  scalp_risk_mode text default 'percent',
  scalp_risk_value float default 0.25,
  scalp_daily_budget float default 0,
  intraday_min_score int default 50,
  intraday_min_rr float default 1.5,
  intraday_risk_mode text default 'percent',
  intraday_risk_value float default 0.5,
  intraday_daily_budget float default 0,
  swing_min_score int default 50,
  swing_min_rr float default 1.5,
  swing_risk_mode text default 'percent',
  swing_risk_value float default 1.0,
  swing_daily_budget float default 0,
  -- Options settings
  options_auto_trade boolean default false,
  options_trigger_tf text default '4h',
  options_spread_width float default 5.0,
  options_max_risk_per_spread float default 200,
  options_max_contracts int default 5,
  -- Futures settings
  futures_stop_loss float default 25.0,
  futures_contracts int default 1,
  created_at timestamptz default now()
);

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email);
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ============================================================
-- 2. TRADES (unified closed trades — FX + IB)
-- ============================================================
create table if not exists trades (
  id bigserial primary key,
  user_id uuid references profiles on delete cascade not null,
  broker text not null,
  broker_trade_id text,
  instrument text not null,
  asset_type text not null,
  direction text not null,
  units int,
  contracts int default 1,
  entry_price float,
  exit_price float,
  stop_loss float,
  take_profit float,
  realized_pl float default 0,
  pips float,
  planned_rr float,
  achieved_rr float,
  strategy text,
  model text,
  close_reason text,
  won boolean,
  -- Options-specific
  spread_type text,
  sell_strike float,
  buy_strike float,
  expiration date,
  "right" text,
  width float,
  -- Timestamps
  opened_at timestamptz,
  closed_at timestamptz,
  duration_mins int,
  created_at timestamptz default now()
);

create index if not exists idx_trades_user_broker on trades(user_id, broker);
create index if not exists idx_trades_user_strategy on trades(user_id, strategy);
create index if not exists idx_trades_instrument on trades(user_id, instrument);
create index if not exists idx_trades_closed_at on trades(closed_at desc);
create index if not exists idx_trades_broker_id on trades(broker_trade_id);

-- ============================================================
-- 3. POSITIONS (open positions — live state)
-- ============================================================
create table if not exists positions (
  id bigserial primary key,
  user_id uuid references profiles on delete cascade not null,
  broker text not null,
  broker_trade_id text,
  instrument text not null,
  asset_type text not null,
  direction text not null,
  units int,
  contracts int default 1,
  entry_price float,
  stop_loss float,
  take_profit float,
  unrealized_pl float default 0,
  pips float default 0,
  strategy text,
  model text,
  -- Options fields
  spread_type text,
  sell_strike float,
  buy_strike float,
  expiration date,
  "right" text,
  opened_at timestamptz,
  updated_at timestamptz default now(),
  unique(user_id, broker, broker_trade_id)
);

-- ============================================================
-- 4. ORDERS (pending/queued orders)
-- ============================================================
create table if not exists orders (
  id bigserial primary key,
  user_id uuid references profiles on delete cascade not null,
  order_id text not null,
  broker text not null,
  status text default 'queued',
  instrument text not null,
  asset_type text not null,
  direction text not null,
  contracts int default 1,
  strategy text,
  model text,
  -- Options fields
  spread_type text,
  sell_strike float,
  buy_strike float,
  expiration date,
  limit_price float,
  -- Metadata
  queued_at timestamptz default now(),
  filled_at timestamptz,
  updated_at timestamptz default now()
);

create index if not exists idx_orders_user_status on orders(user_id, status);

-- ============================================================
-- 5. SIGNALS (signal log — replaces JSON file)
-- ============================================================
create table if not exists signals (
  id bigserial primary key,
  user_id uuid references profiles on delete cascade not null,
  signal_key text not null,
  instrument text,
  action text,
  strategy text,
  strategy_id text,
  model text,
  entry_price float,
  stop_price float,
  target_price float,
  risk_reward float,
  bias_score float,
  zone_type text,
  zone_timeframe text,
  trigger_pattern text,
  close_reason text,
  exit_price float,
  realized_pl float,
  pips float,
  closed_at timestamptz,
  created_at timestamptz default now(),
  unique(user_id, signal_key)
);

-- ============================================================
-- 6. WATCHLIST ZONES (active S/R zones being monitored)
-- ============================================================
create table if not exists watchlist_zones (
  id bigserial primary key,
  user_id uuid references profiles on delete cascade not null,
  model text not null,
  instrument text not null,
  zone_timeframe text not null,
  zone_type text not null,
  zone_price float not null,
  bias_score float default 0,
  trade_direction text,
  status text default 'watching',
  atr float,
  trends jsonb,
  tf_details jsonb,
  updated_at timestamptz default now()
);

create index if not exists idx_watchlist_user_model on watchlist_zones(user_id, model);

-- ============================================================
-- 7. TV LEVELS (TradingView S/R levels from webhooks)
-- ============================================================
create table if not exists tv_levels (
  id bigserial primary key,
  ticker text not null unique,
  levels jsonb not null,
  trends jsonb,
  updated_at timestamptz default now()
);

-- ============================================================
-- 8. ACCOUNT SNAPSHOTS (periodic state for equity curve)
-- ============================================================
create table if not exists account_snapshots (
  id bigserial primary key,
  user_id uuid references profiles on delete cascade not null,
  broker text not null,
  nav float,
  cash float,
  unrealized_pl float,
  realized_pl float,
  buying_power float,
  open_positions int,
  snapshot_at timestamptz default now()
);

create index if not exists idx_snapshots_user_time on account_snapshots(user_id, snapshot_at desc);

-- ============================================================
-- 9. BOT LOGS (recent bot activity)
-- ============================================================
create table if not exists bot_logs (
  id bigserial primary key,
  user_id uuid references profiles on delete cascade not null,
  level text default 'INFO',
  message text not null,
  model text,
  instrument text,
  created_at timestamptz default now()
);

create index if not exists idx_bot_logs_user_time on bot_logs(user_id, created_at desc);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

-- Profiles
alter table profiles enable row level security;
create policy "Users read own profile" on profiles for select using (auth.uid() = id);
create policy "Users update own profile" on profiles for update using (auth.uid() = id);

-- Trades
alter table trades enable row level security;
create policy "Users read own trades" on trades for select using (auth.uid() = user_id);

-- Positions
alter table positions enable row level security;
create policy "Users read own positions" on positions for select using (auth.uid() = user_id);

-- Orders
alter table orders enable row level security;
create policy "Users read own orders" on orders for select using (auth.uid() = user_id);

-- Signals
alter table signals enable row level security;
create policy "Users read own signals" on signals for select using (auth.uid() = user_id);

-- Watchlist Zones
alter table watchlist_zones enable row level security;
create policy "Users read own zones" on watchlist_zones for select using (auth.uid() = user_id);

-- TV Levels (shared, read-only for all authenticated users)
alter table tv_levels enable row level security;
create policy "Authenticated read tv_levels" on tv_levels for select using (auth.role() = 'authenticated');

-- Account Snapshots
alter table account_snapshots enable row level security;
create policy "Users read own snapshots" on account_snapshots for select using (auth.uid() = user_id);

-- Bot Logs
alter table bot_logs enable row level security;
create policy "Users read own logs" on bot_logs for select using (auth.uid() = user_id);

-- ============================================================
-- REALTIME (enable for tables the app subscribes to)
-- ============================================================
alter publication supabase_realtime add table positions;
alter publication supabase_realtime add table trades;
alter publication supabase_realtime add table orders;
alter publication supabase_realtime add table watchlist_zones;
alter publication supabase_realtime add table bot_logs;
