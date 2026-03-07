-- 003_functions.sql
-- Utility SQL functions for spatial and analytical queries.

-- ============================================================
-- nearby_articles: find articles within a radius (km) of a point
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
            radius_km * 1000  -- ST_DWithin uses metres for geography
        )
        ORDER BY lower(title), published_at DESC
    ) deduped
    ORDER BY published_at DESC
    LIMIT limit_count;
$$;

-- ============================================================
-- articles_in_bounds: bounding-box query for visible globe area
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
-- cluster_articles: group articles into grid cells and return
-- cluster centres with article counts.
-- cell_size is in degrees (e.g. 2.0 for ~200 km cells at equator).
-- ============================================================
CREATE OR REPLACE FUNCTION cluster_articles(
    cell_size DOUBLE PRECISION DEFAULT 2.0
)
RETURNS TABLE(
    cluster_lat DOUBLE PRECISION,
    cluster_lng DOUBLE PRECISION,
    article_count BIGINT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        ROUND(latitude / cell_size) * cell_size  + cell_size / 2 AS cluster_lat,
        ROUND(longitude / cell_size) * cell_size + cell_size / 2 AS cluster_lng,
        COUNT(*) AS article_count
    FROM articles
    GROUP BY cluster_lat, cluster_lng
    ORDER BY article_count DESC;
$$;

-- ============================================================
-- topic_counts: count of articles per topic tag (unnested)
-- ============================================================
CREATE OR REPLACE FUNCTION topic_counts()
RETURNS TABLE(
    topic TEXT,
    count BIGINT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        UNNEST(topic_tags) AS topic,
        COUNT(*) AS count
    FROM articles
    GROUP BY topic
    ORDER BY count DESC;
$$;
