-- 007_country_fips.sql
-- Raw GDELT FIPS 10-4 country code. articles.country_code becomes ISO 3166-1
-- alpha-2 (see backend/app/services/country_codes.py, added with the code
-- change that follows this migration). NULL marks rows written before the
-- switch, which ingestion backfills.

-- Catalog-only change, but never queue API reads behind a lock held by an
-- ingestion transaction: fail fast and let the workflow be re-run instead.
SET lock_timeout = '5s';
ALTER TABLE articles ADD COLUMN IF NOT EXISTS country_fips TEXT;
