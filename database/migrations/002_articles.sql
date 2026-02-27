-- 002_articles.sql
-- Core articles table for Orbis news data.

CREATE TABLE IF NOT EXISTS articles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title           TEXT NOT NULL,
    summary         TEXT,
    source_url      TEXT NOT NULL UNIQUE,
    source_name     TEXT NOT NULL,
    source_language TEXT DEFAULT 'en',
    published_at    TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ DEFAULT NOW(),
    location        GEOGRAPHY(Point, 4326) NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    country_code    TEXT,
    region          TEXT,
    topic_tags      TEXT[] DEFAULT '{}',
    sentiment_score DOUBLE PRECISION DEFAULT 0.0,
    entities        JSONB DEFAULT '{}',
    embedding       VECTOR(1536),
    image_url       TEXT
);

-- Spatial index for PostGIS geography queries (ST_DWithin, etc.)
CREATE INDEX IF NOT EXISTS idx_articles_location
    ON articles USING GIST (location);

-- Temporal index for time-range filtering
CREATE INDEX IF NOT EXISTS idx_articles_published_at
    ON articles (published_at);

-- GIN index for array-contains queries on topic tags
CREATE INDEX IF NOT EXISTS idx_articles_topic_tags
    ON articles USING GIN (topic_tags);

-- Filtering by country
CREATE INDEX IF NOT EXISTS idx_articles_country_code
    ON articles (country_code);

-- Filtering/sorting by sentiment
CREATE INDEX IF NOT EXISTS idx_articles_sentiment_score
    ON articles (sentiment_score);
