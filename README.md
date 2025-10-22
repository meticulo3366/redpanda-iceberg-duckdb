# Redpanda → Iceberg → DuckDB → Redpanda: Complete Lakehouse Pipeline

> **A fully Dockerized, Spark-free streaming data pipeline** demonstrating the complete round-trip from Kafka to Iceberg lakehouse and back to Kafka for real-time analytics.

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Tested](https://img.shields.io/badge/e2e%20test-passing-brightgreen)](./validation/e2e.sh)
[![Docker](https://img.shields.io/badge/docker-required-blue)](https://www.docker.com/)

---

## 📊 Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │         COMPLETE ROUND TRIP FLOW            │
                        └─────────────────────────────────────────────┘

 ┌─────────────┐         ┌──────────────┐         ┌────────────┐
 │  Producer   │────────>│   Redpanda   │────────>│  Redpanda  │
 │  (Python)   │  50k    │    Kafka     │ batch   │  Connect   │
 │   Trades    │ trades  │    Topic     │ 10k/30s │ (Benthos)  │
 └─────────────┘         │   "trades"   │         └──────┬─────┘
                         └──────────────┘                │
                                                          │ NDJSON
                         ┌──────────────┐                │
                         │    MinIO     │<───────────────┘
                         │ S3 Storage   │
                         │  (staging/)  │
                         └──────┬───────┘
                                │
                                │ Polls every 10s
                                │
                         ┌──────▼───────┐
                         │  Committer   │
                         │   Service    │
                         │ NDJSON→Parquet
                         │  →Iceberg    │
                         └──────┬───────┘
                                │
                                │ Writes
                                ▼
                    ┌────────────────────────┐
                    │    Apache Iceberg      │
                    │  ACID Lakehouse Table  │
                    │   (Parquet + Metadata) │
                    └───────────┬────────────┘
                                │
                                │ Queries
                                ▼
                         ┌──────────────┐
                         │    DuckDB    │
                         │ Analytical   │
                         │    Engine    │
                         │              │
                         │ • Query      │
                         │ • Aggregate  │
                         │ • Transform  │
                         └──────┬───────┘
                                │
                                │ Publishes
                                │ analytics
                                ▼
                         ┌──────────────┐
                         │   Redpanda   │
                         │    Kafka     │
                         │    Topic     │
                         │  "analytics" │
                         └──────────────┘
                                │
                                │ Consumes
                                ▼
                         ┌──────────────┐
                         │ Downstream   │
                         │ Applications │
                         │ Dashboards   │
                         │   Alerts     │
                         └──────────────┘
```

### Data Flow Summary

1. **Ingest** → Producer generates 50,000 trade records to Redpanda (`trades` topic)
2. **Stage** → Redpanda Connect batches and writes NDJSON files to MinIO S3
3. **Transform** → Committer service converts NDJSON to Parquet format
4. **Store** → Parquet files committed to Apache Iceberg table with ACID guarantees
5. **Analyze** → DuckDB queries Iceberg Parquet files and computes aggregations
6. **Publish** → DuckDB publishes analytics back to Redpanda (`trade_analytics` topic)
7. **Consume** → Downstream applications consume real-time insights

---

## 🎯 What This Demo Shows

This project demonstrates a **production-ready lakehouse architecture** solving real-world data challenges:

### Real-World Use Case
Ingest raw financial trade data → Store in cost-efficient lakehouse → Run analytical queries → Publish insights for real-time monitoring dashboards, alerting systems, and downstream microservices.

### Key Technologies
- **Redpanda** (Kafka-compatible) - High-performance streaming platform
- **Apache Iceberg** - ACID-compliant table format for data lakes
- **DuckDB** - Fast in-process analytical database (Parquet-native)
- **PyIceberg** - Python client for Iceberg table operations
- **Redpanda Connect** - Stream processing framework (formerly Benthos)
- **MinIO** - S3-compatible object storage
- **No Spark Required** - Lightweight Python services

### Validation Results

✅ **Successfully tested end-to-end** (2025-10-22)
✅ **100,000+ records** processed through complete pipeline
✅ **8 stock symbols** aggregated (AAPL, GOOGL, MSFT, AMZN, TSLA, META, BRK.B, NVDA)
✅ **Analytics published** back to Kafka topic in JSON format

**Sample Analytics Output:**
```json
{
  "symbol": "META",
  "trade_count": 12702,
  "avg_price": 273.58,
  "min_price": 50.13,
  "max_price": 499.89,
  "total_volume": 6375486,
  "buy_count": 6260,
  "sell_count": 6442,
  "first_trade_time": "2025-01-15T10:00:02",
  "last_trade_time": "2025-01-15T23:53:14"
}
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose installed
- 8GB RAM minimum
- ~10 minutes for full end-to-end test

### Option 1: Automated End-to-End Test (Recommended)

Run the complete pipeline with one command:

```bash
cd rp-e2e-nospark

# Build the duckdb-cli container (required for Python integration)
docker compose build duckdb-cli

# Run the end-to-end test
./validation/e2e.sh
```

**What the script does:**
1. ✅ Starts all services (Redpanda, MinIO, Iceberg catalog, committer, DuckDB)
2. ✅ Creates required Kafka topics (`trades` and `trade_analytics`)
3. ✅ Produces 50,000 deterministic trade records
4. ✅ Streams data from Kafka → S3 → Iceberg via Redpanda Connect
5. ✅ Verifies Iceberg table with DuckDB
6. ✅ Queries Iceberg and publishes aggregated results back to Kafka
7. ✅ Verifies analytics were published to `trade_analytics` topic

**Expected Output:**
```
=== End-to-End Test PASSED ===
✓ Data successfully flowed through complete pipeline:
  1. Producer → Redpanda (trades topic)
  2. Redpanda Connect → MinIO S3 (NDJSON staging)
  3. Committer → Iceberg table (Parquet files)
  4. DuckDB → Query Iceberg table
  5. DuckDB → Redpanda (trade_analytics topic)

Services are still running. To clean up, run: docker compose down -v
```

### Option 2: Manual Step-by-Step

<details>
<summary>Click to expand manual steps</summary>

#### 1. Build and Start Services
```bash
cd rp-e2e-nospark

# Build the duckdb-cli container
docker compose build duckdb-cli

# Start all services
docker compose up -d redpanda minio catalog committer console duckdb-cli

# Wait ~15 seconds for services to be healthy
docker compose ps
```

#### 2. Create Kafka Topics
```bash
# Create trades topic (for raw data)
docker compose exec redpanda rpk topic create trades --partitions 3 --replicas 1

# Create analytics topic (for DuckDB results)
docker compose exec redpanda rpk topic create trade_analytics --partitions 1 --replicas 1
```

#### 3. Produce Data and Start Streaming
```bash
# Generate 50,000 trade records
docker compose run --rm producer \
    --brokers redpanda:9092 \
    --topic trades \
    --count 50000 \
    --seed 42

# Start Redpanda Connect to stream Kafka → S3
docker compose run --rm connect
# Wait for "Appended ... to Iceberg table" in committer logs, then Ctrl+C
```

#### 4. Query Iceberg with DuckDB and Publish to Kafka
```bash
# Verify Iceberg table
docker compose exec -T duckdb-cli duckdb -c ".read duckdb/common.sql" -c ".read duckdb/verify_iceberg.sql"

# Query and publish analytics
docker compose exec \
    -e RP_BROKERS=redpanda:9092 \
    -e RP_TOPIC_RESULTS=trade_analytics \
    duckdb-cli python3 /workspace/duckdb/query_and_publish.py
```

#### 5. Verify Analytics in Kafka
```bash
# Consume from analytics topic
docker compose exec redpanda rpk topic consume trade_analytics --num 8 --format json
```

</details>

---

## 📁 Project Structure

```
rp-e2e-nospark/
├── docker-compose.yml              # Services orchestration
├── README.md                       # This file
├── validation/
│   └── e2e.sh                      # Automated end-to-end test
│
├── redpanda/
│   ├── Dockerfile
│   ├── producer.py                 # Deterministic trade data generator
│   └── requirements.txt
│
├── connect/
│   └── s3_stage_and_commit.yaml    # Redpanda Connect pipeline config
│
├── committer/
│   ├── Dockerfile
│   ├── app.py                      # FastAPI service (NDJSON→Parquet→Iceberg)
│   └── requirements.txt
│
├── duckdb/
│   ├── common.sql                  # DuckDB S3 configuration
│   ├── verify_iceberg.sql          # Table verification queries
│   └── query_and_publish.py        # Query Iceberg + publish to Kafka
│
└── duckdb-ui/
    ├── Dockerfile                  # DuckDB CLI with Python integration
    └── (runtime container)
```

---

## 🔧 Configuration

### Key Settings in `docker-compose.yml`

**Redpanda Connect (Batching):**
```yaml
count: 10000      # Records per batch
period: 30s       # Max time before flushing batch
```

**Committer Service:**
```yaml
POLL_INTERVAL: 10              # S3 polling frequency (seconds)
PARQUET_ROW_GROUP: 50000       # Parquet row group size
ICEBERG_TABLE: analytics.trades_iceberg
```

**Producer:**
- Generates 50,000 records with fixed seed (deterministic)
- 8 stock symbols: AAPL, GOOGL, MSFT, AMZN, TSLA, META, BRK.B, NVDA
- Price range: $50-500
- Quantity range: 1-1000 shares

---

## 📊 Data Schema

```sql
trade_id    STRING      -- UUID v4 unique identifier
symbol      STRING      -- Stock ticker (8 symbols)
price       DOUBLE      -- Trade price ($50.00 - $499.95)
qty         INTEGER     -- Quantity (1 - 1000 shares)
side        STRING      -- BUY or SELL
ts_event    TIMESTAMP   -- Event timestamp (microsecond precision)
```

**Note:** Table is **unpartitioned** due to PyIceberg 0.6.1 limitation with `table.append()` on partitioned tables.

---

## 🔍 Monitoring & Debugging

### Watch Committer Logs
```bash
docker logs -f rp-e2e-nospark-committer-1

# Look for:
# ✓ "Found X new files to process"
# ✓ "Converted s3://lake/staging/... -> s3://lake/warehouse/..."
# ✓ "Appended ... to Iceberg table"
```

### Check Service Status
```bash
docker compose ps

# All services should show "healthy" or "running"
```

### Access Web UIs
- **Redpanda Console:** http://localhost:8080 (view topics, messages)
- **MinIO Console:** http://localhost:9001 (view S3 buckets, login: `minioadmin` / `minioadmin`)
- **Committer Health:** http://localhost:8088/health

### Query Iceberg Table Directly
```bash
# Execute DuckDB queries in the container
docker compose exec duckdb-cli duckdb -c "
LOAD httpfs;
LOAD iceberg;
SET s3_endpoint='minio:9000';
SET s3_url_style='path';
SET s3_use_ssl=false;
SET s3_access_key_id='minioadmin';
SET s3_secret_access_key='minioadmin';
SELECT symbol, COUNT(*) as trades, AVG(price) as avg_price
FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet')
GROUP BY symbol;
"
```

---

## 🐛 Troubleshooting

<details>
<summary><b>Python Not Found in duckdb-cli Container</b></summary>

**Error:** `exec: "python3": executable file not found in $PATH`

**Solution:**
```bash
docker compose build duckdb-cli
```

The container needs Python 3, DuckDB library, and Kafka client packages.
</details>

<details>
<summary><b>Docker Networking Issues</b></summary>

**Error:** `failed to set up container networking: network <ID> not found`

**Solution:**
```bash
docker compose down -v
docker network prune -f
./validation/e2e.sh
```

This is a known macOS Docker Desktop issue with stale network references.
</details>

<details>
<summary><b>No Data in Iceberg Table</b></summary>

**Check S3 staging files:**
```bash
docker exec rp-e2e-nospark-committer-1 python3 -c "
import boto3
s3 = boto3.client('s3',
    endpoint_url='http://minio:9000',
    aws_access_key_id='minioadmin',
    aws_secret_access_key='minioadmin')
resp = s3.list_objects_v2(Bucket='lake', Prefix='staging/trades/')
print(f'Found {len(resp.get(\"Contents\", []))} NDJSON files')
"
```

**Check Parquet files:**
```bash
docker exec rp-e2e-nospark-committer-1 python3 -c "
import s3fs
fs = s3fs.S3FileSystem(key='minioadmin', secret='minioadmin',
    client_kwargs={'endpoint_url': 'http://minio:9000'})
files = fs.glob('lake/warehouse/analytics/trades_iceberg/data/**/*.parquet')
print(f'Found {len(files)} Parquet files')
"
```
</details>

<details>
<summary><b>Connect Service Not Starting</b></summary>

The connect service uses a `manual` profile. Use:
```bash
docker compose run --rm connect
```

Or with profile flag:
```bash
docker compose --profile manual up -d connect
```
</details>

---

## 🧹 Clean Up

```bash
# Stop all services
docker compose down

# Remove all data (WARNING: deletes everything)
docker compose down -v

# Prune unused networks (optional)
docker network prune -f
```

---

## ✨ Key Features

- ✅ **Fully Dockerized** - No local dependencies required
- ✅ **Complete Round Trip** - Kafka → Iceberg → DuckDB → Kafka
- ✅ **ACID Transactions** - Iceberg snapshots ensure data consistency
- ✅ **Automatic Polling** - Committer service polls S3 every 10 seconds
- ✅ **Idempotent Processing** - Tracks committed files, no duplicates
- ✅ **Production Format** - Parquet with zstd compression
- ✅ **Analytical Queries** - DuckDB queries Parquet files directly
- ✅ **Deterministic Testing** - Fixed seed produces same data every run
- ✅ **Automated E2E Test** - Single script validates entire pipeline
- ✅ **No Spark Required** - Lightweight Python services

---

## 🎓 Learn More

### Documentation
- **[Claude.md](./Claude.md)** - Detailed technical documentation and troubleshooting
- **[Redpanda Docs](https://docs.redpanda.com/)** - Kafka-compatible streaming platform
- **[Apache Iceberg](https://iceberg.apache.org/)** - Table format for huge analytic datasets
- **[DuckDB](https://duckdb.org/)** - Fast in-process analytical database
- **[PyIceberg](https://py.iceberg.apache.org/)** - Python client for Apache Iceberg

### Related Resources
- [Redpanda Connect Documentation](https://docs.redpanda.com/redpanda-connect/)
- [Tabular](https://tabular.io/) - Iceberg REST catalog
- [MinIO](https://min.io/) - S3-compatible object storage

---

## 🤝 Contributing

This is a demo project for educational purposes. Feel free to:
- Open issues for bugs or questions
- Submit PRs for improvements
- Use as a template for your own projects

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

**Built with Claude Code** - Demonstrating modern lakehouse architecture without Spark.

Special thanks to the teams behind Redpanda, Apache Iceberg, DuckDB, and the open-source community.

---

<p align="center">
  <b>⭐ If you find this useful, please star the repository! ⭐</b>
</p>
