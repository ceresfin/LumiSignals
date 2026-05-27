-- ============================================================
-- Migration 001 — Trade Diary + Symbol/Strategy Registries
-- ============================================================
-- Adds an event-sourced trade diary plus the registries it depends on.
-- Goal: eliminate orphan/phantom positions by recording every state
-- transition before the bot acts on it, and reconciling against the
-- broker every sync tick.
--
-- Safe to run on existing databases. All statements are idempotent
-- (create if not exists / on conflict do nothing for seed data).
--
-- Tables created:
--   strategies              — registry mapping stable slugs → display names
--   symbol_metadata         — per-ticker contract specs, sessions, broker IDs
--   user_strategy_settings  — per-user, per-strategy, per-ticker overrides
--   trade_events            — the diary (append-only log of state changes)
-- ============================================================


-- ============================================================
-- 1. STRATEGIES (stable slug → display name registry)
-- ============================================================
create table if not exists strategies (
  strategy_id   text primary key,           -- stable slug, never changes
  display_name  text not null,              -- editable, shown in UI
  description   text,
  asset_classes text[] not null default '{}',  -- {'futures'}, {'fx'}, etc.
  active        boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists idx_strategies_active
  on strategies(active) where active = true;


-- ============================================================
-- 2. SYMBOL METADATA (per-ticker contract specs)
-- ============================================================
create table if not exists symbol_metadata (
  ticker             text primary key,                 -- 'MES', 'EUR_USD', etc.
  asset_class        text not null,                    -- futures | fx | equity | crypto | options
  exchange           text not null,                    -- 'CME', 'OANDA', 'NASDAQ'
  tick_size          numeric(18, 8) not null,          -- 0.25 for MES
  multiplier         numeric(18, 8) not null,          -- $/pt — 5 for MES, 2 for MNQ
  quote_currency     text not null default 'USD',

  -- Session window (local time the exchange is "open" for trading)
  session_open_local   time,                           -- '18:00' for CME futures
  session_close_local  time,                           -- '17:00' for CME futures
  session_tz           text,                           -- 'America/New_York'
  trades_overnight     boolean not null default false, -- true for CME futures

  -- Broker-symbol mapping (nullable — fill what's relevant)
  ib_conid           bigint,                           -- IB contract id
  oanda_instrument   text,                             -- 'EUR_USD'
  pine_alert_symbol  text,                             -- 'CME_MINI:MES1!'

  active             boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists idx_symbol_metadata_asset_class
  on symbol_metadata(asset_class) where active = true;
create index if not exists idx_symbol_metadata_pine
  on symbol_metadata(pine_alert_symbol) where pine_alert_symbol is not null;


-- ============================================================
-- 3. USER STRATEGY SETTINGS (per user / strategy / ticker)
-- ============================================================
-- A NULL ticker row acts as the default for that user+strategy across
-- every ticker. Specific (user, strategy, ticker) rows override.
-- ============================================================
create table if not exists user_strategy_settings (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles(id) on delete cascade,
  strategy_id     text not null references strategies(strategy_id),
  ticker          text references symbol_metadata(ticker),  -- NULL = default
  stop_loss_usd   numeric(12, 2),
  take_profit_usd numeric(12, 2),
  qty             int not null default 1 check (qty > 0),
  enabled         boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Treat NULL ticker as a real value for uniqueness (one default per
-- user+strategy, plus one override per ticker).
create unique index if not exists ux_user_strategy_ticker
  on user_strategy_settings(user_id, strategy_id, coalesce(ticker, ''));

create index if not exists idx_user_strategy_settings_user
  on user_strategy_settings(user_id) where enabled = true;


-- ============================================================
-- 4. TRADE EVENTS (the diary — append-only)
-- ============================================================
-- One row per state transition for one broker trade.
-- Current state of a trade = latest row by event_time for that broker_trade_id.
--
-- States (see lumisignals/diary.py for the canonical enum):
--   INTENT_OPEN          — we asked broker to open
--   OPEN                 — broker confirmed fill
--   INTENT_CLOSE         — we asked broker to close
--   CLOSED               — broker confirmed flat
--   STOP_FIRED           — stop loss triggered close
--   CANCELLED            — order died without filling
--   RECONCILE_GONE       — diary said OPEN, broker said flat (orphan close path)
--   RECONCILE_PHANTOM    — diary said CLOSED, broker shows position
--   RECONCILE_ADOPTED    — we attached an unknown broker position to a strategy
-- ============================================================
create table if not exists trade_events (
  id                uuid primary key default gen_random_uuid(),

  -- Identity
  broker            text not null,                    -- 'ib' | 'oanda' | future
  broker_trade_id   text,                             -- nullable: pre-fill we may not have one yet
  client_intent_id  uuid,                             -- our own id, set on INTENT_OPEN; bridges pre-fill state
  strategy_id       text not null references strategies(strategy_id),
  ticker            text not null references symbol_metadata(ticker),
  user_id           uuid not null references profiles(id) on delete cascade,

  -- State
  state             text not null,                    -- enum-like; see comment above
  event_time        timestamptz not null default now(),
  reason            text,                             -- "TV CLOSE_LONG", "stop fired", etc.

  -- Position truth at this moment
  expected_qty      int,                              -- signed: +1 long, -1 short, 0 flat
  observed_qty      int,                              -- what broker actually shows (filled in by reconciler)

  -- Pricing
  entry_price       numeric(18, 8),
  exit_price        numeric(18, 8),
  stop_price        numeric(18, 8),
  target_price      numeric(18, 8),
  realized_pl       numeric(18, 4),

  -- Raw broker payload at this event (for forensics)
  broker_snapshot   jsonb,
  -- Strategy-specific extras (option legs, zone metadata, etc.)
  meta              jsonb,

  created_at        timestamptz not null default now()
);

-- Lookup by external id (the hot path — used on every webhook & sync tick)
create index if not exists idx_trade_events_broker_trade
  on trade_events(broker, broker_trade_id) where broker_trade_id is not null;

-- Lookup by intent id (covers the pre-fill window)
create index if not exists idx_trade_events_intent
  on trade_events(client_intent_id) where client_intent_id is not null;

-- Reconciler scans: "what's live for this strategy+ticker?"
create index if not exists idx_trade_events_live
  on trade_events(strategy_id, ticker, state)
  where state in ('INTENT_OPEN', 'OPEN', 'INTENT_CLOSE');

-- Mobile diary view
create index if not exists idx_trade_events_user_time
  on trade_events(user_id, event_time desc);


-- ============================================================
-- 5. CURRENT TRADE STATE (materialized view for fast lookups)
-- ============================================================
-- "What is the latest state of every trade?"  Refreshed on every
-- diary write via trigger below (cheap — single-row upsert).
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
  -- Either broker_trade_id or client_intent_id must be set (the trade's identity)
  check (broker_trade_id is not null or client_intent_id is not null)
);

-- Backfill PK on existing installs (no-op if already present).
alter table trade_state_current
  add column if not exists id uuid not null default gen_random_uuid();
do $pk$
begin
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'trade_state_current'::regclass and contype = 'p'
  ) then
    alter table trade_state_current add primary key (id);
  end if;
end$pk$;

-- One row per trade identity. Prefer broker_trade_id once known, else intent.
create unique index if not exists ux_trade_state_current_broker
  on trade_state_current(broker, broker_trade_id)
  where broker_trade_id is not null;
create unique index if not exists ux_trade_state_current_intent
  on trade_state_current(client_intent_id)
  where client_intent_id is not null and broker_trade_id is null;

create index if not exists idx_trade_state_current_live
  on trade_state_current(strategy_id, ticker, state)
  where state in ('INTENT_OPEN', 'OPEN', 'INTENT_CLOSE');


-- Trigger: keep trade_state_current in sync with the diary.
create or replace function update_trade_state_current() returns trigger
language plpgsql as $$
begin
  -- Upsert by broker_trade_id if we have one, else by client_intent_id.
  if new.broker_trade_id is not null then
    insert into trade_state_current (
      broker_trade_id, client_intent_id, broker, strategy_id, ticker, user_id,
      state, expected_qty, observed_qty, entry_price, stop_price, target_price,
      last_event_id, last_event_time
    ) values (
      new.broker_trade_id, new.client_intent_id, new.broker, new.strategy_id,
      new.ticker, new.user_id, new.state, new.expected_qty, new.observed_qty,
      new.entry_price, new.stop_price, new.target_price, new.id, new.event_time
    )
    on conflict (broker, broker_trade_id) where broker_trade_id is not null
    do update set
      client_intent_id = coalesce(excluded.client_intent_id, trade_state_current.client_intent_id),
      state            = excluded.state,
      expected_qty     = coalesce(excluded.expected_qty, trade_state_current.expected_qty),
      observed_qty     = coalesce(excluded.observed_qty, trade_state_current.observed_qty),
      entry_price      = coalesce(excluded.entry_price,  trade_state_current.entry_price),
      stop_price       = coalesce(excluded.stop_price,   trade_state_current.stop_price),
      target_price     = coalesce(excluded.target_price, trade_state_current.target_price),
      last_event_id    = excluded.last_event_id,
      last_event_time  = excluded.last_event_time;

    -- If this event brought in a broker_trade_id for an intent we'd
    -- previously seen, retire the orphan intent row.
    if new.client_intent_id is not null then
      delete from trade_state_current
       where client_intent_id = new.client_intent_id
         and broker_trade_id is null;
    end if;
  else
    insert into trade_state_current (
      broker_trade_id, client_intent_id, broker, strategy_id, ticker, user_id,
      state, expected_qty, observed_qty, entry_price, stop_price, target_price,
      last_event_id, last_event_time
    ) values (
      null, new.client_intent_id, new.broker, new.strategy_id,
      new.ticker, new.user_id, new.state, new.expected_qty, new.observed_qty,
      new.entry_price, new.stop_price, new.target_price, new.id, new.event_time
    )
    on conflict (client_intent_id) where client_intent_id is not null and broker_trade_id is null
    do update set
      state           = excluded.state,
      expected_qty    = coalesce(excluded.expected_qty, trade_state_current.expected_qty),
      observed_qty    = coalesce(excluded.observed_qty, trade_state_current.observed_qty),
      entry_price     = coalesce(excluded.entry_price,  trade_state_current.entry_price),
      stop_price      = coalesce(excluded.stop_price,   trade_state_current.stop_price),
      target_price    = coalesce(excluded.target_price, trade_state_current.target_price),
      last_event_id   = excluded.last_event_id,
      last_event_time = excluded.last_event_time;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_trade_events_update_current on trade_events;
create trigger trg_trade_events_update_current
  after insert on trade_events
  for each row execute function update_trade_state_current();


-- ============================================================
-- 6. SEED DATA — strategies registry
-- ============================================================
insert into strategies (strategy_id, display_name, description, asset_classes) values
  ('futures_2n20',     'Tidewater Scalp',  '2-bar/20-EMA pullback on micro futures',  '{futures}'),
  ('fx_4h_trend',      'Stillwater',       'FX 4H trend continuation',                '{fx}'),
  ('fx_h1_zone',       'H1 Zone α/β',      'FX H1 supply/demand zone scalp',          '{fx}'),
  ('htf_levels_swing', 'Tidewater Swing',  'Monthly zone swing, 1W bias / 1D trigger','{fx}'),
  ('htf_levels_intraday', 'Tidewater Intraday', 'HTF zone intraday continuation',     '{fx}'),
  ('options_credit',   'Credit Spreads',   '0DTE / weekly credit spreads',            '{options}'),
  ('orb_breakout',     'ORB breakout',     '0DTE / intraday opening-range breakout',  '{futures,equity}'),
  ('manual',           'Manual / GUI',     'User-initiated trade — entered via IB GUI or mobile, auto-adopted by reconciler', '{}'),
  ('manual_close',     'Manual close',     'Triggered from mobile/web Close button',  '{}'),
  ('untracked',        'Untracked',        'Pseudo-strategy used when no diary attribution', '{}'),
  ('unknown',          'Unattributed',     'Reconciler placeholder for phantom positions with no diary attribution', '{}')
on conflict (strategy_id) do update set
  display_name = excluded.display_name,
  description  = excluded.description,
  asset_classes = excluded.asset_classes,
  updated_at = now();


-- ============================================================
-- 7. SEED DATA — symbol_metadata
-- ============================================================
insert into symbol_metadata (
  ticker, asset_class, exchange, tick_size, multiplier, quote_currency,
  session_open_local, session_close_local, session_tz, trades_overnight,
  pine_alert_symbol, oanda_instrument
) values
  -- Micro futures (CME, overnight session 6pm-5pm ET)
  ('MES', 'futures', 'CME',   0.25, 5,   'USD', '18:00', '17:00', 'America/New_York', true, 'CME_MINI:MES1!', null),
  ('MNQ', 'futures', 'CME',   0.25, 2,   'USD', '18:00', '17:00', 'America/New_York', true, 'CME_MINI:MNQ1!', null),
  ('MGC', 'futures', 'COMEX', 0.10, 10,  'USD', '18:00', '17:00', 'America/New_York', true, 'COMEX_MINI:MGC1!', null),
  ('MCL', 'futures', 'NYMEX', 0.01, 100, 'USD', '18:00', '17:00', 'America/New_York', true, 'NYMEX_MINI:MCL1!', null),

  -- FX majors (Oanda, 24/5)
  ('EUR_USD', 'fx', 'OANDA', 0.0001, 1, 'USD', '17:00', '17:00', 'America/New_York', true, 'OANDA:EURUSD', 'EUR_USD'),
  ('GBP_USD', 'fx', 'OANDA', 0.0001, 1, 'USD', '17:00', '17:00', 'America/New_York', true, 'OANDA:GBPUSD', 'GBP_USD'),
  ('AUD_USD', 'fx', 'OANDA', 0.0001, 1, 'USD', '17:00', '17:00', 'America/New_York', true, 'OANDA:AUDUSD', 'AUD_USD'),
  ('NZD_USD', 'fx', 'OANDA', 0.0001, 1, 'USD', '17:00', '17:00', 'America/New_York', true, 'OANDA:NZDUSD', 'NZD_USD'),
  ('USD_JPY', 'fx', 'OANDA', 0.01,   1, 'JPY', '17:00', '17:00', 'America/New_York', true, 'OANDA:USDJPY', 'USD_JPY'),
  ('USD_CAD', 'fx', 'OANDA', 0.0001, 1, 'CAD', '17:00', '17:00', 'America/New_York', true, 'OANDA:USDCAD', 'USD_CAD'),
  ('USD_CHF', 'fx', 'OANDA', 0.0001, 1, 'CHF', '17:00', '17:00', 'America/New_York', true, 'OANDA:USDCHF', 'USD_CHF'),
  ('EUR_JPY', 'fx', 'OANDA', 0.01,   1, 'JPY', '17:00', '17:00', 'America/New_York', true, 'OANDA:EURJPY', 'EUR_JPY'),
  ('GBP_JPY', 'fx', 'OANDA', 0.01,   1, 'JPY', '17:00', '17:00', 'America/New_York', true, 'OANDA:GBPJPY', 'GBP_JPY'),

  -- Equity indices (used by reconciler when slow-tier flags SPX options or stock holdings)
  ('SPX', 'equity', 'CBOE',    0.01, 100, 'USD', null, null, null, false, null, null),
  ('SPY', 'equity', 'ARCA',    0.01, 100, 'USD', null, null, null, false, null, null),
  ('NDX', 'equity', 'NASDAQ',  0.01, 100, 'USD', null, null, null, false, null, null),
  ('QQQ', 'equity', 'NASDAQ',  0.01, 100, 'USD', null, null, null, false, null, null),
  ('RUT', 'equity', 'RUSSELL', 0.01, 100, 'USD', null, null, null, false, null, null),
  ('IWM', 'equity', 'ARCA',    0.01, 100, 'USD', null, null, null, false, null, null)
on conflict (ticker) do update set
  asset_class       = excluded.asset_class,
  exchange          = excluded.exchange,
  tick_size         = excluded.tick_size,
  multiplier        = excluded.multiplier,
  quote_currency    = excluded.quote_currency,
  session_open_local  = excluded.session_open_local,
  session_close_local = excluded.session_close_local,
  session_tz          = excluded.session_tz,
  trades_overnight    = excluded.trades_overnight,
  pine_alert_symbol = excluded.pine_alert_symbol,
  oanda_instrument  = excluded.oanda_instrument,
  updated_at        = now();


-- ============================================================
-- 8. BACKFILL — port existing per-user futures settings into
-- user_strategy_settings as the futures_2n20 default row.
-- ============================================================
-- This relies on a `profiles.futures_stop_loss` / `profiles.futures_contracts`
-- column existing (created in schema.sql). The insert is a no-op if those
-- columns are absent — wrap in a guard for safety.
do $$
begin
  if exists (
    select 1 from information_schema.columns
     where table_name = 'profiles' and column_name = 'futures_stop_loss'
  ) then
    insert into user_strategy_settings (user_id, strategy_id, ticker, stop_loss_usd, qty)
    select p.id, 'futures_2n20', null,
           coalesce(p.futures_stop_loss::numeric, 25),
           coalesce(p.futures_contracts, 1)
      from profiles p
    on conflict (user_id, strategy_id, coalesce(ticker, '')) do nothing;
  end if;
end$$;


-- ============================================================
-- 9. ROW LEVEL SECURITY
-- ============================================================
alter table strategies              enable row level security;
alter table symbol_metadata         enable row level security;
alter table user_strategy_settings  enable row level security;
alter table trade_events            enable row level security;
alter table trade_state_current     enable row level security;

-- Registries are world-readable to authenticated users
drop policy if exists "Authenticated read strategies" on strategies;
create policy "Authenticated read strategies" on strategies
  for select using (auth.role() = 'authenticated');

drop policy if exists "Authenticated read symbol_metadata" on symbol_metadata;
create policy "Authenticated read symbol_metadata" on symbol_metadata
  for select using (auth.role() = 'authenticated');

-- Per-user tables
drop policy if exists "Users read own settings" on user_strategy_settings;
create policy "Users read own settings" on user_strategy_settings
  for select using (auth.uid() = user_id);

drop policy if exists "Users update own settings" on user_strategy_settings;
create policy "Users update own settings" on user_strategy_settings
  for update using (auth.uid() = user_id);

drop policy if exists "Users insert own settings" on user_strategy_settings;
create policy "Users insert own settings" on user_strategy_settings
  for insert with check (auth.uid() = user_id);

drop policy if exists "Users delete own settings" on user_strategy_settings;
create policy "Users delete own settings" on user_strategy_settings
  for delete using (auth.uid() = user_id);

drop policy if exists "Users read own trade events" on trade_events;
create policy "Users read own trade events" on trade_events
  for select using (auth.uid() = user_id);

drop policy if exists "Users read own current state" on trade_state_current;
create policy "Users read own current state" on trade_state_current
  for select using (auth.uid() = user_id);


-- ============================================================
-- 10. REALTIME — let the mobile app subscribe to diary changes
-- ============================================================
do $rt$
declare t text;
begin
  foreach t in array array['trade_events','trade_state_current','user_strategy_settings']
  loop
    if not exists (
      select 1 from pg_publication_tables
       where pubname = 'supabase_realtime'
         and schemaname = 'public'
         and tablename = t
    ) then
      execute format('alter publication supabase_realtime add table %I', t);
    end if;
  end loop;
end$rt$;
