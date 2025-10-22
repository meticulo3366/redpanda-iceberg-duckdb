#!/bin/bash
set -euo pipefail

# Create Redpanda topics for the demo
BROKER="${RP_BROKERS:-redpanda:9092}"
TOPIC="${RP_TOPIC_TRADES:-trades}"

echo "Creating topic: ${TOPIC}"
rpk topic create "${TOPIC}" \
  --brokers "${BROKER}" \
  --partitions 3 \
  --replicas 1 \
  --topic-config "cleanup.policy=delete" \
  --topic-config "retention.ms=86400000" \
  || echo "Topic ${TOPIC} may already exist"

echo "Listing topics:"
rpk topic list --brokers "${BROKER}"

echo "Topic seeding complete"
