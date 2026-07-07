-- Enabled once on first container boot (via /docker-entrypoint-initdb.d).
-- pgvector powers embedding similarity; citext gives case-insensitive handles.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;
