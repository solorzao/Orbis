# Orbis — Product Spec

## Vision

Orbis is a spatial intelligence layer on top of world news. Users interact with a beautiful 3D globe to discover, explore, and understand news happening around the world. The globe is the interface — AI is what turns raw news into understanding.

---

## Core Features & UX

### The Globe Interaction

- Spin, zoom, and tap on the globe to explore news by region
- News stories appear as glowing dots or clusters — brighter/larger clusters indicate more activity
- Zoom in and dots spread apart into individual stories; zoom out and they aggregate into heatmap-like regions
- Smooth transition from globe view → country view → city/local view

### News Consumption

- Tapping a cluster expands into a card stack or feed of headlines for that area
- Topic filters (politics, tech, conflict, climate, sports, etc.) that re-color or re-filter the globe in real time
- Time slider to scrub back through the last 24–48 hours and watch news unfold geographically

### Engagement Hooks

- "Breaking" animations — a ripple effect when major news drops somewhere
- Bookmarkable regions — get notified when news spikes in areas you care about
- Share a "globe snapshot" — a specific view/angle with highlighted stories

---

## AI Features

### 1. RAG-Powered Time Travel

Every news article is stored with vector embeddings, geolocation, and timestamps. Users select a region on the globe, open a chat interface, and ask natural language questions scoped to that area and time range.

- **Example query:** "What are the biggest issues that have happened in the last 5 years here?"
- The LLM retrieves relevant stored articles and synthesizes an answer with citations
- Sources are visualized on a mini-timeline so users see which articles informed the answer
- The longer Orbis runs, the smarter it gets — the dataset compounds over time

### 2. Sentiment Heatmap Over Time

Sentiment analysis runs on all stored articles. Users can toggle a heatmap layer showing how the "mood" of a region has shifted over weeks, months, or years.

- Scrub through time and watch regions shift from green to red and back
- Powerful visual storytelling that reveals trends invisible in individual headlines
- Filterable by topic — see sentiment shifts for "economy" vs "politics" vs "climate" independently

### 3. Personalized Daily Globe Briefing

Each morning, AI generates a personalized briefing based on bookmarked regions and interests.

- "Here's what happened overnight in your watched regions"
- Delivered as a summary with links to dive deeper
- Available as an email digest, push notification, or an in-app "morning spin" of the globe that auto-rotates to each region with updates
- Adapts over time based on reading habits and engagement patterns

### 4. Cross-Region Connection Detection

AI identifies when stories in different parts of the globe are related and visualizes these connections as arcs across the globe.

- **Example:** A trade policy in Washington affecting manufacturing in Vietnam; a drought in Brazil impacting coffee prices in Europe
- Makes the interconnectedness of world events tangible and visible
- Users can tap on an arc to see the AI-generated explanation of the connection
- Unique feature — nobody else surfaces global news relationships this way

### 5. Explain Like I Just Arrived

For any region or story cluster, generate a contextual briefing that catches you up on the full picture.

- Who are the key players? What's the background? Why does this matter?
- Like having an AI foreign correspondent who gives you context, not just today's headline
- Adjustable depth — quick summary vs. deep dive
- Includes related historical context from the RAG knowledge base

### 6. Conflict & Crisis Tracker

AI detects escalation patterns — if news sentiment in a region is trending sharply negative or article volume is spiking, it flags a developing situation.

- Automatically creates a "situation room" view for the region
- Running AI-summarized timeline of the developing crisis
- Tracks escalation/de-escalation over time with visual indicators
- Targeted at journalists, researchers, and anyone following geopolitics

### 7. Regional Narrative Generator

Goes beyond single-query RAG to automatically generate "story arcs" for a region.

- **Example:** "The evolution of the housing crisis in London: 2020–2025"
- AI-authored documentary-style briefings with timeline visualization on the globe
- Users can request narratives on specific themes for any region
- Surfaces long-term trends that are hard to spot from daily news consumption

---

## Tech Stack

### Frontend / 3D Globe

