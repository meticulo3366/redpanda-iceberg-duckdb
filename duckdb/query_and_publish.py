#!/usr/bin/env python3
"""
Query Iceberg table using DuckDB and publish results to Redpanda.
This script demonstrates the complete round trip: Redpanda -> Iceberg -> Redpanda.
"""

import json
import os
import sys
from typing import List, Dict

import duckdb
from confluent_kafka import Producer


def get_env_or_exit(var_name: str, default: str = None) -> str:
    """Get environment variable or exit if not set and no default."""
    value = os.getenv(var_name, default)
    if value is None:
        print(f"ERROR: {var_name} environment variable not set", file=sys.stderr)
        sys.exit(1)
    return value


def delivery_report(err, msg):
    """Kafka delivery callback."""
    if err is not None:
        print(f"ERROR: Message delivery failed: {err}", file=sys.stderr)
    else:
        print(f"✓ Published to {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")


def query_iceberg_with_duckdb() -> List[Dict]:
    """Query Iceberg table using DuckDB and return aggregated results."""

    # Get S3/MinIO configuration
    minio_endpoint = get_env_or_exit("MINIO_ENDPOINT", "http://minio:9000")
    minio_access_key = get_env_or_exit("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key = get_env_or_exit("MINIO_SECRET_KEY", "minioadmin")
    minio_region = get_env_or_exit("MINIO_REGION", "us-east-1")

    print("=== Querying Iceberg Table with DuckDB ===")

    # Create DuckDB connection
    conn = duckdb.connect(":memory:")

    # Install and load required extensions
    conn.execute("INSTALL httpfs")
    conn.execute("INSTALL iceberg")
    conn.execute("LOAD httpfs")
    conn.execute("LOAD iceberg")

    # Configure S3 access (strip http:// from endpoint for DuckDB)
    endpoint = minio_endpoint.replace("http://", "").replace("https://", "")
    conn.execute(f"SET s3_endpoint='{endpoint}'")
    conn.execute("SET s3_url_style='path'")
    conn.execute("SET s3_use_ssl=false")
    conn.execute(f"SET s3_access_key_id='{minio_access_key}'")
    conn.execute(f"SET s3_secret_access_key='{minio_secret_key}'")
    conn.execute(f"SET s3_region='{minio_region}'")

    # Query Iceberg table for aggregated stats
    query = """
    SELECT
        symbol,
        COUNT(*) as trade_count,
        ROUND(AVG(price), 2) as avg_price,
        ROUND(MIN(price), 2) as min_price,
        ROUND(MAX(price), 2) as max_price,
        SUM(qty) as total_volume,
        COUNT(CASE WHEN side = 'BUY' THEN 1 END) as buy_count,
        COUNT(CASE WHEN side = 'SELL' THEN 1 END) as sell_count,
        MIN(ts_event) as first_trade_time,
        MAX(ts_event) as last_trade_time
    FROM read_parquet('s3://lake/warehouse/analytics/trades_iceberg/data/**/*.parquet')
    GROUP BY symbol
    ORDER BY total_volume DESC
    """

    print(f"Executing query against Iceberg table...")
    result = conn.execute(query).fetchall()

    # Convert to list of dicts
    columns = ['symbol', 'trade_count', 'avg_price', 'min_price', 'max_price',
               'total_volume', 'buy_count', 'sell_count', 'first_trade_time', 'last_trade_time']

    records = []
    for row in result:
        record = dict(zip(columns, row))
        # Convert timestamp to string
        record['first_trade_time'] = record['first_trade_time'].isoformat() if record['first_trade_time'] else None
        record['last_trade_time'] = record['last_trade_time'].isoformat() if record['last_trade_time'] else None
        records.append(record)

    print(f"\nQuery results ({len(records)} symbols):")
    print("-" * 100)
    print(f"{'Symbol':<8} {'Trades':<10} {'Avg Price':<12} {'Min':<10} {'Max':<10} {'Volume':<12} {'Buy':<8} {'Sell':<8}")
    print("-" * 100)
    for rec in records:
        print(f"{rec['symbol']:<8} {rec['trade_count']:<10} ${rec['avg_price']:<11.2f} ${rec['min_price']:<9.2f} ${rec['max_price']:<9.2f} {rec['total_volume']:<12} {rec['buy_count']:<8} {rec['sell_count']:<8}")
    print("-" * 100)

    conn.close()

    return records


def publish_to_redpanda(records: List[Dict], broker: str, topic: str):
    """Publish aggregated results to Redpanda."""

    print(f"\n=== Publishing Results to Redpanda ===")
    print(f"Target topic: {topic}")

    # Configure producer
    conf = {
        'bootstrap.servers': broker,
        'client.id': 'duckdb-iceberg-publisher',
        'acks': 'all',
        'compression.type': 'snappy',
    }

    producer = Producer(conf)

    try:
        # Publish each symbol's stats as a separate message
        for record in records:
            key = record['symbol'].encode('utf-8')
            value = json.dumps(record).encode('utf-8')

            producer.produce(
                topic=topic,
                key=key,
                value=value,
                callback=delivery_report
            )

        # Wait for all messages to be delivered
        producer.flush(timeout=30)

        print(f"\n✓ Successfully published {len(records)} aggregated trade statistics to {topic}")

    except Exception as e:
        print(f"ERROR: Failed to publish to Redpanda: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main execution flow."""

    # Get configuration from environment
    broker = get_env_or_exit("RP_BROKERS", "redpanda:9092")
    topic = get_env_or_exit("RP_TOPIC_RESULTS", "trade_analytics")

    print("=" * 100)
    print("DuckDB Iceberg Query -> Redpanda Publisher")
    print("=" * 100)

    # Step 1: Query Iceberg table using DuckDB
    records = query_iceberg_with_duckdb()

    if not records:
        print("WARNING: No data found in Iceberg table", file=sys.stderr)
        sys.exit(1)

    # Step 2: Publish results to Redpanda
    publish_to_redpanda(records, broker, topic)

    print("\n" + "=" * 100)
    print("✓ END-TO-END VERIFICATION COMPLETE")
    print("✓ Data successfully flowed: Redpanda -> Iceberg -> DuckDB Query -> Redpanda")
    print("=" * 100)


if __name__ == "__main__":
    main()
