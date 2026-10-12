# Orbis Database

PostgreSQL schema for the Orbis globe news explorer, powered by **Supabase** with **PostGIS** (spatial queries) and **pgvector** (embeddings).

## Schema Overview

### `articles` table

| Column            | Type                    | Notes                                 |
|-------------------|-------------------------|---------------------------------------|
| `id`              | UUID (PK)               | Auto-generated via `uuid_generate_v4` |
| `title`           | TEXT                    | Required                              |
| `summary`         | TEXT                    | AI-generated, nullable                |
| `source_url`      | TEXT (UNIQUE)           | Deduplication key                     |
| `source_name`     | TEXT                    | e.g. "Reuters", "BBC"                 |
| `source_language` | TEXT                    | Default `'en'`                        |
| `published_at`    | TIMESTAMPTZ             | When the article was published        |
| `ingested_at`     | TIMESTAMPTZ             | Auto-set to `NOW()`                   |
| `location`        | GEOGRAPHY(Point, 4326)  | PostGIS geography for spatial queries |
| `latitude`        | DOUBLE PRECISION        | Numeric latitude                      |
| `longitude`       | DOUBLE PRECISION        | Numeric longitude                     |
| `country_code`    | TEXT                    | ISO 3166-1 alpha-2 (`''` if unknown)  |
| `country_fips`    | TEXT                    | Raw GDELT FIPS 10-4 code; NULL = row predates the ISO switch (backfilled by ingestion) |
| `region`          | TEXT                    | Continent / sub-region                |
| `topic_tags`      | TEXT[]                  | Array of topic labels                 |
| `sentiment_score` | DOUBLE PRECISION        | Range roughly -1.0 to 1.0            |
| `entities`        | JSONB                   | Named entities extracted by AI        |
| `embedding`       | VECTOR(1536)            | OpenAI `text-embedding-3-small`, for semantic search. HNSW index `idx_articles_embedding_half` is built at half precision on `(embedding::halfvec(1536))`; queries must use that exact cast to hit it (migration 008) |
| `image_url`       | TEXT                    | Thumbnail URL, nullable               |
| `themes`          | TEXT[]                  | GDELT GKG themes; default `'{}'`      |
| `persons`         | TEXT[]                  | GKG people; default `'{}'`            |
| `orgs`            | TEXT[]                  | GKG organisations; default `'{}'`     |
| `names`           | TEXT[]                  | Most frequent GKG proper names; default `'{}'` |
| `counts`          | JSONB                   | GKG typed counts (killed, arrested, ...); default `'[]'` |
| `mentioned_countries` | TEXT[]              | ISO 3166-1 alpha-2 codes of the countries the article mentions (GDELT country-level locations), filled by ingestion; links between places are computed from it; default `'{}'` (migration 011) |

### SQL Functions

| Function              | Purpose                                         |
|-----------------------|-------------------------------------------------|
| `nearby_articles()`   | Articles within N km of a lat/lng point          |
| `articles_in_bounds()`| Articles inside a bounding box. Unused: the backend's `get_articles_in_bounds` inlines its own query |
| `cluster_articles()`  | Grid-cell clustering with counts                |
| `topic_counts()`      | Count of articles per topic tag                 |

### Row Level Security

- **SELECT**: public (no auth required)
- **INSERT / UPDATE / DELETE**: service role only

## Required Extensions

Enable these in the Supabase Dashboard under **Database > Extensions**:

1. **uuid-ossp** -- UUID generation (usually enabled by default)
2. **PostGIS** -- spatial/geographic queries
3. **pgvector** -- vector embeddings

## Running Migrations

### Option A: Setup script

```bash
export DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres"
bash database/setup.sh
```

### Option B: Supabase SQL Editor

1. Open your project in the [Supabase Dashboard](https://supabase.com/dashboard)
2. Go to **SQL Editor > New query**
3. Paste and run each file in order:
   - `migrations/001_extensions.sql`
   - `migrations/002_articles.sql`
   - `migrations/003_functions.sql`
   - `migrations/004_rls_policies.sql`
4. Run `seed.sql` to populate sample data

## Seeding Data

The seed file inserts ~20 articles with worldwide geographic coverage, realistic titles, and timestamps relative to `NOW()` so the data always appears fresh.

> **Re-seed local databases after migration `007_country_fips.sql`.** Rows seeded before 007 have no `country_fips`, so the ingestion backfill treats their ISO `country_code` as a FIPS code and rewrites it (for example `GB` becomes `GA`, Gabon). Delete those rows (or recreate the database) and run `seed.sql` again; the current seed sets `country_fips` on every row.

```bash
psql "${DATABASE_URL}" -f database/seed.sql
```