| Option | Notes |
|--------|-------|
| **globe.gl** (recommended) | Built on Three.js, designed for data visualization on globes |
| CesiumJS | Heavier, better for photorealistic imagery |
| Mapbox Globe View | Good if satellite imagery is a priority |

- **React / Next.js** for the app shell
- **Tailwind CSS** for styling
- **Framer Motion** for animations and transitions

### News Data Sources

| Source | Pros | Cons |
|--------|------|------|
| **GDELT API** | Free, massive, real-time, 65 languages, geolocated | Raw, requires processing |
| **NewsAPI** | Clean headlines and summaries | Limited free tier |
| **GNews API** | Decent free tier | Smaller coverage |
| **Bing News Search API** | Good coverage | Paid |

Recommendation: Start with GDELT for volume and geolocation, supplement with NewsAPI for cleaner headline data.

### Backend

- **Python FastAPI** — API layer
- **Redis** — caching hot news data (changes every few minutes)
- **PostgreSQL + PostGIS** — storing and querying geolocated news
- **pgvector** — vector embeddings for RAG (keeps everything in one DB)
- **Scheduled jobs** — Azure Functions or cron for news ingestion and geocoding

### AI Layer

- **Claude API** — regional news summaries, narrative generation, Q&A
- **Embedding model** — for vectorizing articles (e.g., Voyage AI, OpenAI embeddings, or open-source)
- **Topic classification** — clustering related stories
- **Sentiment analysis** — color-coding the globe and powering the heatmap

### Hosting

- **Vercel** or **Cloudflare Pages** — frontend
- **Azure** — backend (leveraging existing expertise)
- Serverless-first for early stages

### Data Schema (per article)

```
{
  id: uuid,
  title: string,
  summary: string,
  source_url: string,
  source_name: string,
  source_language: string,
  published_at: timestamp,
  ingested_at: timestamp,
  latitude: float,
  longitude: float,
  country_code: string,
  region: string,
  topic_tags: string[],
  sentiment_score: float,
  entities: {
    people: string[],
    organizations: string[],
    places: string[]
  },
  embedding: vector(1536)
}
```

---

## Monetization

### Freemium Model

**Free tier:**
- Browse the globe, read headlines, basic filters
- Limited time range (last 24–48 hours)
- AI-generated news summaries

**Pro tier ($5–10/mo):**
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

### Additional Revenue Streams

- **API access** — for developers/researchers wanting geolocated news data
- **B2B tier** — newsrooms, analysts, NGOs, and intelligence teams who need global situational awareness
- **Sponsored spotlights** — tastefully done, e.g. "Conflict zone coverage powered by X"

---

## MVP Scope

### V1 — Keep It Tight

1. Interactive 3D globe with globe.gl
2. One news source (GDELT or NewsAPI) feeding geolocated dots
3. Click a dot/cluster → see headlines + links to source articles
4. AI-generated summaries for news clusters
5. One or two topic filters
6. Basic responsive web app (no mobile native yet)

### What to Skip for MVP

- All paid AI features (time travel, sentiment heatmap, cross-region detection, ELIJA, conflict tracker, narratives, daily briefings)
- Time slider
- User accounts and bookmarks
- Mobile apps
- Multiple news sources

### Post-MVP Roadmap

**V2 — AI Foundation:**
- User accounts and authentication
- Bookmarkable regions with alerts
- RAG-powered time travel (first paid feature)
- Explain Like I Just Arrived briefings
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

## Open Questions

- **News source licensing:** What are the terms of use for GDELT and NewsAPI at scale? Any restrictions on storing/re-displaying content?
- **Embedding cost:** At high volume, embedding every article adds up. Evaluate open-source models (e.g., BGE, E5) vs. paid APIs for cost optimization.
- **Globe performance:** How many simultaneous data points can globe.gl handle smoothly before needing LOD (level of detail) optimization?
- **Moderation:** How to handle news from unreliable or state-propaganda sources? Any editorial layer needed?
- **Mobile:** PWA first or go straight to native? globe.gl performance on mobile devices needs testing.