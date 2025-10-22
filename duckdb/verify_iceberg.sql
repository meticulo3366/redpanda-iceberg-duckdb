-- Verify Iceberg table via direct Parquet reads
-- Checks total count, distinct trade_id count, and timestamp range

.print '=== Verifying Iceberg Table (Parquet Data Files) ==='

-- Read Iceberg data files directly (Parquet files in warehouse)
SELECT
    COUNT(*) AS total_records,
    COUNT(DISTINCT trade_id) AS distinct_trade_ids,
    MIN(ts_event) AS earliest_event,
    MAX(ts_event) AS latest_event,
    COUNT(DISTINCT symbol) AS distinct_symbols
FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet');

.print ''
.print 'Iceberg table verification complete'
