-- Verify Iceberg table via REST catalog
-- Query directly from iceberg_catalog.redpanda namespace

SELECT
    'Iceberg Table Verification' as check_name,
    COUNT(*) as record_count
FROM iceberg_catalog.redpanda.trades;

SELECT
    symbol,
    COUNT(*) as trade_count,
    ROUND(AVG(price), 2) as avg_price,
    SUM(qty) as total_volume
FROM iceberg_catalog.redpanda.trades
GROUP BY symbol
ORDER BY total_volume DESC;
