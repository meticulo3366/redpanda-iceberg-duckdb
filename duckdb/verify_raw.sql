-- Verify staged NDJSON files in MinIO
-- Checks total count and distinct trade_id count in staging area

.print '=== Verifying Raw Staged NDJSON Files ==='

-- Count total records in staged NDJSON files
SELECT
    COUNT(*) AS total_records,
    COUNT(DISTINCT trade_id) AS distinct_trade_ids,
    MIN(ts_event) AS earliest_event,
    MAX(ts_event) AS latest_event
FROM read_ndjson_auto('s3://lake/staging/trades/**/*.ndjson');

.print ''
.print 'Raw staging verification complete'
