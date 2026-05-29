-- Account-type tagging for paper vs live separation.
--
-- IB uses the same login for paper (DUxxxxxx) and live (Uxxxxxx) accounts.
-- Without this column, the moment we switch the bot to the live account,
-- live trades start landing in the same rows as historical paper trades —
-- contaminating dashboard P&L, strategy win rate, and slippage stats.
--
-- All existing rows default to 'paper' because that's what we've been
-- running. New rows are tagged at write time based on the IB account ID
-- the bot is currently connected to (see lumisignals/account_type.py).

alter table trades
  add column if not exists account_type text default 'paper';

alter table positions
  add column if not exists account_type text default 'paper';

alter table trade_events
  add column if not exists account_type text default 'paper';

-- Backfill: belt + suspenders. The `default 'paper'` on the column
-- handles new rows; this handles any rows whose default didn't apply.
update trades        set account_type = 'paper' where account_type is null;
update positions     set account_type = 'paper' where account_type is null;
update trade_events  set account_type = 'paper' where account_type is null;

-- Indexes scoped per-account for fast dashboard filtering.
create index if not exists trades_account_type_closed_idx
  on trades (user_id, broker, account_type, closed_at);

create index if not exists trade_events_account_type_idx
  on trade_events (strategy_id, ticker, account_type, event_time);

create index if not exists positions_account_type_idx
  on positions (user_id, broker, account_type);
