# Agent Article Reading — Design

## Problem
The Orbis agent only has article titles and metadata. When users ask for details, it can't provide deeper context because it never reads the actual article content.

## Solution
Add a `read_article` retrieval tool that scrapes article URLs on demand, extracting text with a multi-strategy cascade and smart truncation.

## Design Decisions
- **Tool-based approach (Option C)**: The planner decides when to invoke `read_article`, fitting the existing tool architecture.
- **Multi-strategy extraction (B+C)**: trafilatura -> BeautifulSoup -> meta description. Results tagged with quality level.
- **Smart truncation (Option C)**: ~500 words, keyword-relevant paragraphs prioritized.
- **24hr Redis cache**: Scraped text cached by URL hash to avoid re-fetching.
- **Second-pass execution**: `read_article` runs after initial retrieval to get URLs from results.

## Pipeline (5 steps)
1. Plan — Haiku picks tools; `read_article` separated if present
2. Retrieve — Run search/graph tools in parallel
3. Read articles — Scrape top URLs from step 2 (skipped if not planned)
4. Build context — Merge retrieval + article text
5. Synthesize — LLM generates answer

## Files
- **New**: `backend/app/services/scraper.py`
- **Modified**: `retrieval.py`, `agent.py`, `requirements.txt`, `AgentPanel.tsx`
