SELECT 'CREATE DATABASE legacy'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'legacy')\gexec
