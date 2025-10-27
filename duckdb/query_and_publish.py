#!/usr/bin/env python3
"""
Query Iceberg table using DuckDB REST catalog and publish results to Redpanda.
This demonstrates the complete round trip: Redpanda Iceberg Topics → DuckDB → Redpanda.
"""

import json
import os
import sys
import subprocess
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


def get_polaris_token() -> str:
    """Get OAuth2 token from Polaris."""
    polaris_endpoint = get_env_or_exit("POLARIS_ENDPOINT", "http://polaris:8181")
    client_id = get_env_or_exit("POLARIS_CLIENT_ID", "root")
    client_secret = get_env_or_exit("POLARIS_CLIENT_SECRET", "pass")

    print("Getting OAuth2 token from Polaris...")

    try:
        result = subprocess.run([
            "curl", "-s", "-X", "POST",
            f"{polaris_endpoint}/api/catalog/v1/oauth/tokens",
            "-H", "Content-Type: application/x-www-form-urlencoded",
            "-d", f"grant_type=client_credentials&client_id={client_id}&client_secret={client_secret}&scope=PRINCIPAL_ROLE:ALL"
        ], capture_output=True, text=True, check=True)

        token_response = json.loads(result.stdout)
        token = token_response.get("access_token")

        if not token:
            print("ERROR: No access token in response", file=sys.stderr)
            sys.exit(1)

        print("✓ Token obtained successfully")
        return token

    except Exception as e:
        print(f"ERROR: Failed to get token: {e}", file=sys.stderr)
        sys.exit(1)


def delivery_report(err, msg):
    """Kafka delivery callback."""
    if err is not None:
        print(f"ERROR: Message delivery failed: {err}", file=sys.stderr)
    else:
        print(f"✓ Published to {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")


def query_iceberg_with_duckdb(token: str) -> List[Dict]:
    """Query Iceberg table using DuckDB REST catalog and return aggregated results."""

    print("\n=== Querying Iceberg Table via REST Catalog ===")

    # Create DuckDB connection
    conn = duckdb.connect(":memory:")

    # Install and load required extensions
    conn.execute("INSTALL httpfs")
    conn.execute("INSTALL iceberg")
    conn.execute("LOAD httpfs")
    conn.execute("LOAD iceberg")

    # Configure S3 access (MinIO)
    conn.execute("SET s3_endpoint='minio:9000'")
    conn.execute("SET s3_url_style='path'")
    conn.execute("SET s3_use_ssl=false")
    conn.execute("SET s3_access_key_id='minioadmin'")
    conn.execute("SET s3_secret_access_key='minioadmin'")
    conn.execute("SET s3_region='us-east-1'")

    # Create secret for Iceberg REST catalog
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

    print("✓ Connected to Polaris REST catalog")

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
    FROM iceberg_catalog.redpanda.trades
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
    print("DuckDB Iceberg REST Catalog Query → Redpanda Publisher")
    print("=" * 100)

    # Step 1: Get Polaris OAuth2 token
    token = get_polaris_token()

    # Step 2: Query Iceberg table using DuckDB REST catalog
    records = query_iceberg_with_duckdb(token)

    if not records:
        print("WARNING: No data found in Iceberg table", file=sys.stderr)
        sys.exit(1)

    # Step 3: Publish results to Redpanda
    publish_to_redpanda(records, broker, topic)

    print("\n" + "=" * 100)
    print("✓ END-TO-END VERIFICATION COMPLETE")
    print("✓ Data successfully flowed: Redpanda Iceberg Topics → DuckDB Query → Redpanda")
    print("=" * 100)


if __name__ == "__main__":
    main()
