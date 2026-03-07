-- 004_dedup_and_cleanup.sql
-- 1. Update query functions to deduplicate by title
-- 2. Delete existing articles with bad titles
-- 3. Delete duplicate-title articles (keep newest per title)

-- ============================================================
-- Update nearby_articles to deduplicate by title
-- ============================================================
CREATE OR REPLACE FUNCTION nearby_articles(
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    radius_km DOUBLE PRECISION DEFAULT 100,
    limit_count INTEGER DEFAULT 50
)
RETURNS SETOF articles
LANGUAGE sql STABLE
AS $$
    SELECT * FROM (
        SELECT DISTINCT ON (lower(title)) *
        FROM articles
        WHERE ST_DWithin(
            location,
            ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography,
            radius_km * 1000
        )
        ORDER BY lower(title), published_at DESC
    ) deduped
    ORDER BY published_at DESC
    LIMIT limit_count;
$$;

-- ============================================================
-- Update articles_in_bounds to deduplicate by title
-- ============================================================
CREATE OR REPLACE FUNCTION articles_in_bounds(
    min_lat DOUBLE PRECISION,
    min_lng DOUBLE PRECISION,
    max_lat DOUBLE PRECISION,
    max_lng DOUBLE PRECISION,
    limit_count INTEGER DEFAULT 200
)
RETURNS SETOF articles
LANGUAGE sql STABLE
AS $$
    SELECT * FROM (
        SELECT DISTINCT ON (lower(title)) *
        FROM articles
        WHERE ST_Within(
            location::geometry,
            ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326)
        )
        ORDER BY lower(title), published_at DESC
    ) deduped
    ORDER BY published_at DESC
    LIMIT limit_count;
$$;

-- ============================================================
-- Clean up existing bad titles
-- ============================================================
DELETE FROM articles WHERE lower(title) LIKE '%just a moment%';
DELETE FROM articles WHERE lower(title) LIKE '%cloudflare%';
DELETE FROM articles WHERE lower(title) LIKE '%access denied%';
DELETE FROM articles WHERE lower(title) LIKE '%attention required%';
DELETE FROM articles WHERE lower(title) LIKE '%checking your browser%';
DELETE FROM articles WHERE lower(title) LIKE '%please wait%';
DELETE FROM articles WHERE lower(title) ~ '^(4\d\d|5\d\d)\s';
DELETE FROM articles WHERE lower(title) ~ '^article\s+[0-9a-f]';

-- ============================================================
-- Delete duplicate-title articles (keep the newest per title)
-- ============================================================
DELETE FROM articles
WHERE id NOT IN (
    SELECT DISTINCT ON (lower(title)) id
    FROM articles
    ORDER BY lower(title), published_at DESC
);
