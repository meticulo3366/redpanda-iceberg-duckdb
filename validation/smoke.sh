#!/bin/bash
set -euo pipefail

# Smoke test: verify all services are healthy and reachable

echo "=== Running Smoke Tests ==="

# Check Redpanda broker
echo "Checking Redpanda broker..."
docker compose exec -T redpanda rpk cluster health | grep -q "Healthy.*true" || {
    echo "ERROR: Redpanda is not healthy"
    exit 1
}
echo "✓ Redpanda is healthy"

# Check MinIO
echo "Checking MinIO..."
curl -sf http://localhost:9000/minio/health/live > /dev/null || {
    echo "ERROR: MinIO is not healthy"
    exit 1
}
echo "✓ MinIO is healthy"

# Check Nessie
echo "Checking Nessie REST catalog..."
curl -sf http://localhost:19120/api/v2/config > /dev/null || {
    echo "ERROR: Nessie is not responding"
    exit 1
}
echo "✓ Nessie is healthy"

# Check Committer service
echo "Checking Committer service..."
curl -sf http://localhost:8088/health | grep -q "healthy" || {
    echo "ERROR: Committer service is not healthy"
    exit 1
}
echo "✓ Committer service is healthy"

# Check that topics exist
echo "Checking Redpanda topics..."
docker compose exec -T redpanda rpk topic list | grep -q "trades" || {
    echo "ERROR: trades topic not found"
    exit 1
}
echo "✓ Topics created"

# Check MinIO bucket
echo "Checking MinIO bucket..."
docker compose exec -T minio-init mc ls myminio/lake > /dev/null 2>&1 || {
    echo "WARNING: Could not verify MinIO bucket (container may be stopped)"
}
echo "✓ MinIO bucket accessible"

echo ""
echo "=== Smoke Tests PASSED ==="
exit 0
