# Orbis — News Licensing & Cost Analysis

---

## Part 1: News Source Licensing

### GDELT (Recommended Primary Source)

**License:** Open data platform, free for commercial use
**Terms:** GDELT positions itself as a "free open platform for computing on the entire world." The data (events, entities, locations, sentiment) is freely available. However, GDELT provides *metadata and analysis* about news articles — not the full article text. You get titles, URLs, tone scores, entities, and geolocation, but not article bodies.

**Key considerations:**
- ✅ Free, no rate limits on bulk data downloads (updated every 15 minutes)
- ✅ Pre-geolocated data across 65 languages — huge win for Orbis
- ✅ Includes sentiment/tone scores out of the box
- ✅ Historical data back to 1979
- ✅ Commercial use permitted
- ⚠️ No full article text — only metadata, URLs, and extracted entities
- ⚠️ Geocoding accuracy varies, especially for small/remote locations
- ⚠️ DOC API searches limited to rolling 3-month window; bulk downloads needed for deeper history

**Recommendation:** Use GDELT as the backbone for geolocation, event detection, and sentiment. Supplement with a headline API for cleaner user-facing content.

---

### NewsAPI.org

**License:** Tiered commercial licensing

| Plan | Price | Requests | Notes |
|------|-------|----------|-------|
| Developer | Free | 100/day | Dev/test only, **cannot be used in production** |
| Business | $449/mo | 250K/mo | Production use, real-time articles, 5yr archive |
| Advanced | $1,749/mo | 2M/mo | 99.95% SLA, priority support |
| Enterprise | Custom | Unlimited | Extended source library, article clustering |

**Key considerations:**
- ❌ Free tier explicitly prohibits production/commercial use
- ❌ No full article content — only titles, descriptions, URLs
- ⚠️ $449/mo minimum for any production deployment
- ✅ Clean, well-structured headline data
- ✅ 5-year article search archive on paid plans

---

### NewsData.io

**License:** Commercial-friendly, including free tier

| Plan | Price | Credits/mo | Notes |
|------|-------|------------|-------|
| Free | $0 | 200/day | Commercial use allowed, 12hr delay, 10 articles/credit |
| Basic | $200/mo | 20,000 | Real-time, 6mo history, 50 articles/credit |
| Professional | $400/mo | 50,000 | 2yr history, priority support |

**Key considerations:**
- ✅ Free tier allows commercial use (rare!)
- ✅ 87,000+ sources, 89 languages
- ⚠️ Free tier has 12-hour delay and limited articles per request
- ✅ Good alternative to NewsAPI for cleaner headline data

---

### GNews API

**License:** Commercial use requires paid plan

| Plan | Price | Requests/day | Notes |
|------|-------|-------------|-------|
| Free | $0 | 100 | Dev/test only, **no commercial use** |
| Starter | $50/mo | 30,000 | Commercial use allowed |
| Business | Custom | Custom | Enterprise features |

**Key considerations:**
- ❌ Free tier cannot be used commercially
- ✅ Affordable entry at $50/mo
- ⚠️ Historical data only back to 2020
- ⚠️ No source filtering available

---

### Licensing Recommendation

**MVP (minimize cost):** GDELT (free) + NewsData.io free tier
- GDELT provides geolocation, events, and sentiment
- NewsData.io supplements with cleaner headlines for user-facing display
- Total news API cost: **$0/mo**

**Growth stage:** GDELT + NewsAPI.org Business
- NewsAPI provides much better headline quality and 5yr archive
- Total news API cost: **$449/mo**

**⚠️ Critical legal note:** None of these APIs provide full article text for redistribution. Orbis should display headlines, summaries, and source attribution with links to original articles. Reproducing full article content would require direct licensing agreements with publishers.

---

## Part 2: Cost Analysis by Scenario

### Scenario 1: MVP (Solo Dev, Pre-Launch)

| Component | Service | Monthly Cost |
|-----------|---------|-------------|
| **News Data** | GDELT + NewsData.io (free tiers) | $0 |
| **Frontend Hosting** | Vercel Hobby (free) | $0 |
| **Database** | Supabase Free (500MB, pgvector included) | $0 |
| **Cache** | Upstash Redis (free tier, 10K commands/day) | $0 |
| **AI - Summaries** | Claude Haiku 4.5 ($1/$5 per MTok) | ~$5 |
| **Embeddings** | OpenAI text-embedding-3-small ($0.02/MTok) | ~$1 |
| **Domain** | .io or .com | ~$10 |
| | **Total** | **~$16/mo** |

**Assumptions:** ~500 articles/day ingested, ~100 daily users, light AI usage, no paid AI features yet.

---

### Scenario 2: Early Growth (Launched, ~1K DAU)

| Component | Service | Monthly Cost |
|-----------|---------|-------------|
| **News Data** | GDELT + NewsData.io Basic ($200/mo) | $200 |
| **Frontend Hosting** | Vercel Pro ($20/mo) | $20 |
| **Database** | Supabase Pro ($25/mo + compute add-on) | $75 |
| **Cache** | Upstash Redis Pro | $10 |
| **AI - Summaries** | Claude Haiku 4.5 | ~$30 |
| **AI - RAG/Features** | Claude Sonnet 4.5 ($3/$15 per MTok) | ~$80 |
| **Embeddings** | OpenAI text-embedding-3-small | ~$5 |
| **Auth** | Supabase Auth (included in Pro) | $0 |
| **Monitoring** | Free tier (Vercel Analytics + Sentry) | $0 |
| | **Total** | **~$420/mo** |

