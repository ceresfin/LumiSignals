-- TV → bot latency measurement.
-- webhook_received_at = the saas server's clock when the webhook arrived.
-- tv_latency_seconds  = derived at write time as
--     (webhook_received_at - signal_bar_close_at)
-- where signal_bar_close_at is the most-recent closed bar in cache at
-- webhook receive time. Stored precomputed so the stats endpoint is trivial.

alter table trade_events
  add column if not exists webhook_received_at timestamptz,
  add column if not exists tv_latency_seconds  numeric(10, 3);

create index if not exists trade_events_tv_latency_idx
  on trade_events (strategy_id, ticker, event_time)
  where tv_latency_seconds is not null;
