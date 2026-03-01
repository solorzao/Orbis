CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Backfill already-applied migrations
INSERT INTO schema_migrations (filename) VALUES
    ('001_extensions.sql'),
    ('002_articles.sql'),
    ('003_functions.sql'),
    ('004_rls_policies.sql'),
    ('005_migration_tracking.sql')
ON CONFLICT (filename) DO NOTHING;
