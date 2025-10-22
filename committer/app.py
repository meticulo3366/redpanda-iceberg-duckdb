#!/usr/bin/env python3
"""
Committer service: Convert staged NDJSON to Parquet and append to Iceberg table.

Receives POST /commit with {"staged_objects": ["s3://bucket/path/file.ndjson", ...]},
converts each NDJSON file to Parquet, and appends to Iceberg table via PyIceberg.
Maintains idempotency by tracking committed files.
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.schema import Schema
from pyiceberg.types import (
    NestedField,
    StringType,
    DoubleType,
    IntegerType,
    TimestampType,
)
from pyiceberg.partitioning import PartitionSpec, PartitionField
from pyiceberg.transforms import DayTransform, HourTransform
from pyiceberg.table import Table
import s3fs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "lake")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")

CATALOG_URI = os.getenv("CATALOG_URI", "http://catalog:8181")
ICEBERG_WAREHOUSE = os.getenv("ICEBERG_WAREHOUSE", "s3://lake/warehouse")
ICEBERG_TABLE = os.getenv("ICEBERG_TABLE", "analytics.trades_iceberg")

PARQUET_TARGET_PREFIX = os.getenv("PARQUET_TARGET_PREFIX", "warehouse/analytics/trades_iceberg/data")
PARQUET_ROW_GROUP = int(os.getenv("PARQUET_ROW_GROUP", "50000"))
COMMITTER_PORT = int(os.getenv("COMMITTER_PORT", "8088"))

# Committed files log (for idempotency)
COMMITTED_LOG_PATH = f"s3://{MINIO_BUCKET}/warehouse/_logs/committed_files.jsonl"

app = FastAPI(title="Iceberg Committer Service")

# Initialize S3 client
s3_client = boto3.client(
    's3',
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    region_name=MINIO_REGION
)

# Initialize S3FS
fs = s3fs.S3FileSystem(
    key=MINIO_ACCESS_KEY,
    secret=MINIO_SECRET_KEY,
    client_kwargs={
        'endpoint_url': MINIO_ENDPOINT,
        'region_name': MINIO_REGION
    }
)

# Iceberg schema matching producer output
ICEBERG_SCHEMA = Schema(
    NestedField(1, "trade_id", StringType(), required=True),
    NestedField(2, "symbol", StringType(), required=True),
    NestedField(3, "price", DoubleType(), required=True),
    NestedField(4, "qty", IntegerType(), required=True),
    NestedField(5, "side", StringType(), required=True),
    NestedField(6, "ts_event", TimestampType(), required=True),
)

# Partition spec: partition by day and hour from ts_event
# Note: PyIceberg 0.6.1 doesn't support table.append() on partitioned tables
# So we'll create unpartitioned table for now
# Use empty PartitionSpec for unpartitioned table (not None)
PARTITION_SPEC = PartitionSpec()


class CommitRequest(BaseModel):
    """Request model for /commit endpoint."""
    staged_objects: List[str]
    batch_size: Optional[int] = None


class CommitResponse(BaseModel):
    """Response model for /commit endpoint."""
    files_appended: int
    snapshot_id: str
    message: str


def get_catalog() -> RestCatalog:
    """Initialize PyIceberg REST catalog."""
    return RestCatalog(
        "default",
        **{
            "uri": CATALOG_URI,
            "warehouse": ICEBERG_WAREHOUSE,
            "s3.endpoint": MINIO_ENDPOINT,
            "s3.access-key-id": MINIO_ACCESS_KEY,
            "s3.secret-access-key": MINIO_SECRET_KEY,
            "s3.region": MINIO_REGION,
            "s3.path-style-access": "true",
        }
    )


def ensure_table_exists(catalog: RestCatalog) -> Table:
    """Ensure Iceberg table exists, create if not."""
    namespace, table_name = ICEBERG_TABLE.rsplit(".", 1)

    try:
        # Create namespace if it doesn't exist
        try:
            catalog.create_namespace(namespace)
            logger.info(f"Created namespace: {namespace}")
        except Exception as e:
            logger.info(f"Namespace {namespace} may already exist: {e}")

        # Try to load existing table
        try:
            table = catalog.load_table(ICEBERG_TABLE)
            logger.info(f"Loaded existing table: {ICEBERG_TABLE}")
            return table
        except Exception:
            # Create new table
            table = catalog.create_table(
                identifier=ICEBERG_TABLE,
                schema=ICEBERG_SCHEMA,
                partition_spec=PARTITION_SPEC,
            )
            logger.info(f"Created new table: {ICEBERG_TABLE}")
            return table

    except Exception as e:
        logger.error(f"Failed to ensure table exists: {e}")
        raise


def load_committed_files() -> set:
    """Load set of already-committed file URIs from log."""
    committed = set()
    try:
        if fs.exists(COMMITTED_LOG_PATH.replace("s3://", "")):
            with fs.open(COMMITTED_LOG_PATH.replace("s3://", ""), 'r') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        committed.add(entry.get("staged_uri"))
        logger.info(f"Loaded {len(committed)} committed files from log")
    except Exception as e:
        logger.warning(f"Could not load committed files log: {e}")
    return committed


def mark_file_committed(staged_uri: str, snapshot_id: str):
    """Append entry to committed files log."""
    try:
        entry = {
            "staged_uri": staged_uri,
            "snapshot_id": snapshot_id,
            "committed_at": datetime.utcnow().isoformat() + "Z"
        }
        with fs.open(COMMITTED_LOG_PATH.replace("s3://", ""), 'a') as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(f"Marked file as committed: {staged_uri}")
    except Exception as e:
        logger.error(f"Failed to mark file committed: {e}")


def convert_ndjson_to_parquet(ndjson_uri: str) -> str:
    """
    Read NDJSON from S3, convert to Parquet, write back to S3.
    Returns S3 URI of the Parquet file.
    """
    # Parse S3 URI
    parsed = urlparse(ndjson_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')

    logger.info(f"Converting {ndjson_uri} to Parquet")

    # Read NDJSON from S3
    records = []
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        body_bytes = obj['Body'].read()

        # Decompress if zstd compressed
        if key.endswith('.zst') or key.endswith('.zstd'):
            logger.info(f"Decompressing zstd file: {key}")
            # Use decompressobj with max_window_size to avoid content size check
            dctx = zstd.ZstdDecompressor()
            decompressor = dctx.decompressobj()
            # Provide max_output_size to avoid frame header content size requirement
            body_bytes = decompressor.decompress(body_bytes, max_output_size=100 * 1024 * 1024)  # 100MB max

        # Decode to UTF-8
        body = body_bytes.decode('utf-8')

        # Parse NDJSON
        for line in body.splitlines():
            if line.strip():
                records.append(json.loads(line))
    except Exception as e:
        logger.error(f"Failed to read NDJSON from S3: {e}")
        raise

    if not records:
        logger.warning(f"No records found in {ndjson_uri}")
        return None

    logger.info(f"Read {len(records)} records from NDJSON")

    # Convert to PyArrow Table
    # Parse ISO8601 timestamps
    for record in records:
        if 'ts_event' in record:
            # Remove 'Z' suffix if present and parse
            ts_str = record['ts_event'].rstrip('Z')
            record['ts_event'] = datetime.fromisoformat(ts_str)

    schema = pa.schema([
        pa.field('trade_id', pa.string(), nullable=False),
        pa.field('symbol', pa.string(), nullable=False),
        pa.field('price', pa.float64(), nullable=False),
        pa.field('qty', pa.int32(), nullable=False),
        pa.field('side', pa.string(), nullable=False),
        pa.field('ts_event', pa.timestamp('us'), nullable=False),
    ])

    pa_table = pa.Table.from_pylist(records, schema=schema)

    # Generate Parquet filename with partition info
    # Extract partition values from first record
    first_record = records[0]
    dt = first_record['ts_event'].strftime('%Y-%m-%d')
    hour = first_record['ts_event'].strftime('%H')
    part_uuid = str(uuid.uuid4())

    parquet_key = f"{PARQUET_TARGET_PREFIX}/dt={dt}/hour={hour}/part-{part_uuid}.parquet"
    parquet_uri = f"s3://{MINIO_BUCKET}/{parquet_key}"
    parquet_s3fs_path = f"{MINIO_BUCKET}/{parquet_key}"

    # Write Parquet to S3
    try:
        with fs.open(parquet_s3fs_path, 'wb') as f:
            pq.write_table(
                pa_table,
                f,
                row_group_size=PARQUET_ROW_GROUP,
                compression='zstd',
                use_dictionary=True,
            )
        logger.info(f"Wrote Parquet file: {parquet_uri}")
    except Exception as e:
        logger.error(f"Failed to write Parquet to S3: {e}")
        raise

    return parquet_uri


def append_to_iceberg(table: Table, parquet_files: List[str]) -> str:
    """
    Append Parquet files to Iceberg table.
    Returns snapshot ID.
    """
    try:
        # Append each parquet file individually
        for parquet_uri in parquet_files:
            # Read Parquet file as PyArrow table
            table_data = pq.read_table(parquet_uri, filesystem=fs)
            # Append to table
            table.append(table_data)
            logger.info(f"Appended {parquet_uri} to Iceberg table")

        # Get latest snapshot ID
        snapshot = table.current_snapshot()
        snapshot_id = str(snapshot.snapshot_id) if snapshot else "unknown"

        logger.info(f"Completed appending {len(parquet_files)} files to table, snapshot: {snapshot_id}")
        return snapshot_id

    except Exception as e:
        logger.error(f"Failed to append to Iceberg table: {e}")
        raise


@app.post("/commit", response_model=CommitResponse)
async def commit_staged_files(request: CommitRequest):
    """
    Convert staged NDJSON files to Parquet and append to Iceberg table.
    Idempotent: skips already-committed files.
    """
    logger.info(f"Received commit request for {len(request.staged_objects)} staged objects")

    # Load committed files for idempotency check
    committed_files = load_committed_files()

    # Filter out already-committed files
    files_to_commit = [
        uri for uri in request.staged_objects
        if uri not in committed_files
    ]

    if not files_to_commit:
        logger.info("All files already committed, skipping")
        return CommitResponse(
            files_appended=0,
            snapshot_id="",
            message="All files already committed"
        )

    logger.info(f"Committing {len(files_to_commit)} new files")

    # Convert NDJSON to Parquet
    parquet_files = []
    for ndjson_uri in files_to_commit:
        try:
            parquet_uri = convert_ndjson_to_parquet(ndjson_uri)
            if parquet_uri:
                parquet_files.append(parquet_uri)
        except Exception as e:
            logger.error(f"Failed to convert {ndjson_uri}: {e}")
            raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")

    if not parquet_files:
        raise HTTPException(status_code=400, detail="No valid files to commit")

    # Append to Iceberg table
    try:
        catalog = get_catalog()
        table = ensure_table_exists(catalog)
        snapshot_id = append_to_iceberg(table, parquet_files)

        # Mark files as committed
        for uri in files_to_commit:
            mark_file_committed(uri, snapshot_id)

        return CommitResponse(
            files_appended=len(parquet_files),
            snapshot_id=snapshot_id,
            message=f"Successfully committed {len(parquet_files)} files"
        )

    except Exception as e:
        logger.error(f"Failed to commit to Iceberg: {e}")
        raise HTTPException(status_code=500, detail=f"Commit failed: {e}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "iceberg-committer"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "iceberg-committer",
        "version": "1.0.0",
        "endpoints": ["/commit", "/health"]
    }


def poll_s3_for_new_files():
    """Background task to poll S3 for new NDJSON files and process them."""
    import asyncio
    import time

    STAGING_PREFIX = f"{MINIO_BUCKET}/staging/trades/"
    POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))  # seconds

    logger.info(f"Starting S3 poller: s3://{STAGING_PREFIX}")
    logger.info(f"Poll interval: {POLL_INTERVAL} seconds")

    while True:
        try:
            # List files in staging directory
            objects = s3_client.list_objects_v2(
                Bucket=MINIO_BUCKET,
                Prefix="staging/trades/"
            )

            if 'Contents' in objects:
                # Load committed files
                committed_files = load_committed_files()

                # Filter to only .ndjson or .ndjson.zst files that haven't been committed
                new_files = []
                for obj in objects['Contents']:
                    s3_uri = f"s3://{MINIO_BUCKET}/{obj['Key']}"
                    if (obj['Key'].endswith('.ndjson') or obj['Key'].endswith('.ndjson.zst')) and s3_uri not in committed_files:
                        new_files.append(s3_uri)

                if new_files:
                    logger.info(f"Found {len(new_files)} new files to process")

                    # Get catalog and ensure table exists
                    catalog = get_catalog()
                    table = ensure_table_exists(catalog)

                    # Convert NDJSON to Parquet
                    parquet_files = []
                    for staged_uri in new_files:
                        try:
                            parquet_uri = convert_ndjson_to_parquet(staged_uri)
                            if parquet_uri:
                                parquet_files.append(parquet_uri)
                                logger.info(f"Converted {staged_uri} -> {parquet_uri}")
                        except Exception as e:
                            logger.error(f"Failed to convert {staged_uri}: {e}")
                            continue

                    if parquet_files:
                        # Append to Iceberg table
                        snapshot_id = append_to_iceberg(table, parquet_files)
                        logger.info(f"Appended {len(parquet_files)} files to Iceberg, snapshot: {snapshot_id}")

                        # Mark files as committed
                        for staged_uri in new_files:
                            mark_file_committed(staged_uri, snapshot_id)
                else:
                    logger.debug("No new files to process")

        except Exception as e:
            logger.error(f"Error in S3 poller: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import uvicorn
    import threading

    logger.info(f"Starting committer service on port {COMMITTER_PORT}")
    logger.info(f"Catalog URI: {CATALOG_URI}")
    logger.info(f"Iceberg warehouse: {ICEBERG_WAREHOUSE}")
    logger.info(f"Iceberg table: {ICEBERG_TABLE}")
    logger.info(f"Using Tabular REST catalog")

    # Start S3 poller in background thread
    poller_thread = threading.Thread(target=poll_s3_for_new_files, daemon=True)
    poller_thread.start()
    logger.info("S3 poller started in background")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=COMMITTER_PORT,
        log_level="info"
    )
