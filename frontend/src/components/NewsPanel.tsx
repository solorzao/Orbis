"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { GlobePoint, PanelFilters } from "@/types/news";
import { formatScore, sentimentBucket, sentimentKey } from "@/lib/clustering";
import { fetchSelectionSummary } from "@/lib/api";

interface NewsPanelProps {
  point: GlobePoint | null;
  onClose: () => void;
  onMinimize?: () => void;
  onLoadMore?: (filters?: PanelFilters) => void;
  loadingMore?: boolean;
  clusterSummary?: string | null;
  summaryLoading?: boolean;
  articlesLoading?: boolean;
  savedFilters?: PanelFilters;
  savedFilterSummary?: string | null;
  onFiltersChange?: (filters: PanelFilters, filterSummary: string | null) => void;
}

/** The tone filters, on tokens.md's sentiment bins (see sentimentBucket). */
const TONES = [
  { key: "positive", label: "Positive", token: "p3" },
  { key: "neutral", label: "Neutral", token: "neutral" },
  { key: "negative", label: "Negative", token: "n3" },
] as const;

const MAX_SUMMARIZE = 10;

/** Topics with a --topic-* token; any other tag gets the neutral "All" colour. */
const TOPIC_TOKENS = new Set([
  "politics",
  "conflict",
  "technology",
  "climate",
  "economy",
  "health",
]);

function topicColor(tag: string): string {
  const key = tag.toLowerCase();
  return TOPIC_TOKENS.has(key) ? `var(--topic-${key})` : "var(--topic-all)";
}

