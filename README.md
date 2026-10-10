# Orbis

Interactive 3D globe for exploring geolocated world news with AI-powered summaries.

![Next.js](https://img.shields.io/badge/Next.js-16-black)
![FastAPI](https://img.shields.io/badge/FastAPI-0.133-009688)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6)

## Overview

Orbis plots real-time news from the [GDELT](https://www.gdeltproject.org/) API onto a 3D globe. Articles are geolocated by country, clustered spatially, classified into topics, and summarized by Claude AI when a user clicks a cluster.

**Key features:**

- Real-time 3D globe powered by [globe.gl](https://globe.gl/) (Three.js)
- GDELT news feed with 15-minute refresh and Redis caching
- Keyword-based topic classification (7 categories) with post-filtering
- AI cluster summaries via Claude Haiku with 6-hour grid-cell caching
- Sentiment-colored data points and animated slide-out news panel

## Tech Stack

| Layer          | Technology                                      |
| -------------- | ----------------------------------------------- |
| Frontend       | Next.js, React, TypeScript, Tailwind, Framer Motion |
| 3D Globe       | globe.gl (Three.js)                             |
| Backend        | Python, FastAPI, Uvicorn                         |
| Database       | Azure PostgreSQL (asyncpg)                       |
| Cache          | Azure Cache for Redis                            |
| News Data      | GDELT DOC 2.0 API                               |
| AI Summaries   | Anthropic Claude Haiku                           |
| Infrastructure | Terraform, Azure Container Apps, Vercel          |
| CI/CD          | GitHub Actions                                   |

## Project Structure

```
Orbis/
├── frontend/          # Next.js app
│   ├── src/
│   │   ├── app/           # Pages
│   │   ├── components/    # Globe, NewsPanel, TopicFilter
│   │   ├── lib/           # API client, clustering, mock data
│   │   └── types/         # TypeScript interfaces
│   └── e2e/           # Playwright tests
├── backend/           # FastAPI app
│   ├── app/
│   │   ├── routers/       # API endpoints
│   │   ├── services/      # GDELT, clustering, AI summary, cache
│   │   └── models/        # Pydantic models
│   └── tests/         # pytest suite
├── database/          # SQL migrations
├── infra/             # Terraform (Azure)
└── .github/workflows/ # CI + Deploy pipelines
```

## Getting Started

### Prerequisites

- Node.js 22+
- Python 3.12+
- Redis (optional — caching degrades gracefully)

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The browser calls same-origin `/api/*`, which Next.js proxies to the backend. Set `ORBIS_API_URL` (defaults to `http://localhost:8000`) and, if the backend has a key, `ORBIS_API_KEY` in `frontend/.env.local`.

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your values
uvicorn app.main:app --reload
```

Required environment variables:

| Variable            | Description                          |
| ------------------- | ------------------------------------ |
| `DATABASE_URL`      | PostgreSQL connection string         |
| `ANTHROPIC_API_KEY` | Anthropic API key for AI summaries   |

Optional (sensible defaults):

| Variable               | Default   | Description                        |
| ---------------------- | --------- | ---------------------------------- |
| `REDIS_URL`            | —         | Redis connection (disabled if unset) |
| `GDELT_CACHE_TTL`     | `900`     | GDELT cache duration (seconds)     |
| `SUMMARY_CACHE_TTL`   | `21600`   | AI summary cache duration (seconds) |
| `CLUSTER_RESOLUTION_DEG` | `2.0`  | Clustering grid size (degrees)     |
| `HAIKU_MODEL_ID`       | `claude-haiku-4-5-20251001` | Claude model for summaries |

See [`backend/.env.example`](backend/.env.example) for the full list.

## Running Tests

```bash
# Backend (57 tests)
cd backend
python -m pytest tests/ -v

# Frontend unit tests (14 tests)
cd frontend
npm run test

# Frontend E2E (Playwright)
cd frontend
npx playwright install --with-deps chromium
npm run test:e2e
```

## CI/CD

**Pull requests** trigger the CI workflow (`.github/workflows/ci.yml`):
- Frontend: ESLint, Prettier, Vitest, Next.js build
- Backend: Ruff lint/format, pytest
- E2E: Playwright on Chromium
- Infra: Terraform fmt/validate

**Pushes to main** trigger the Deploy workflow (`.github/workflows/deploy.yml`):
- Backend changes: Docker build → GHCR → Azure Container Apps
- Database changes: Idempotent SQL migration runner
- Frontend: Deployed automatically by Vercel's GitHub integration

## API Endpoints

| Method | Path                | Description                          |
| ------ | ------------------- | ------------------------------------ |
| GET    | `/api/news`         | Globe data points (clustered)        |
| GET    | `/api/news/cluster` | Articles near a lat/lng              |
| GET    | `/api/news/summary` | AI-generated cluster summary         |
| GET    | `/api/topics`       | Topic categories with article counts |
| GET    | `/health`           | Health check (DB + Redis status)     |

## License

Private repository.
