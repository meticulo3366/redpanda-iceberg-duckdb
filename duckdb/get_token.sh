#!/bin/bash
# Get OAuth2 token from Polaris and generate init-env.sql

set -e

POLARIS_ENDPOINT="${POLARIS_ENDPOINT:-http://polaris:8181}"
CLIENT_ID="${POLARIS_CLIENT_ID:-root}"
CLIENT_SECRET="${POLARIS_CLIENT_SECRET:-pass}"

# Extract base URL (remove /api/catalog/ suffix if present)
POLARIS_BASE_URL=$(echo "$POLARIS_ENDPOINT" | sed 's|/api/catalog/\?$||')

echo "Getting OAuth2 token from Polaris..."

# Get token and save to temporary file
TEMP_FILE=$(mktemp)
curl -s -X POST "${POLARIS_BASE_URL}/api/catalog/v1/oauth/tokens" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Polaris-Realm: POLARIS" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL" \
  > "$TEMP_FILE"

# Extract access token
TOKEN=$(python3 -c "import json; print(json.load(open('$TEMP_FILE'))['access_token'])" 2>&1)
rm -f "$TEMP_FILE"

if [ -z "$TOKEN" ] || [[ "$TOKEN" == *"KeyError"* ]] || [[ "$TOKEN" == *"Traceback"* ]]; then
    echo "ERROR: Failed to get token from Polaris"
    exit 1
fi

echo "Token obtained successfully"

# Create init-env.sql with actual token (write to writable location)
cat > /tmp/init-env.sql <<EOF
-- DuckDB initialization with Polaris REST catalog
-- Auto-generated with OAuth2 token

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

-- Create secret for Iceberg REST catalog
CREATE OR REPLACE SECRET iceberg_secret (
    TYPE ICEBERG,
    TOKEN '${TOKEN}'
);

-- Attach Polaris catalog
ATTACH 'redpanda_catalog' AS iceberg_catalog (
    TYPE ICEBERG,
    SECRET iceberg_secret,
    ENDPOINT 'http://polaris:8181/api/catalog/'
);

SELECT 'Iceberg catalog attached successfully!' as status;
EOF

echo "init-env.sql generated successfully"
