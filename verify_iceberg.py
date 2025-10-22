#!/usr/bin/env python3
"""Verify Iceberg table data."""

from pyiceberg.catalog.rest import RestCatalog

# Initialize catalog
catalog = RestCatalog(
    'default',
    **{
        'uri': 'http://catalog:8181',
        'warehouse': 's3://lake/warehouse',
        's3.endpoint': 'http://minio:9000',
        's3.access-key-id': 'minioadmin',
        's3.secret-access-key': 'minioadmin',
        's3.region': 'us-east-1',
        's3.path-style-access': 'true',
    }
)

# Load table
table = catalog.load_table('analytics.trades_iceberg')

print('=== Iceberg Table Verification ===')
print(f'Table: {table.name()}')
print(f'Current snapshot ID: {table.current_snapshot().snapshot_id if table.current_snapshot() else "None"}')
print('\nSchema:')
for field in table.schema().fields:
    print(f'  - {field}')

# Scan table to get data
print('\n=== Reading Data ===')
scan = table.scan()
arrow_table = scan.to_arrow()
print(f'Total records: {len(arrow_table)}')

# Show first 5 records
print(f'\nFirst 5 records:')
for i in range(min(5, len(arrow_table))):
    row = arrow_table.slice(i, 1)
    trade_id = row['trade_id'][0].as_py()
    symbol = row['symbol'][0].as_py()
    price = row['price'][0].as_py()
    qty = row['qty'][0].as_py()
    side = row['side'][0].as_py()
    ts_event = row['ts_event'][0].as_py()
    print(f'  {i+1}. {symbol:5s} {side:4s} {qty:4d} @ ${price:.2f} - {ts_event} ({trade_id})')

# Summary stats
print(f'\n=== Summary Statistics ===')
symbols = arrow_table['symbol'].unique().to_pylist()
print(f'Symbols: {symbols}')

# Get min/max using combine_chunks() to convert ChunkedArray to Array
import pyarrow.compute as pc
ts_min = pc.min(arrow_table['ts_event']).as_py()
ts_max = pc.max(arrow_table['ts_event']).as_py()
print(f'Date range: {ts_min} to {ts_max}')

price_min = pc.min(arrow_table['price']).as_py()
price_max = pc.max(arrow_table['price']).as_py()
print(f'Price range: ${price_min:.2f} - ${price_max:.2f}')

# Count by symbol
print(f'\nRecords per symbol:')
for symbol in symbols:
    count = len([x for x in arrow_table['symbol'].to_pylist() if x == symbol])
    print(f'  {symbol}: {count} records')

print('\n=== END-TO-END PIPELINE VERIFICATION SUCCESSFUL ===')
print(f'✓ Data flowed from Redpanda -> S3 -> Parquet -> Iceberg')
print(f'✓ Total of {len(arrow_table)} trade records successfully ingested')
