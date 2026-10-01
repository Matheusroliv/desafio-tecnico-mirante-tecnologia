-- Databases auxiliares na mesma instancia do Compose:
--   legacy   -> metrica de Equivalencia Comportamental (schemas temporarios, nada persiste)
--   langfuse -> Langfuse self-hosted (profile observability)
SELECT 'CREATE DATABASE legacy'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'legacy')\gexec

SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
