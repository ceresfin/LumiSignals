-- Slippage measurement support.
-- signal_price = the bar close TV's Pine alert was looking at when it fired.
-- entry_price already exists on OPEN rows = the actual IB fill price.
-- Slippage is computed on the fly: (entry_price - signal_price) * direction_sign,
-- where direction_sign is +1 for BUY, -1 for SELL. Positive = adverse.

alter table trade_events
  add column if not exists signal_price numeric(18, 8);

-- Index for the slippage stats endpoint — query by strategy_id + ticker + window.
create index if not exists trade_events_signal_price_idx
  on trade_events (strategy_id, ticker, event_time)
  where signal_price is not null;
