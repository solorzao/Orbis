# Rolling 7-Day Article Retention

**Date:** 2026-03-07
**Status:** Approved

## Goal

Shift Orbis from indefinite article storage to a rolling 7-day window. Positions the app as a live news pulse for recent events, not a news archive.

## Changes

### 1. Config constant (`backend/app/config.py`)
- Add `RETENTION_DAYS = 7`

### 2. Cleanup function (`backend/app/services/ingestion.py`)
- `DELETE FROM articles WHERE published_at < NOW() - INTERVAL '7 days'`
- Runs after each ingestion cycle (every 15 min)
- Logs row count deleted

### 3. Scheduler integration (`backend/app/services/scheduler.py`)
- Call cleanup after upsert + cache invalidation

### 4. Remove legacy startup cleanup (`backend/app/main.py`)
- Remove the empty-region article deletion on startup (rolling retention handles it)

### 5. Preserved
- pgvector/embeddings column (needed for upcoming embedded agent feature)
- Frontend time slider and timespan params (unchanged)
- Redis caching config
- API endpoints and query logic
- Database schema (no migrations)
