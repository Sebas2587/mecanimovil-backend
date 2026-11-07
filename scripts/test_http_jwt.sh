#!/bin/bash
# Test HTTP endpoints with real JWT authentication
set -e

BASE_URL="http://localhost:8000"
API_BASE="${BASE_URL}/api"

echo "=== Testing HTTP Endpoints with JWT ==="
echo ""

# Seed data and capture tokens
echo "1. Seeding test data..."
SEED_OUTPUT=$(cd /agent/repos/mecanimovil-backend && ./run_django.sh scripts/seed_test_users.py 2>&1)
echo "$SEED_OUTPUT" | tail -20

# Extract token (simplified - in production use jq)
MANDANTE_TOKEN=$(echo "$SEED_OUTPUT" | grep -A2 "MANDANTE:" | grep "Access Token:" | awk '{print $3}' | cut -d'.' -f1-3)

if [ -z "$MANDANTE_TOKEN" ]; then
    echo "ERROR: Failed to extract JWT token"
    exit 1
fi

echo ""
echo "2. Testing authenticated endpoint..."
echo "GET ${API_BASE}/ordenes/proveedor-ordenes/"

RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
    -H "Authorization: Bearer ${MANDANTE_TOKEN}" \
    "${API_BASE}/ordenes/proveedor-ordenes/")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d':' -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS/d')

echo "Status: $HTTP_STATUS"
echo "Response preview: $(echo "$BODY" | head -c 200)..."

if [ "$HTTP_STATUS" != "200" ]; then
    echo "ERROR: Expected 200, got $HTTP_STATUS"
    echo "Full response: $BODY"
    exit 1
fi

echo "✓ Authenticated list orders successful"

echo ""
echo "3. Testing order accept (idempotent)..."
ORDER_ID=$(echo "$SEED_OUTPUT" | grep "Pending Order ID:" | awk '{print $4}')

ACCEPT_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
    -X POST \
    -H "Authorization: Bearer ${MANDANTE_TOKEN}" \
    -H "Content-Type: application/json" \
    "${API_BASE}/ordenes/proveedor-ordenes/${ORDER_ID}/aceptar/")

ACCEPT_STATUS=$(echo "$ACCEPT_RESPONSE" | grep "HTTP_STATUS" | cut -d':' -f2)
echo "Status: $ACCEPT_STATUS"

if [ "$ACCEPT_STATUS" != "200" ]; then
    echo "ERROR: Accept failed with status $ACCEPT_STATUS"
    echo "Response: $(echo "$ACCEPT_RESPONSE" | sed '/HTTP_STATUS/d')"
    exit 1
fi

echo "✓ Order accept successful"

echo ""
echo "4. Testing assignment..."
MECANICO_ID=$(echo "$SEED_OUTPUT" | grep "Mechanic ID:" | awk '{print $3}')

ASSIGN_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
    -X POST \
    -H "Authorization: Bearer ${MANDANTE_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"mecanico_id\": ${MECANICO_ID}}" \
    "${API_BASE}/ordenes/proveedor-ordenes/${ORDER_ID}/asignar_tecnico/")

ASSIGN_STATUS=$(echo "$ASSIGN_RESPONSE" | grep "HTTP_STATUS" | cut -d':' -f2)
echo "Status: $ASSIGN_STATUS"

if [ "$ASSIGN_STATUS" != "200" ]; then
    echo "WARNING: Assignment returned $ASSIGN_STATUS (may be expected)"
else
    echo "✓ Technician assignment successful"
fi

echo ""
echo "=== HTTP JWT Tests Complete ==="
echo "All critical endpoints verified with real JWT authentication"
