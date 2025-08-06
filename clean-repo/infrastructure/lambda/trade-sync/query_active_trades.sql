-- Query active trades from RDS to identify discrepancies with OANDA
-- Expected trades from OANDA: 1515, 914, 568, 516 (4 trades total)

\echo '=== RDS Active Trades Analysis ==='
\echo 'Expected OANDA trades: 1515, 914, 568, 516'
\echo ''

-- Show all active trades
\echo '--- ALL ACTIVE TRADES IN RDS ---'
SELECT 
    trade_id,
    instrument,
    direction,
    units,
    open_time,
    last_updated
FROM active_trades
ORDER BY trade_id DESC;

\echo ''
\echo '--- TRADE COUNT ANALYSIS ---'
SELECT 
    COUNT(*) as total_trades_in_rds,
    COUNT(*) - 4 as extra_trades_count
FROM active_trades;

\echo ''
\echo '--- EXTRA TRADES (not in OANDA) ---'
SELECT 
    trade_id,
    instrument,
    direction,
    units,
    open_time,
    'EXTRA - NOT IN OANDA' as status
FROM active_trades
WHERE trade_id NOT IN ('1515', '914', '568', '516')
ORDER BY trade_id DESC;

\echo ''
\echo '--- MISSING TRADES (in OANDA but not RDS) ---'
WITH expected_trades AS (
    SELECT unnest(ARRAY['1515', '914', '568', '516']) as expected_trade_id
)
SELECT 
    expected_trade_id,
    'MISSING FROM RDS' as status
FROM expected_trades
WHERE expected_trade_id NOT IN (
    SELECT trade_id::text FROM active_trades
);

\echo ''
\echo '--- SUMMARY ---'
WITH stats AS (
    SELECT 
        COUNT(*) as rds_trades,
        COUNT(CASE WHEN trade_id::text IN ('1515', '914', '568', '516') THEN 1 END) as matching_trades,
        COUNT(CASE WHEN trade_id::text NOT IN ('1515', '914', '568', '516') THEN 1 END) as extra_trades
    FROM active_trades
)
SELECT 
    'RDS Trades: ' || rds_trades as summary_line_1,
    'OANDA Trades: 4' as summary_line_2,
    'Matching: ' || matching_trades as summary_line_3,
    'Extra in RDS: ' || extra_trades as summary_line_4,
    'Missing in RDS: ' || (4 - matching_trades) as summary_line_5
FROM stats;