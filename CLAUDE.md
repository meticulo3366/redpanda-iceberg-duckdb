# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Redpanda Iceberg Topics → DuckDB → Redpanda** streaming lakehouse pipeline demonstrating Redpanda's **native Iceberg integration** with Polaris REST catalog. The architecture is **significantly simplified** compared to traditional approaches - no Spark, no custom committer services, no Redpanda Connect needed.

**Key Architecture:**
1. **Redpanda** with native Iceberg Topics → Automatically creates Iceberg tables
2. **Apache Polaris** (REST catalog) → Manages Iceberg metadata
3. **PostgreSQL** → Stores Polaris metadata
4. **MinIO** → S3-compatible storage for Parquet files
5. **DuckDB** → Queries Iceberg tables via REST catalog and publishes analytics

## Common Commands

### Build and Testing
```bash
# Build DuckDB container (includes Python + confluent-kafka)
docker compose build duckdb-cli

# Run complete end-to-end test (recommended)
./validation/e2e.sh

# Start all services manually
docker compose up -d

# Check service health
docker compose ps
```

### Working with Redpanda Iceberg Topics
```bash
# Create topic with Iceberg mode (native integration)
docker compose exec redpanda rpk topic create trades \
    --partitions 1 \
    --replicas 1 \
    --topic-config=redpanda.iceberg.mode=value_schema_latest

# Register JSON schema for topic
docker compose exec redpanda rpk registry schema create trades-value \
    --schema @schema.json \
    --type json

# Produce test data
docker compose run --rm producer \
    --brokers redpanda:9092 \
    --topic trades \
    --count 10000 \
    --seed 42

# Wait for automatic Iceberg snapshot (10 seconds default)
sleep 15
```

### Querying with DuckDB
```bash
# Generate DuckDB init script with OAuth2 token
docker compose exec duckdb-cli /workspace/duckdb/get_token.sh

# Query Iceberg table via REST catalog
docker compose exec duckdb-cli duckdb -init /workspace/duckdb/init-env.sql -c "
SELECT symbol, COUNT(*) as trades
FROM iceberg_catalog.redpanda.trades
GROUP BY symbol;
"

# Query and publish analytics to Kafka
docker compose exec \
    -e RP_BROKERS=redpanda:9092 \
    -e RP_TOPIC_RESULTS=trade_analytics \
    duckdb-cli python3 /workspace/duckdb/query_and_publish.py
```

### Debugging
```bash
# Check Redpanda Iceberg logs
docker compose logs redpanda | grep -i iceberg

# Check Polaris catalog
TOKEN=$(curl -s -X POST http://localhost:8181/api/catalog/v1/oauth/tokens \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=root&client_secret=pass&scope=PRINCIPAL_ROLE:ALL" \
  | jq -r '.access_token')

curl -s http://localhost:8181/api/management/v1/catalogs \
  -H "Authorization: Bearer $TOKEN" | jq

# Check MinIO files
docker compose exec minio-init mc ls myminio/redpanda --recursive

# Redpanda Console
# http://localhost:8080

# MinIO Console (login: minioadmin/minioadmin)
# http://localhost:9001

# Cleanup
docker compose down -v
```

## Architecture Details

### Bidirectional Iceberg Data Flow

This demo showcases a **complete bidirectional Iceberg cycle**:

1. **Ingestion**: Producer writes trades to Redpanda `trades` topic (with `redpanda.iceberg.mode=value_schema_latest`)
2. **Auto-Snapshot 1**: Redpanda's native Iceberg integration creates `trades` Iceberg table (snapshots every 10s)
3. **Storage**: Parquet files written to MinIO S3 (`s3://redpanda/`), metadata registered in Polaris catalog
4. **Query 1**: DuckDB connects to Polaris REST catalog and queries `trades` Iceberg table
5. **Analytics Publish**: DuckDB aggregates data and publishes to `trade_analytics` topic (ALSO with Iceberg mode!)
6. **Auto-Snapshot 2**: Redpanda creates `trade_analytics` Iceberg table automatically
7. **Query 2**: DuckDB queries `trade_analytics` Iceberg table (completing the cycle!)

**Result**: Kafka → Iceberg → DuckDB → Kafka → Iceberg → DuckDB (full bidirectional flow)

### What's Different from Traditional Approaches

**❌ Removed Components:**
- **No Spark** - Not needed for small-medium scale workloads
- **No Custom Committer Service** - Redpanda handles Iceberg natively
- **No Redpanda Connect/Benthos** - Built-in Iceberg Topics feature handles data movement
- **No Tabular Catalog** - Replaced with open-source Apache Polaris

**✅ Simplified Stack:**
- Redpanda with `iceberg_enabled=true` and REST catalog configuration
- Polaris for standard Iceberg REST catalog API
- PostgreSQL for Polaris metadata storage
- DuckDB with Iceberg extension for analytics

### Key Components

#### Redpanda with Iceberg Topics (`docker-compose.yml`)
Redpanda v25.2.2+ includes native Iceberg integration configured via cluster settings:

