#!/bin/bash
# Set up Polaris catalog after bootstrap
set -euo pipefail

POLARIS_HOST="${POLARIS_HOST:-polaris}"
POLARIS_PORT="${POLARIS_PORT:-8181}"
CLIENT_ID="${CLIENT_ID:-root}"
CLIENT_SECRET="${CLIENT_SECRET:-pass}"
REALM="${REALM:-POLARIS}"
CATALOG_NAME="${CATALOG_NAME:-redpanda_catalog}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"

echo "=== Setting up Polaris Catalog ==="
echo "Polaris endpoint: http://${POLARIS_HOST}:${POLARIS_PORT}"
echo "Catalog name: ${CATALOG_NAME}"
echo ""

# Step 1: Get OAuth2 token
echo "Step 1: Getting OAuth2 token..."
TOKEN=$(curl -s -X POST "http://${POLARIS_HOST}:${POLARIS_PORT}/api/catalog/v1/oauth/tokens" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Polaris-Realm: ${REALM}" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL" \
  | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to get OAuth2 token"
    exit 1
fi

echo "✓ Token obtained successfully"
echo ""

# Step 2: Create catalog
echo "Step 2: Creating catalog '${CATALOG_NAME}'..."
CATALOG_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "http://${POLARIS_HOST}:${POLARIS_PORT}/api/management/v1/catalogs" \
  -H "Polaris-Realm: ${REALM}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": \"INTERNAL\",
    \"name\": \"${CATALOG_NAME}\",
    \"properties\": {
      \"default-base-location\": \"s3://redpanda\"
    },
    \"storageConfigInfo\": {
      \"roleArn\": \"arn:aws:iam::123456789012:role/dummy\",
      \"region\": \"us-east-1\",
      \"endpoint\": \"${MINIO_ENDPOINT}\",
      \"pathStyleAccess\": true,
      \"storageType\": \"S3\",
      \"allowedLocations\": [\"s3://redpanda\"]
    }
  }")

HTTP_CODE=$(echo "$CATALOG_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$CATALOG_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Catalog created successfully"
elif [ "$HTTP_CODE" = "409" ]; then
    echo "⚠ Catalog already exists (409), continuing..."
else
    echo "ERROR: Failed to create catalog (HTTP $HTTP_CODE)"
    echo "Response: $RESPONSE_BODY"
    exit 1
fi
echo ""

# Step 3: Create 'redpanda' namespace in the catalog
echo "Step 3: Creating 'redpanda' namespace in catalog..."
NAMESPACE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "http://${POLARIS_HOST}:${POLARIS_PORT}/api/catalog/v1/${CATALOG_NAME}/namespaces" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"namespace": ["redpanda"], "properties": {}}')

HTTP_CODE=$(echo "$NAMESPACE_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$NAMESPACE_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    echo "✓ Namespace 'redpanda' created successfully"
elif [ "$HTTP_CODE" = "409" ]; then
    echo "⚠ Namespace already exists (409), continuing..."
else
    echo "ERROR: Failed to create namespace (HTTP $HTTP_CODE)"
    echo "Response: $RESPONSE_BODY"
    exit 1
fi
echo ""

# Step 4: Create catalog admin role
echo "Step 4: Creating catalog admin role..."
ROLE_RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT "http://${POLARIS_HOST}:${POLARIS_PORT}/api/management/v1/catalogs/${CATALOG_NAME}/catalog-roles/catalog_admin/grants" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"grant":{"type":"catalog", "privilege":"CATALOG_MANAGE_CONTENT"}}')

HTTP_CODE=$(echo "$ROLE_RESPONSE" | tail -n1)
if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Catalog admin role created successfully"
else
    echo "⚠ Catalog admin role creation status: HTTP $HTTP_CODE (may already exist)"
fi
echo ""

# Step 5: Create principal role
echo "Step 5: Creating principal role 'data_engineer'..."
PRINCIPAL_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "http://${POLARIS_HOST}:${POLARIS_PORT}/api/management/v1/principal-roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"principalRole":{"name":"data_engineer"}}')

HTTP_CODE=$(echo "$PRINCIPAL_RESPONSE" | tail -n1)
if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Principal role created successfully"
elif [ "$HTTP_CODE" = "409" ]; then
    echo "⚠ Principal role already exists (409), continuing..."
else
    echo "⚠ Principal role creation status: HTTP $HTTP_CODE"
fi
echo ""

# Step 6: Connect the roles
echo "Step 6: Connecting principal role to catalog role..."
CONNECT_RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT "http://${POLARIS_HOST}:${POLARIS_PORT}/api/management/v1/principal-roles/data_engineer/catalog-roles/${CATALOG_NAME}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"catalogRole":{"name":"catalog_admin"}}')

HTTP_CODE=$(echo "$CONNECT_RESPONSE" | tail -n1)
if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Roles connected successfully"
else
    echo "⚠ Role connection status: HTTP $HTTP_CODE"
fi
echo ""

# Step 7: Assign role to root principal
echo "Step 7: Assigning data_engineer role to root principal..."
ASSIGN_RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT "http://${POLARIS_HOST}:${POLARIS_PORT}/api/management/v1/principals/root/principal-roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"principalRole": {"name":"data_engineer"}}')

HTTP_CODE=$(echo "$ASSIGN_RESPONSE" | tail -n1)
if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Role assigned to root principal successfully"
else
    echo "⚠ Role assignment status: HTTP $HTTP_CODE"
fi
echo ""

# Verify setup
echo "Step 8: Verifying catalog setup..."
CATALOGS=$(curl -s -X GET "http://${POLARIS_HOST}:${POLARIS_PORT}/api/management/v1/catalogs" \
  -H "Authorization: Bearer $TOKEN")

if echo "$CATALOGS" | grep -q "${CATALOG_NAME}"; then
    echo "✓ Catalog '${CATALOG_NAME}' verified in Polaris"
else
    echo "⚠ Warning: Could not verify catalog in listing"
    echo "Response: $CATALOGS"
fi
echo ""

echo "=== Polaris Catalog Setup Complete ==="
exit 0
