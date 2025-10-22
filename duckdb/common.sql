-- DuckDB common setup: install extensions and configure S3/Iceberg access
-- This file should be loaded before any verification queries

-- Install required extensions
INSTALL httpfs;
INSTALL iceberg;

-- Load extensions
LOAD httpfs;
LOAD iceberg;

-- Configure S3 access for MinIO
SET s3_endpoint='minio:9000';
SET s3_url_style='path';
SET s3_use_ssl=false;
SET s3_access_key_id='minioadmin';
SET s3_secret_access_key='minioadmin';
SET s3_region='us-east-1';

-- Configure Iceberg catalog (Nessie REST)
-- Note: DuckDB Iceberg extension may have limited REST catalog support
-- For now, we'll read Iceberg metadata directly from S3
