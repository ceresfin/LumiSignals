-- ============================================================
-- Migration 002 — Live prices broadcast table
-- ============================================================
-- Single row per ticker, upserted by the IB sync (~every 2s) with the
-- latest market price. Mobile subscribes via Supabase realtime and
-- recomputes P&L client-side for sub-cycle freshness — independent of
-- whether the bot has just rewritten the per-position `unrealized_pl`.
--
-- The whole row is one record per symbol: writes are UPSERTs on
-- ticker. Realtime publishes UPDATE events so mobile sees the new
-- price within milliseconds of the bot's write.
-- ============================================================

create table if not exists live_prices (
  ticker     text primary key,
  price      numeric(18, 8) not null,
  bid        numeric(18, 8),
  ask        numeric(18, 8),
  source     text default 'ib_cpapi',
  ts         timestamptz not null default now()
);

-- Authenticated read-only — anyone with a session can subscribe.
alter table live_prices enable row level security;

drop policy if exists "Authenticated read live_prices" on live_prices;
create policy "Authenticated read live_prices" on live_prices
  for select using (auth.role() = 'authenticated');

-- Realtime publication (idempotent)
do $rt$
begin
  if not exists (
    select 1 from pg_publication_tables
     where pubname = 'supabase_realtime'
       and schemaname = 'public'
       and tablename = 'live_prices'
  ) then
    execute 'alter publication supabase_realtime add table live_prices';
  end if;
end$rt$;