function timeAgo(dateString: string): string {
  const now = new Date();
  const date = new Date(dateString);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const stories = (n: number) => `${n} ${n === 1 ? "story" : "stories"}`;

function AiSkeleton() {
  return (
    <div className="scrim insp-ai" aria-hidden="true">
      <span className="skel" />
      <span className="skel" />
      <span className="skel short" />
    </div>
  );
}

/**
 * A place's stories in the side panel's Stories tab (mockup `.insp`, `.art`):
 * the AI summary on a scrim, filter pills, and one row per story with its
 * signed tone. Minimize keeps the place in Recent places; close drops it.
 */
export default function NewsPanel({
  point,
  onClose,
  onMinimize,
  onLoadMore,
  loadingMore,
  clusterSummary,
  summaryLoading,
  articlesLoading,
  savedFilters,
  savedFilterSummary,
  onFiltersChange,
}: NewsPanelProps) {
  const [selectedTopics, setSelectedTopics] = useState<Set<string>>(
    () => new Set(savedFilters?.topics ?? []),
  );
  const [selectedSentiment, setSelectedSentiment] = useState<string | null>(
    savedFilters?.sentiment ?? null,
  );
  const [searchQuery, setSearchQuery] = useState(savedFilters?.search ?? "");
  const [filterSummary, setFilterSummary] = useState<string | null>(savedFilterSummary ?? null);
  const [filterSummaryLoading, setFilterSummaryLoading] = useState(false);

  // Save filter state to the parent so it persists for this place
  const saveFilters = useCallback(() => {
    onFiltersChange?.(
      { topics: Array.from(selectedTopics), sentiment: selectedSentiment, search: searchQuery },
      filterSummary,
    );
  }, [onFiltersChange, selectedTopics, selectedSentiment, searchQuery, filterSummary]);

  // ...including when another place replaces this one (it unmounts)
  const saveRef = useRef(saveFilters);
  useEffect(() => {
    saveRef.current = saveFilters;
  }, [saveFilters]);
  useEffect(() => () => saveRef.current(), []);

  // Clear filter summary when filters change (skip initial mount to preserve restored state)
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    setFilterSummary(null);
  }, [selectedTopics, selectedSentiment, searchQuery]);

  const articles = point?.articles;

  const availableTopics = useMemo(() => {
    const tags = new Set<string>();
    articles?.forEach((a) => a.topicTags.forEach((t) => tags.add(t)));
    return Array.from(tags).sort();
  }, [articles]);

  const filteredArticles = useMemo(() => {
    let result = articles ?? [];
    if (selectedTopics.size > 0) {
      result = result.filter((a) => a.topicTags.some((t) => selectedTopics.has(t)));
    }
    if (selectedSentiment) {
      result = result.filter((a) => sentimentBucket(a.sentimentScore) === selectedSentiment);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter((a) => a.title.toLowerCase().includes(q));
    }
    return result;
  }, [articles, selectedTopics, selectedSentiment, searchQuery]);

  const hasActiveFilters =
    selectedTopics.size > 0 || selectedSentiment !== null || searchQuery.trim() !== "";

  const canSummarize = hasActiveFilters && filteredArticles.length >= 2;

  const handleSummarize = useCallback(async () => {
    if (!canSummarize || filterSummaryLoading) return;
    setFilterSummaryLoading(true);
    try {
      const headlines = filteredArticles
        .slice(0, MAX_SUMMARIZE)
        .map((a) => `${a.title} (${a.sourceName})`);
      const result = await fetchSelectionSummary(headlines, point?.locationName);
      setFilterSummary(result.summary);
    } catch {
      setFilterSummary("Summary generation failed.");
    } finally {
      setFilterSummaryLoading(false);
    }
  }, [canSummarize, filterSummaryLoading, filteredArticles, point?.locationName]);

  const handleMinimize = useCallback(() => {
    saveFilters();
    if (onMinimize) onMinimize();
    else onClose();
  }, [saveFilters, onMinimize, onClose]);

  const clearFilters = () => {
    setSelectedTopics(new Set());
    setSelectedSentiment(null);
    setSearchQuery("");
  };

  const toggleTopic = (topic: string) =>
    setSelectedTopics((prev) => {
      const next = new Set(prev);
      if (next.has(topic)) next.delete(topic);
      else next.add(topic);
      return next;
    });

  if (!point) return null;

  const place = point.locationName || `${point.lat.toFixed(2)}°, ${point.lng.toFixed(2)}°`;
  const count = hasActiveFilters
    ? `${filteredArticles.length} of ${stories(point.count)}`
    : stories(point.count);
  const remaining = point.count - point.articles.length;
  const showLoadMore = !articlesLoading && point.articles.length > 0 && remaining > 0;

  return (
    <div
      data-testid="news-panel"
      className="insp"
      aria-busy={articlesLoading || undefined}
      // Escape inside the panel minimizes it (the globe and co-pilot keep their own keys)
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          handleMinimize();
        }
      }}
    >
      <div className="insp-head">
        <div className="min-w-0">
          <h2 className="insp-title">{place}</h2>
          <p className="insp-count">{count}</p>
        </div>
        <div className="end">
          {onMinimize && (
            <button
              type="button"
              className="iconbtn"
              aria-label="Minimize panel"
              title="Keep in recent places"
              onClick={handleMinimize}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                <path d="M2.5 6h7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </button>
          )}
          <button type="button" className="iconbtn" aria-label="Close panel" onClick={onClose}>
            <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
              <path
                d="M2 2l8 8M10 2l-8 8"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>

      {summaryLoading && <AiSkeleton />}
      {clusterSummary && !summaryLoading && (
        <div className="scrim insp-ai">
          <p>
            <span className="ai">AI</span>
            {clusterSummary}
          </p>
        </div>
      )}

      {point.articles.length > 0 && (
        <div className="insp-filters">
          <div className="chips" role="group" aria-label="Filter stories">
            <button
              type="button"
              className="pill"
              aria-pressed={!hasActiveFilters}
              onClick={clearFilters}
            >
              All
            </button>
            {availableTopics.map((topic) => (
              <button
                key={topic}
                type="button"
                className="pill"
                aria-pressed={selectedTopics.has(topic)}
                onClick={() => toggleTopic(topic)}
              >
                {topic}
              </button>
            ))}
            {TONES.map(({ key, label, token }) => (
              <button
                key={key}
                type="button"
                className="pill"
                aria-pressed={selectedSentiment === key}
                onClick={() => setSelectedSentiment((prev) => (prev === key ? null : key))}
              >
                <span
                  className="dot"
                  aria-hidden="true"
                  style={{ "--c": `var(--sentiment-${token})` } as CSSProperties}
                />
                {label}
              </button>
            ))}
          </div>
          <label className="insp-search">
            <svg width="12" height="12" viewBox="0 0 10 10" fill="none" aria-hidden="true">
              <circle cx="4.5" cy="4.5" r="3" stroke="currentColor" strokeWidth="1.2" />
              <path d="M7 7L9 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search headlines"
              aria-label="Search headlines"
            />
          </label>
        </div>
      )}

      {filterSummaryLoading && <AiSkeleton />}
      {filterSummary && !filterSummaryLoading && (
        <div className="scrim insp-ai">
          <p className="lbl">
            <span>Selection</span>
            <span>{stories(Math.min(filteredArticles.length, MAX_SUMMARIZE))}</span>
          </p>
          <p>
            <span className="ai">AI</span>
            {filterSummary}
          </p>
        </div>
      )}
      {canSummarize && !filterSummary && !filterSummaryLoading && (
        <div>
          <button type="button" className="pill" onClick={handleSummarize}>
            <span className="ai">AI</span>
            Summarize selection
          </button>
        </div>
      )}

      <div className="scrim insp-list">
        {articlesLoading && point.articles.length === 0 && (
          <>
            <p className="insp-status">Fetching stories…</p>
            {[0, 1, 2].map((i) => (
              <div key={i} className="art" aria-hidden="true">
                <span className="skel" />
                <span className="skel short" />
              </div>
            ))}
          </>
        )}
        {!articlesLoading && point.articles.length === 0 && (
          <p className="insp-status">No stories found for this topic in this area.</p>
        )}
        {filteredArticles.map((article) => (
          <article key={article.id} className="art">
            <a className="h" href={article.sourceUrl} target="_blank" rel="noopener noreferrer">
              {article.title}
            </a>
            <div className="m">
              <span>{article.sourceName}</span>
              <span suppressHydrationWarning>{timeAgo(article.publishedAt)}</span>
              {article.topicTags.map((tag) => (
                <span
                  key={tag}
                  className="art-tag"
                  style={{ "--c": topicColor(tag) } as CSSProperties}
                >
                  {tag}
                </span>
              ))}
              <span
                className="sent"
                style={
                  {
                    "--sc": `var(--sentiment-${sentimentKey(article.sentimentScore)})`,
                  } as CSSProperties
                }
              >
                <span className="sr-only">Tone </span>
                {formatScore(article.sentimentScore)}
              </span>
            </div>
          </article>
        ))}
        {hasActiveFilters && filteredArticles.length === 0 && point.articles.length > 0 && (
          <p className="insp-status">No stories match the selected filters.</p>
        )}
      </div>

      {showLoadMore && (
        <div className="insp-more">
          <button
            type="button"
            className="pill"
            disabled={loadingMore}
            onClick={() =>
              onLoadMore?.(
                hasActiveFilters
                  ? {
                      topics: Array.from(selectedTopics),
                      sentiment: selectedSentiment,
                      search: searchQuery,
                    }
                  : undefined,
              )
            }
          >
            {loadingMore ? "Loading…" : "Load more"}
            {!loadingMore && !hasActiveFilters && <span className="num">{remaining} more</span>}
          </button>
        </div>
      )}
    </div>
  );
}
