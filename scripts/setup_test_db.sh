#!/bin/bash
# PostgreSQL 16 + PostGIS + pgvector setup script for test environment
# This script sets up a local PostgreSQL instance for running backend tests

set -e

echo "=== MecaniMovil Backend Test Database Setup ==="

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo "PostgreSQL not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y postgresql-16 postgresql-contrib-16
fi

# Check if PostGIS is installed
if ! dpkg -l | grep -q postgresql-16-postgis; then
    echo "PostGIS not found. Installing..."
    sudo apt-get install -y postgresql-16-postgis-3
fi

# Check if pgvector is installed
if ! dpkg -l | grep -q postgresql-16-pgvector; then
    echo "pgvector not found. Installing..."
    sudo apt-get install -y postgresql-16-pgvector
fi

# Start PostgreSQL if not running (no systemd)
if ! sudo pg_lsclusters | grep -q "16.*main.*online"; then
    echo "Starting PostgreSQL cluster..."
    sudo pg_ctlcluster 16 main start
fi

# Create test user and database
echo "Setting up test database and user..."
sudo -u postgres psql <<EOF
-- Create test user if not exists
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'mecani_test') THEN
        CREATE USER mecani_test WITH PASSWORD 'test_password' SUPERUSER;
    END IF;
END
\$\$;

-- Create test database if not exists
SELECT 'CREATE DATABASE mecanimovil_test OWNER mecani_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mecanimovil_test')\gexec

-- Connect to test database and create extensions
\c mecanimovil_test

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE mecanimovil_test TO mecani_test;
GRANT ALL ON SCHEMA public TO mecani_test;

EOF

echo "=== Database setup complete ==="
echo "Database: mecanimovil_test"
echo "User: mecani_test"
echo "Password: test_password"
echo "Host: localhost"
echo "Port: 5432"
echo ""
echo "Update your .env file with:"
echo "DATABASE_URL=postgresql://mecani_test:test_password@localhost:5432/mecanimovil_test"
