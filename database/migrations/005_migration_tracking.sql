CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- This file runs before every migration pass. The backfill below is only
-- valid for databases created before tracking existed; on a fresh database
-- (no articles table yet) clear any rows it wrote so every migration runs.
DELETE FROM schema_migrations WHERE to_regclass('public.articles') IS NULL;

-- Backfill already-applied migrations (pre-tracking databases only)
INSERT INTO schema_migrations (filename)
SELECT filename
FROM unnest(ARRAY[
    '001_extensions.sql',
    '002_articles.sql',
    '003_functions.sql',
    '004_rls_policies.sql',
    '005_migration_tracking.sql'
]) AS filename
WHERE to_regclass('public.articles') IS NOT NULL
ON CONFLICT (filename) DO NOTHING;
