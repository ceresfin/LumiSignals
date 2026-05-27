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
-- 10. STRATEGIES (stable slug → display-name registry)
-- ============================================================
create table if not exists strategies (
  strategy_id   text primary key,
  display_name  text not null,
  description   text,
  asset_classes text[] not null default '{}',
  active        boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ============================================================
-- 11. SYMBOL METADATA (per-ticker contract specs / sessions)
-- ============================================================
create table if not exists symbol_metadata (
  ticker             text primary key,
  asset_class        text not null,
  exchange           text not null,
  tick_size          numeric(18, 8) not null,
  multiplier         numeric(18, 8) not null,
  quote_currency     text not null default 'USD',
  session_open_local   time,
  session_close_local  time,
  session_tz           text,
  trades_overnight     boolean not null default false,
  ib_conid           bigint,
  oanda_instrument   text,
  pine_alert_symbol  text,
  active             boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- ============================================================
-- 12. USER STRATEGY SETTINGS (per user / strategy / ticker)
-- ============================================================
create table if not exists user_strategy_settings (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles(id) on delete cascade,
  strategy_id     text not null references strategies(strategy_id),
  ticker          text references symbol_metadata(ticker),
  stop_loss_usd   numeric(12, 2),
  take_profit_usd numeric(12, 2),
  qty             int not null default 1 check (qty > 0),
  enabled         boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create unique index if not exists ux_user_strategy_ticker
  on user_strategy_settings(user_id, strategy_id, coalesce(ticker, ''));

-- ============================================================
-- 13. TRADE EVENTS (append-only diary of state transitions)
-- ============================================================
create table if not exists trade_events (
  id                uuid primary key default gen_random_uuid(),
  broker            text not null,
  broker_trade_id   text,
  client_intent_id  uuid,
  strategy_id       text not null references strategies(strategy_id),
  ticker            text not null references symbol_metadata(ticker),
  user_id           uuid not null references profiles(id) on delete cascade,
  state             text not null,
  event_time        timestamptz not null default now(),
  reason            text,
  expected_qty      int,
  observed_qty      int,
  entry_price       numeric(18, 8),
  exit_price        numeric(18, 8),
  stop_price        numeric(18, 8),
  target_price      numeric(18, 8),
  realized_pl       numeric(18, 4),
  broker_snapshot   jsonb,
  meta              jsonb,
  created_at        timestamptz not null default now()
);
create index if not exists idx_trade_events_broker_trade
  on trade_events(broker, broker_trade_id) where broker_trade_id is not null;
create index if not exists idx_trade_events_intent
  on trade_events(client_intent_id) where client_intent_id is not null;
create index if not exists idx_trade_events_live
  on trade_events(strategy_id, ticker, state)
  where state in ('INTENT_OPEN', 'OPEN', 'INTENT_CLOSE');
create index if not exists idx_trade_events_user_time
  on trade_events(user_id, event_time desc);

-- ============================================================
-- 14. TRADE STATE CURRENT (latest state per trade — fast lookups)
-- ============================================================
create table if not exists trade_state_current (
  id                uuid primary key default gen_random_uuid(),
  broker_trade_id   text,
  client_intent_id  uuid,
  broker            text not null,
  strategy_id       text not null references strategies(strategy_id),
  ticker            text not null references symbol_metadata(ticker),
  user_id           uuid not null references profiles(id) on delete cascade,
  state             text not null,
  expected_qty      int,
  observed_qty      int,
  entry_price       numeric(18, 8),
  stop_price        numeric(18, 8),
  target_price      numeric(18, 8),
  last_event_id     uuid not null references trade_events(id),
  last_event_time   timestamptz not null,
  check (broker_trade_id is not null or client_intent_id is not null)
);
create unique index if not exists ux_trade_state_current_broker
  on trade_state_current(broker, broker_trade_id)
  where broker_trade_id is not null;
create unique index if not exists ux_trade_state_current_intent
  on trade_state_current(client_intent_id)
  where client_intent_id is not null and broker_trade_id is null;
create index if not exists idx_trade_state_current_live
  on trade_state_current(strategy_id, ticker, state)
  where state in ('INTENT_OPEN', 'OPEN', 'INTENT_CLOSE');

-- See migrations/001_trade_diary.sql for the trigger that keeps
-- trade_state_current in sync with trade_events.

-- ============================================================
-- ROW LEVEL SECURITY (diary tables)
-- ============================================================
alter table strategies              enable row level security;
alter table symbol_metadata         enable row level security;
alter table user_strategy_settings  enable row level security;
alter table trade_events            enable row level security;
alter table trade_state_current     enable row level security;

create policy "Authenticated read strategies" on strategies
  for select using (auth.role() = 'authenticated');
create policy "Authenticated read symbol_metadata" on symbol_metadata
  for select using (auth.role() = 'authenticated');
create policy "Users read own settings" on user_strategy_settings
  for select using (auth.uid() = user_id);
create policy "Users update own settings" on user_strategy_settings
  for update using (auth.uid() = user_id);
create policy "Users insert own settings" on user_strategy_settings
  for insert with check (auth.uid() = user_id);
create policy "Users delete own settings" on user_strategy_settings
  for delete using (auth.uid() = user_id);
create policy "Users read own trade events" on trade_events
  for select using (auth.uid() = user_id);
create policy "Users read own current state" on trade_state_current
  for select using (auth.uid() = user_id);

-- ============================================================
-- REALTIME (enable for tables the app subscribes to)
-- ============================================================
alter publication supabase_realtime add table positions;
alter publication supabase_realtime add table trades;
alter publication supabase_realtime add table orders;
alter publication supabase_realtime add table watchlist_zones;
alter publication supabase_realtime add table bot_logs;
alter publication supabase_realtime add table trade_events;
alter publication supabase_realtime add table trade_state_current;
alter publication supabase_realtime add table user_strategy_settings;