```yaml
# Critical Iceberg settings
--set=iceberg_enabled=true
--set=iceberg_catalog_type=rest
--set=iceberg_rest_catalog_endpoint=http://polaris:8181/api/catalog/
--set=iceberg_rest_catalog_oauth2_server_uri=http://polaris:8181/api/catalog/v1/oauth/tokens
--set=iceberg_rest_catalog_authentication_mode=oauth2
--set=iceberg_rest_catalog_client_id=root
--set=iceberg_rest_catalog_client_secret=pass
--set=iceberg_rest_catalog_warehouse=redpanda_catalog
--set=iceberg_target_lag_ms=10000  # Snapshot frequency (10 seconds)

# Tiered storage settings
--set=cloud_storage_enabled=true
--set=cloud_storage_bucket=redpanda
--set=cloud_storage_api_endpoint=minio:9000
--set=cloud_storage_access_key=minioadmin
--set=cloud_storage_secret_key=minioadmin
--set=cloud_storage_disable_tls=true
--set=cloud_storage_url_style=path
```

**How It Works:**
- Topics created with `--topic-config=redpanda.iceberg.mode=<mode>` automatically get Iceberg integration
- Redpanda creates Iceberg snapshots at intervals specified by `iceberg_target_lag_ms` (default 10s)
- No external services needed - Redpanda handles Parquet conversion and Iceberg table management internally

#### Iceberg Modes

Three modes available via `redpanda.iceberg.mode`:

1. **`key_value`** - Stores raw message bytes as BLOB columns (key + value)
2. **`value_schema_id_prefix`** - Avro-encoded messages with schema ID prefix
3. **`value_schema_latest`** - JSON messages using latest registered schema (**used in this demo**)

For `value_schema_latest`, Redpanda:
- Reads schema from Schema Registry
- Flattens nested JSON into columnar format
- Creates properly typed Iceberg columns
- Writes Parquet files with appropriate types

#### Apache Polaris REST Catalog
Polaris provides standard Iceberg REST API for metadata management:

```yaml
# Polaris configuration
POLARIS_PERSISTENCE_TYPE: relational-jdbc
POLARIS_JDBC_URL: jdbc:postgresql://postgres:5432/polaris
POLARIS_JDBC_USER: polaris
POLARIS_JDBC_PASSWORD: polaris123
POLARIS_BOOTSTRAP_CREDENTIALS: "POLARIS,root,pass"
```

**Bootstrap Process:**
1. PostgreSQL initialized with `polaris` database and user
2. Polaris starts and connects to PostgreSQL
3. `polaris-bootstrap` service creates `redpanda_catalog` via REST API
4. Catalog configured with S3 storage pointing to MinIO

**OAuth2 Authentication:**
- Polaris uses OAuth2 for authentication
- Client credentials: `client_id=root`, `client_secret=pass`
- Token endpoint: `http://polaris:8181/api/catalog/v1/oauth/tokens`
- Tokens have limited lifetime - refresh with `get_token.sh` if expired

#### DuckDB Integration (`duckdb/query_and_publish.py`)
DuckDB connects to Iceberg tables via Polaris REST catalog:

```python
# Get OAuth2 token from Polaris
token = get_polaris_token()

# Create secret with token
conn.execute(f"""
    CREATE OR REPLACE SECRET iceberg_secret (
        TYPE ICEBERG,
        TOKEN '{token}'
    )
""")

# Attach Polaris catalog
conn.execute("""
    ATTACH 'redpanda_catalog' AS iceberg_catalog (
        TYPE ICEBERG,
        SECRET iceberg_secret,
        ENDPOINT 'http://polaris:8181/api/catalog/'
    )
""")

# Query Iceberg table
result = conn.execute("""
    SELECT symbol, COUNT(*) as trades
    FROM iceberg_catalog.redpanda.trades
    GROUP BY symbol
""").fetchall()
```

**Important Notes:**
- Token must be refreshed periodically (run `get_token.sh`)
- S3 endpoint must NOT include `http://` prefix when configuring DuckDB
- Tables are namespaced as `iceberg_catalog.redpanda.<topic_name>`
- Redpanda automatically creates namespace `redpanda` for Iceberg tables

### Schema

```python
# Trade data schema (registered as JSON schema)
{
  "type": "object",
  "properties": {
    "trade_id": {"type": "string"},      # UUID v4
    "symbol": {"type": "string"},        # AAPL, GOOGL, MSFT, etc.
    "price": {"type": "number"},         # 50.00 - 499.95
    "qty": {"type": "integer"},          # 1 - 1000
    "side": {"type": "string"},          # BUY or SELL
    "ts_event": {"type": "string", "format": "date-time"}  # ISO 8601 timestamp
  },
  "required": ["trade_id", "symbol", "price", "qty", "side", "ts_event"]
}
```

**Iceberg Table Schema** (auto-created by Redpanda):
- All fields from JSON schema mapped to appropriate Iceberg types
- Timestamp stored as `timestamp` type (microsecond precision)
- Numbers stored as `double` or `integer` based on JSON schema

## Environment Configuration

All services configured via `docker-compose.yml` environment variables:

