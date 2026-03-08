# ORBIS — Project Brief for Development

## What is Orbis?

Orbis is a web app that lets users interact with a 3D globe to discover, explore, and understand news happening around the world. News stories appear as glowing dots/clusters on the globe. AI features turn raw news into understanding.

---

## Tech Stack

- **Frontend:** React / Next.js + globe.gl (Three.js-based) + Tailwind CSS + Framer Motion
- **Backend:** Python FastAPI
- **Database:** Supabase (PostgreSQL + PostGIS + pgvector + Auth)
- **Cache:** Upstash Redis
- **News Data:** GDELT API (free, updates every 15 min, geolocated, 65 languages, sentiment included)
- **AI:** Claude API (Haiku 4.5 for cheap tasks, Sonnet 4.5 for complex), OpenAI text-embedding-3-small for embeddings
- **Hosting:** Vercel (frontend), Azure or Railway (backend)

---

## Core Features (MVP - V1)

1. Interactive 3D globe with globe.gl
2. GDELT news data feeding geolocated dots onto the globe
3. Dots cluster when zoomed out, spread apart when zoomed in
4. Click a dot/cluster → card stack of headlines + links to source articles
5. AI-generated summaries for news clusters (free tier feature)
6. 1-2 topic filters (e.g., politics, conflict, tech, climate)
7. Responsive web app (no mobile native yet)

### Skip for MVP:
- User accounts, auth, bookmarks
- Time slider
- All paid AI features
- Mobile apps
- Multiple news sources beyond GDELT

---

## AI Features (Post-MVP, Paid Tier)

All of these are **Pro plan only** ($5-10/mo) except summaries which are free:

1. **RAG-Powered Time Travel** — Users select a region, ask natural language questions scoped to that area and time range. LLM retrieves stored articles via vector search and synthesizes answers with citations.

2. **Sentiment Heatmap Over Time** — Toggle a heatmap layer showing how the "mood" of a region shifted over weeks/months/years. Filterable by topic.

3. **Personalized Daily Globe Briefing** — AI-generated morning briefing based on bookmarked regions. Available as email digest, push notification, or in-app "morning spin."

4. **Cross-Region Connection Detection** — AI identifies related stories across different parts of the globe and visualizes connections as arcs. Tap an arc to see the AI explanation.

5. **Explain Like I Just Arrived (ELIJA)** — Contextual briefing for any region: key players, background, why it matters. Adjustable depth.

6. **Conflict & Crisis Tracker** — Detects escalation patterns via sentiment trends and volume spikes. Creates "situation room" view with running AI-summarized timeline.

7. **Regional Narrative Generator** — Auto-generates "story arcs" for a region, e.g., "The evolution of the housing crisis in London: 2020-2025."

---

## Data Schema (per article)

```json
{
  "id": "uuid",
  "title": "string",
  "summary": "string",
  "source_url": "string",
  "source_name": "string",
  "source_language": "string",
  "published_at": "timestamp",
  "ingested_at": "timestamp",
  "latitude": "float",
  "longitude": "float",
  "country_code": "string",
  "region": "string",
  "topic_tags": ["string"],
  "sentiment_score": "float",
  "entities": {
    "people": ["string"],
    "organizations": ["string"],
    "places": ["string"]
  },
  "embedding": "vector(1536)"
}
```

---

## GDELT Integration Notes

- **Update frequency:** Every 15 minutes
- **Data format:** CSV files, also available via BigQuery and REST APIs
- **DOC 2.0 API:** Search last 3 months of articles by keyword, location, theme, sentiment
- **GEO API:** Geographic tools for investigating media from last 7 days
- **Bulk data:** CSV files updated every 15 min at http://data.gdeltproject.org/gdeltv2/lastupdate.txt
- **What you get:** Title, URL, source, language, tone/sentiment, locations (lat/lng), themes, entities (people, orgs, places), image URLs, CAMEO event codes
- **What you don't get:** Full article text (only metadata + URL)
- **License:** Free, open data, commercial use permitted

---

## Monetization

**Free tier:**
- Browse the globe, read headlines, basic filters
- Limited time range (last 24-48 hours)
- AI-generated news summaries

**Pro tier ($5-10/mo):**
- RAG-powered time travel queries
- Sentiment heatmap over time
- Cross-region connection detection
- Explain Like I Just Arrived briefings
- Conflict & crisis tracker
- Regional narrative generator
- Personalized daily globe briefings
- Custom alerts and bookmarked regions
- Historical time-scrubbing (full archive)
- Advanced topic filters

**Additional revenue:** API access, B2B tier, sponsored spotlights

---

## Post-MVP Roadmap

**V2 — AI Foundation:**
- User accounts and authentication (Supabase Auth)
- Bookmarkable regions with alerts
- RAG-powered time travel
- ELIJA briefings
- Historical time slider

**V3 — Intelligence Layer:**
- Sentiment heatmap over time
- Cross-region connection detection (arcs)
- Conflict & crisis tracker
- Regional narrative generator

**V4 — Personalization & Growth:**
- Personalized daily globe briefings
- Email digests
- Mobile apps (React Native or native)
- API access for developers
- B2B tier

---

## Cost Estimates

| Stage | Monthly Cost | Break-even |
|-------|-------------|------------|
| MVP | ~$16/mo | N/A |
| Early Growth (1K DAU) | ~$420/mo | 42-84 Pro subs |
| Scaling (10K DAU) | ~$1,234/mo | 154 Pro subs |

### Key cost optimization strategies:
- Model routing: Haiku for summaries/sentiment/classification, Sonnet for RAG/narratives
- Batch API (50% off) for non-real-time: embeddings, sentiment, briefings
- Prompt caching (up to 90% savings) for repeated system prompts
- pgvector over dedicated vector DB (saves $50-200/mo)
- GDELT is free forever

---

## Reference Documents

Two detailed planning docs were created during brainstorming:
1. `orbis-product-spec.md` — Full product spec with features, tech stack, monetization, MVP scope
2. `orbis-cost-analysis.md` — Detailed licensing analysis and cost projections across 3 growth scenarios