**Assumptions:** ~2,000 articles/day ingested and embedded, ~1,000 DAU, ~100 Pro subscribers using AI features, moderate RAG queries.

**Revenue needed to break even:** ~42–84 Pro subscribers at $5–10/mo.

---

### Scenario 3: Scaling (10K DAU, Growing Pro Base)

| Component | Service | Monthly Cost |
|-----------|---------|-------------|
| **News Data** | GDELT + NewsAPI.org Business ($449) | $449 |
| **Frontend Hosting** | Vercel Pro (with bandwidth overages) | $50 |
| **Database** | Supabase Pro + Large Compute ($110) | $185 |
| **Cache** | Upstash Redis or self-hosted on Azure | $30 |
| **AI - Summaries** | Claude Haiku 4.5 (batch, 50% off) | ~$60 |
| **AI - RAG/Features** | Claude Sonnet 4.5 (w/ prompt caching) | ~$300 |
| **Embeddings** | OpenAI text-embedding-3-small | ~$20 |
| **Daily Briefings** | Claude Haiku 4.5 (batch) | ~$40 |
| **Sentiment Analysis** | Claude Haiku 4.5 (batch) | ~$50 |
| **Email (Briefings)** | Resend or Postmark | $20 |
| **Monitoring** | Sentry + Vercel Analytics | $30 |
| | **Total** | **~$1,234/mo** |

**Assumptions:** ~5,000 articles/day, 10K DAU, ~500 Pro subscribers, heavy RAG usage, daily briefing emails.

**Revenue at 500 Pro subs × $8/mo = $4,000/mo → healthy margin.**

---

## Part 3: Cost Optimization Strategies

### AI Cost Reduction

| Strategy | Savings | How |
|----------|---------|-----|
| **Prompt caching** | Up to 90% on input tokens | Cache system prompts and region context across requests |
| **Batch API** | 50% on all tokens | Use for non-real-time work: embeddings, sentiment analysis, daily briefings, narrative generation |
| **Model routing** | ~60% overall | Use Haiku 4.5 ($1/$5) for summaries, sentiment, classification. Reserve Sonnet ($3/$15) for RAG answers and narratives |
| **Smart chunking** | Variable | Embed article summaries (shorter) instead of full text to reduce embedding costs |

### Database Cost Reduction

- **pgvector over dedicated vector DB:** Saves $50-200/mo vs Pinecone/Weaviate, works fine up to millions of vectors
- **Supabase over standalone Postgres + separate auth:** Saves significant integration overhead and potentially $100+/mo on auth services
- **Aggressive caching with Redis:** Cache hot news data (last 24h) and popular RAG results to reduce DB queries

### News Data Cost Reduction

- **GDELT as primary:** Free forever, and provides the most critical data (geolocation + events)
- **Defer NewsAPI until revenue justifies it:** The $449/mo jump is significant — only upgrade when user demand requires cleaner headline data
- **Consider NewsData.io as a middle ground:** $200/mo for decent quality with commercial-friendly terms

---

## Part 4: Embedding & Storage Cost Projection

### How fast does the vector DB grow?

| Timeframe | Articles Stored | Estimated Storage | Embedding Cost (cumulative) |
|-----------|----------------|-------------------|---------------------------|
| Month 1 | 60K | ~0.5 GB (vectors) + 0.3 GB (metadata) | $0.60 |
| Month 6 | 360K | ~3 GB + 2 GB | $3.60 |
| Year 1 | 730K | ~6 GB + 4 GB | $7.30 |
| Year 3 | 2.2M | ~18 GB + 12 GB | $22.00 |
| Year 5 | 3.6M | ~30 GB + 20 GB | $36.00 |

**Key insight:** Embedding costs are negligible at $0.02 per million tokens. Storage is the real cost driver over time, but even at Year 5 (~50 GB total), Supabase Pro handles this comfortably within its included storage + modest overages (~$5-10/mo extra).

pgvector performs well up to ~5-10 million vectors. Beyond that, you'd evaluate dedicated vector DBs or horizontal scaling — but that's likely 3-5 years out at 2K articles/day.

---

## Summary

| Stage | Monthly Cost | Revenue Needed | Break-even Subs |
|-------|-------------|----------------|-----------------|
| **MVP** | ~$16 | - | - |
| **Early Growth** (1K DAU) | ~$420 | ~$420 | 42-84 Pro subs |
| **Scaling** (10K DAU) | ~$1,234 | ~$1,234 | 154 Pro subs |

The economics are very favorable. The biggest cost drivers are the Claude API for AI features and the news API licensing at scale. Both scale with usage and can be heavily optimized with caching, batching, and model routing — all things you have experience with from your ML work at Tapcheck. The MVP is essentially free to run, and the path to profitability is achievable with a modest number of paying subscribers.