- **MinIO**: `http://minio:9000`, credentials: `minioadmin/minioadmin`, bucket: `redpanda`
- **PostgreSQL**: `postgres:5432`, database: `polaris`, user: `polaris/polaris123`
- **Polaris**: `http://polaris:8181`, OAuth2: `root/pass`, warehouse: `redpanda_catalog`
- **Redpanda**: Kafka API: `localhost:19092` (external), `redpanda:9092` (internal)
- **DuckDB**: Configured via init-env.sql with token

## Common Issues

### OAuth2 Token Expired
**Symptom**: DuckDB queries fail with authentication error

**Solution**:
```bash
docker compose exec duckdb-cli /workspace/duckdb/get_token.sh
```

### No Iceberg Table Created
**Symptom**: DuckDB cannot find `iceberg_catalog.redpanda.trades`

**Check**:
1. Topic created with Iceberg mode: `rpk topic describe trades`
2. Data produced to topic: `rpk topic consume trades --num 1`
3. Wait 10+ seconds for snapshot
4. Check Redpanda logs: `docker compose logs redpanda | grep iceberg`
5. Verify Polaris catalog: `curl http://localhost:8181/api/management/v1/catalogs`

### Polaris Not Starting
**Symptom**: `polaris` container repeatedly restarts

**Check**:
1. PostgreSQL is healthy: `docker compose ps postgres`
2. Database initialized: `docker compose exec postgres psql -U polaris -d polaris -c "\dt"`
3. Polaris logs: `docker compose logs polaris`

### Producer Fails
**Symptom**: Producer cannot write to Redpanda

**Check**:
1. Redpanda is healthy: `docker compose exec redpanda rpk status`
2. Topic exists: `docker compose exec redpanda rpk topic list`
3. Schema registered (for value_schema_latest mode): `docker compose exec redpanda rpk registry schema list`

## Testing Strategy

The E2E test (`validation/e2e.sh`) validates **bidirectional Iceberg flow**:
1. ✅ All services start and are healthy
2. ✅ TWO topics created with `value_schema_latest` mode (trades + trade_analytics)
3. ✅ JSON schemas registered for both topics in Schema Registry
4. ✅ 10,000 trades produced successfully
5. ✅ Iceberg snapshot 1 created for `trades` table (automatic after 10s)
6. ✅ DuckDB can query `trades` table via Polaris REST catalog
7. ✅ Analytics published to `trade_analytics` topic (with Iceberg mode)
8. ✅ Iceberg snapshot 2 created for `trade_analytics` table
9. ✅ DuckDB can query `trade_analytics` table (complete bidirectional cycle!)
10. ✅ All 8 symbols present in both Iceberg tables

Expected runtime: ~5-10 minutes

## File Organization

```
├── docker-compose.yml           # All services (MinIO, Postgres, Polaris, Redpanda, DuckDB)
├── resources/
│   └── create-polaris-db.sql   # PostgreSQL initialization
├── validation/
│   └── e2e.sh                  # End-to-end test
├── redpanda/
│   ├── producer.py             # Deterministic trade generator
│   ├── Dockerfile
│   └── requirements.txt
├── duckdb/
│   ├── init.sql                # DuckDB REST catalog template
│   ├── get_token.sh            # OAuth2 token helper
│   ├── verify_iceberg.sql      # Verification queries
│   └── query_and_publish.py    # Query + publish to Kafka
└── duckdb-ui/
    └── Dockerfile              # DuckDB CLI + Python + packages
```

## Development Notes

- **No committer/ or connect/ directories** - Removed in simplified architecture
- **Schema Registry Required** - For `value_schema_latest` mode, must register JSON schema
- **Automatic Namespace Creation** - Redpanda creates `redpanda` namespace in catalog automatically
- **Snapshot Frequency** - Configurable via `iceberg_target_lag_ms` (default 10000ms = 10s)
- **Token Lifetime** - Polaris OAuth2 tokens expire; refresh as needed
- **S3 Path Style** - MinIO requires `cloud_storage_url_style=path` and `s3_url_style=path`
- **DuckDB Extensions** - Must install `httpfs` and `iceberg` extensions before use
- **Redpanda Version** - Requires v25.2.2+ for native Iceberg Topics support
- **Polaris Image** - Uses `apache/polaris:latest` (ensure image is available)

## Key Differences from Previous Version

| Aspect | Previous (Custom Committer) | Current (Native Iceberg) |
|--------|----------------------------|-------------------------|
| **Iceberg Integration** | Custom Python FastAPI service | Native Redpanda feature |
| **Data Flow** | Redpanda Connect → S3 → Committer → Iceberg | Redpanda → Iceberg (direct) |
| **Catalog** | Tabular (proprietary) | Apache Polaris (open-source) |
| **Snapshot Creation** | Manual polling + conversion | Automatic every 10s |
| **Services** | 7 (including committer, connect) | 5 (removed 2 services) |
| **Complexity** | High (multiple moving parts) | Low (native integration) |
| **Topic Configuration** | Normal Kafka topic | Topic with `redpanda.iceberg.mode` |
