-- Verify end-to-end consistency: Iceberg table must have exactly BATCH_COUNT records
-- Fails with error message if counts don't match expected values

.print '=== Verifying End-to-End Consistency ==='

-- Check that Iceberg table has expected count and all unique trade_ids
WITH iceberg_stats AS (
    SELECT
        COUNT(*) AS total_count,
        COUNT(DISTINCT trade_id) AS distinct_count
    FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet')
),
validation AS (
    SELECT
        total_count,
        distinct_count,
        50000 AS expected_count,
        CASE
            WHEN total_count = 50000 AND distinct_count = 50000 THEN 'PASS'
            ELSE 'FAIL'
        END AS status,
        CASE
            WHEN total_count != 50000 THEN 'Total count mismatch: expected 50000, got ' || total_count
            WHEN distinct_count != 50000 THEN 'Distinct trade_id count mismatch: expected 50000, got ' || distinct_count
            ELSE 'OK'
        END AS message
    FROM iceberg_stats
)
SELECT
    status,
    total_count,
    distinct_count,
    expected_count,
    message
FROM validation;

-- Fail if validation didn't pass
SELECT CASE
    WHEN (SELECT status FROM (
        SELECT
            CASE
                WHEN COUNT(*) = 50000 AND COUNT(DISTINCT trade_id) = 50000 THEN 'PASS'
                ELSE 'FAIL'
            END AS status
        FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet')
    )) = 'PASS' THEN 1
    ELSE CAST('Consistency check FAILED: count mismatch' AS INT)
END AS consistency_check_result;

.print ''
.print 'Consistency verification complete: PASS'
