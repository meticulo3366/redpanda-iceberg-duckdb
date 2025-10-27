#!/usr/bin/env python3
"""
Deterministic trade data producer for Redpanda.
Emits exactly BATCH_COUNT rows with fixed SEED for reproducibility.
"""

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta
from typing import Dict

from confluent_kafka import Producer


SYMBOLS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "BRK.B"]
SIDES = ["BUY", "SELL"]


def generate_trade(trade_index: int, base_time: datetime) -> Dict:
    """Generate a single deterministic trade record."""
    # Deterministic UUID based on index
    trade_id = str(uuid.UUID(int=trade_index, version=4))

    symbol = random.choice(SYMBOLS)
    price = round(random.uniform(50.0, 500.0), 2)
    qty = random.randint(1, 1000)
    side = random.choice(SIDES)

    # Spread trades over time
    ts_event = base_time + timedelta(seconds=trade_index)
    ts_event_str = ts_event.isoformat() + "Z"

    # Add padding to defeat Parquet compression (for demo purposes)
    # Generate 100 bytes of random data per record to ensure >1MB Parquet files
    padding = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=100))

    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "price": price,
        "qty": qty,
        "side": side,
        "ts_event": ts_event_str,
        "notes": padding  # Padding field for testing
    }


def delivery_report(err, msg):
    """Kafka delivery callback."""
    if err is not None:
        print(f"ERROR: Message delivery failed: {err}", file=sys.stderr)
        sys.exit(1)
    else:
        # Print progress every 5000 messages
        if msg.offset() % 5000 == 0:
            print(f"Progress: delivered message to {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")


def main():
    # Check for environment variables first
    default_broker = os.getenv("BROKER", "localhost:19092")

    parser = argparse.ArgumentParser(description="Produce deterministic trade data")
    parser.add_argument("--brokers", default=default_broker, help="Kafka brokers")
    parser.add_argument("--topic", default="trades", help="Topic name")
    parser.add_argument("--count", type=int, default=50000, help="Number of trades to produce")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    # Set seed for deterministic output
    random.seed(args.seed)

    # Base timestamp for all trades
    base_time = datetime(2025, 1, 15, 10, 0, 0)

    # Configure producer
    conf = {
        'bootstrap.servers': args.brokers,
        'client.id': 'trade-producer',
        'acks': 'all',
        'compression.type': 'snappy',
        'linger.ms': 10,
        'batch.size': 16384,
    }

    producer = Producer(conf)

    print(f"Producing {args.count} trades to {args.topic} (seed={args.seed})")

    try:
        for i in range(args.count):
            trade = generate_trade(i, base_time)

            # Use trade_id as key for consistent partitioning
            key = trade["trade_id"].encode('utf-8')
            value = json.dumps(trade).encode('utf-8')

            producer.produce(
                topic=args.topic,
                key=key,
                value=value,
                callback=delivery_report
            )

            # Poll periodically to trigger callbacks
            if i % 100 == 0:
                producer.poll(0)

        # Wait for all messages to be delivered
        print("Flushing remaining messages...")
        producer.flush(timeout=30)

        print(f"SUCCESS: Produced {args.count} trades to {args.topic}")

    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        producer.flush()
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
