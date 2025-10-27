-- DuckDB initialization with Polaris REST catalog
-- This script connects DuckDB to the Polaris Iceberg catalog

-- Load required extensions
INSTALL httpfs;
INSTALL iceberg;
LOAD httpfs;
LOAD iceberg;

-- Configure S3 access for MinIO
SET s3_endpoint='minio:9000';
SET s3_url_style='path';
SET s3_use_ssl=false;
SET s3_access_key_id='minioadmin';
SET s3_secret_access_key='minioadmin';
SET s3_region='us-east-1';

-- Get OAuth2 token from Polaris (this will be replaced by script)
-- TOKEN placeholder will be replaced with actual token

-- Create secret for Iceberg REST catalog
CREATE OR REPLACE SECRET iceberg_secret (
    TYPE ICEBERG,
    TOKEN '${POLARIS_TOKEN}'
);

-- Attach Polaris catalog
ATTACH 'redpanda_catalog' AS iceberg_catalog (
    TYPE ICEBERG,
    SECRET iceberg_secret,
    ENDPOINT 'http://polaris:8181/api/catalog/'
);

-- Show available tables
SELECT 'Iceberg catalog attached successfully!' as status;
