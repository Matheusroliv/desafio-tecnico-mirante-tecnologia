#!/bin/bash
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
SELECT 'CREATE DATABASE legacy'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'legacy')\gexec
SQL
