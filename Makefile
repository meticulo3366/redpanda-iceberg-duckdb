.PHONY: up down produce sink verify-stage verify-iceberg verify-consistency show-snapshot e2e clean help

# Load environment variables
include .env
export

# Default target
help:
	@echo "Redpanda -> Iceberg E2E Demo (No Spark)"
	@echo ""
	@echo "Available targets:"
	@echo "  up                    - Start all Docker services"
	@echo "  down                  - Stop and remove all Docker services"
	@echo "  produce               - Produce deterministic trade data to Redpanda"
	@echo "  sink                  - Run Redpanda Connect to stage & commit data"
	@echo "  verify-stage          - Verify staged NDJSON files in MinIO"
	@echo "  verify-iceberg        - Verify Iceberg table (Parquet files)"
	@echo "  verify-consistency    - Verify end-to-end count consistency"
	@echo "  show-snapshot         - Show Nessie commit history"
	@echo "  e2e                   - Run complete end-to-end workflow"
	@echo "  clean                 - Clean up all data and containers"
	@echo ""
	@echo "Quick start:"
	@echo "  make up && make produce && make sink"
	@echo "  # In another terminal after first batch:"
	@echo "  make verify-stage && make verify-iceberg && make verify-consistency"

# Start all services
up:
	@echo "=== Starting Docker services ==="
	docker compose up -d redpanda minio nessie committer duckdb-cli
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@docker compose up -d minio-init
	@echo "Waiting for initialization to complete..."
	@sleep 10
	@echo "Creating Redpanda topics..."
	docker compose exec -T redpanda bash -c 'cd /tmp && rpk topic create $(RP_TOPIC_TRADES) --brokers $(RP_BROKERS) --partitions 3 --replicas 1 || echo "Topic may already exist"'
	@echo ""
	@echo "Services started successfully!"
	@echo "  - Redpanda Console: http://localhost:8080"
	@echo "  - MinIO Console: http://localhost:9001"
	@echo "  - Nessie API: http://localhost:19120/api/v2"
	@echo "  - Committer API: http://localhost:8088"

# Stop all services
down:
	@echo "=== Stopping Docker services ==="
	docker compose down -v
	@echo "Services stopped and volumes removed"

# Produce trade data
produce:
	@echo "=== Producing trade data ==="
	docker compose run --rm producer \
		--brokers redpanda:9092 \
		--topic $(RP_TOPIC_TRADES) \
		--count $(BATCH_COUNT) \
		--seed $(SEED)
	@echo ""
	@echo "Production complete: $(BATCH_COUNT) trades produced"

# Run Redpanda Connect sink
sink:
	@echo "=== Running Redpanda Connect sink ==="
	@echo "This will run in the foreground. Press Ctrl+C to stop after first batch commits."
	docker compose run --rm \
		-e RP_BROKERS=$(RP_BROKERS) \
		-e RP_TOPIC_TRADES=$(RP_TOPIC_TRADES) \
		-e MINIO_ENDPOINT=$(MINIO_ENDPOINT) \
		-e MINIO_ACCESS_KEY=$(MINIO_ACCESS_KEY) \
		-e MINIO_SECRET_KEY=$(MINIO_SECRET_KEY) \
		-e MINIO_BUCKET=$(MINIO_BUCKET) \
		-e MINIO_REGION=$(MINIO_REGION) \
		-e COMMITTER_PORT=$(COMMITTER_PORT) \
		-e STAGE_PREFIX=$(STAGE_PREFIX) \
		connect \
		-c /config/s3_stage_and_commit.yaml

# Verify staged NDJSON files
verify-stage:
	@echo "=== Verifying staged NDJSON files ==="
	docker compose exec -T duckdb-cli duckdb -c ".read duckdb/common.sql" -c ".read duckdb/verify_raw.sql"

# Verify Iceberg table
verify-iceberg:
	@echo "=== Verifying Iceberg table ==="
	docker compose exec -T duckdb-cli duckdb -c ".read duckdb/common.sql" -c ".read duckdb/verify_iceberg.sql"

# Verify end-to-end consistency
verify-consistency:
	@echo "=== Verifying end-to-end consistency ==="
	docker compose exec -T duckdb-cli duckdb -c ".read duckdb/common.sql" -c ".read duckdb/verify_consistency.sql"

# Show Nessie snapshot history
show-snapshot:
	@echo "=== Nessie Commit History ==="
	curl -s http://localhost:19120/api/v2/trees | jq '.' || echo "Nessie not responding"

# Complete end-to-end workflow
e2e:
	@echo "=== Running End-to-End Workflow ==="
	@$(MAKE) produce
	@echo ""
	@echo "Starting sink in background..."
	@$(MAKE) sink > /tmp/sink.log 2>&1 & echo $$! > /tmp/sink.pid
	@sleep 60  # Wait for first batch
	@if [ -f /tmp/sink.pid ]; then kill `cat /tmp/sink.pid` 2>/dev/null || true; rm /tmp/sink.pid; fi
	@sleep 10  # Wait for commit to complete
	@echo ""
	@$(MAKE) verify-stage
	@echo ""
	@$(MAKE) verify-iceberg
	@echo ""
	@$(MAKE) verify-consistency
	@echo ""
	@echo "=== End-to-End Workflow Complete ==="
	@echo "All verification checks passed!"

# Clean up everything
clean: down
	@echo "=== Cleaning up ==="
	@rm -f /tmp/sink.log /tmp/sink.pid
	@echo "Cleanup complete"
