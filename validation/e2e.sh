#!/bin/bash
set -euo pipefail

# End-to-end test: full pipeline from Redpanda -> Iceberg -> DuckDB -> Redpanda
# This script runs the complete workflow and validates results

cd "$(dirname "$0")/.."  # Change to rp-e2e-nospark directory

echo "=== Starting End-to-End Test ==="

# Clean up any existing environment
echo "Cleaning up previous environment..."
docker compose down -v 2>/dev/null || true

# Build duckdb-cli container
echo ""
echo "Step 0: Building duckdb-cli container (includes Python + packages)..."
docker compose build duckdb-cli

# Start all services
echo ""
echo "Step 1: Starting services..."
docker compose up -d redpanda minio catalog committer console duckdb-cli

# Wait for services to be fully ready
echo "Waiting for services to stabilize..."
sleep 15

# Check service health
echo "Checking service health..."
docker compose ps

# Create topics
echo ""
echo "Step 2: Creating Redpanda topics..."
docker compose exec -T redpanda rpk topic create trades --partitions 3 --replicas 1 2>/dev/null || echo "Topic 'trades' may already exist"
docker compose exec -T redpanda rpk topic create trade_analytics --partitions 1 --replicas 1 2>/dev/null || echo "Topic 'trade_analytics' may already exist"

# Produce data
echo ""
echo "Step 3: Producing trade data..."
docker compose run --rm producer \
    --brokers redpanda:9092 \
    --topic trades \
    --count 50000 \
    --seed 42

# Wait a moment for messages to be available
sleep 2

# Run sink (Connect pipeline) - use run instead of up to avoid networking issues
echo ""
echo "Step 4: Running Redpanda Connect sink (Redpanda -> S3 -> Iceberg)..."
docker compose run --rm connect &
SINK_PID=$!

# Wait for at least one batch to complete
echo "Waiting for first batch to be processed..."
RETRIES=0
MAX_RETRIES=60
while [ $RETRIES -lt $MAX_RETRIES ]; do
    if docker compose logs committer 2>/dev/null | grep -q "Appended.*to Iceberg table"; then
        echo "✓ First batch processed and committed to Iceberg!"
        sleep 5  # Give it time to finish current batch
        # Stop the connect service gracefully
        docker compose stop connect 2>/dev/null || true
        docker compose rm -f connect 2>/dev/null || true
        # Don't wait for background process, just continue
        break
    fi
    sleep 2
    RETRIES=$((RETRIES + 1))
done

if [ $RETRIES -eq $MAX_RETRIES ]; then
    echo "ERROR: Timeout waiting for Iceberg commit"
    docker compose stop connect 2>/dev/null || true
    docker compose logs committer
    exit 1
fi

# Give committer time to finish processing
echo "Waiting for committer to complete..."
sleep 10

# Verify Iceberg table with DuckDB
echo ""
echo "Step 5: Verifying Iceberg table with DuckDB..."
docker compose exec -T duckdb-cli duckdb -c ".read duckdb/common.sql" -c ".read duckdb/verify_iceberg.sql"

# Query Iceberg with DuckDB and publish results back to Redpanda
echo ""
echo "Step 6: Querying Iceberg with DuckDB and publishing to Redpanda..."
docker compose exec -T \
    -e RP_BROKERS=redpanda:9092 \
    -e RP_TOPIC_RESULTS=trade_analytics \
    -e MINIO_ENDPOINT=http://minio:9000 \
    -e MINIO_ACCESS_KEY=minioadmin \
    -e MINIO_SECRET_KEY=minioadmin \
    -e MINIO_REGION=us-east-1 \
    duckdb-cli python3 /workspace/duckdb/query_and_publish.py

# Verify the analytics were published to Redpanda
echo ""
echo "Step 7: Verifying analytics published to Redpanda..."
echo "Consuming from trade_analytics topic (expecting 8 symbols):"
# Only consume 8 messages since we have 8 symbols
docker compose exec -T redpanda rpk topic consume trade_analytics --num 8 --format json

# Show summary
echo ""
echo "Step 8: Summary of Iceberg table..."
docker compose exec -T duckdb-cli duckdb -c ".read duckdb/common.sql" -c "
SELECT
    'Total Records' as metric,
    COUNT(*)::VARCHAR as value
FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet')
UNION ALL
SELECT
    'Unique Symbols' as metric,
    COUNT(DISTINCT symbol)::VARCHAR as value
FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet')
UNION ALL
SELECT
    'Date Range' as metric,
    MIN(ts_event)::VARCHAR || ' to ' || MAX(ts_event)::VARCHAR as value
FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet');
"

echo ""
echo "=== End-to-End Test PASSED ==="
echo "✓ Data successfully flowed through complete pipeline:"
echo "  1. Producer -> Redpanda (trades topic)"
echo "  2. Redpanda Connect -> MinIO S3 (NDJSON staging)"
echo "  3. Committer -> Iceberg table (Parquet files)"
echo "  4. DuckDB -> Query Iceberg table"
echo "  5. DuckDB -> Redpanda (trade_analytics topic)"
echo ""
echo "Services are still running. To clean up, run: docker compose down -v"
exit 0
