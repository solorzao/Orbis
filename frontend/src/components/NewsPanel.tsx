"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { GlobePoint, PanelFilters } from "@/types/news";
import { getSentimentColor } from "@/lib/clustering";
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

function sentimentLabel(score: number): string {
  if (score >= 0.5) return "Positive";
  if (score >= 0) return "Neutral";
  return "Negative";
}

function ArticleSkeleton({ delay = 0 }: { delay?: number }) {
  return (
    <div
      className="relative overflow-hidden rounded-xl border border-[var(--border-subtle)] p-4"
      style={{ background: "var(--surface-card)", animationDelay: `${delay}ms` }}
    >
      {/* Shimmer overlay */}
      <div
        className="absolute inset-0 -translate-x-full animate-[shimmer_1.8s_ease-in-out_infinite]"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(59, 130, 246, 0.04), transparent)",
          animationDelay: `${delay}ms`,
        }}
      />
      <div className="mb-2.5 flex items-center gap-2">
        <div className="h-2 w-2 rounded-full" style={{ background: "var(--border-subtle)" }} />
        <div className="h-2 w-12 rounded bg-[var(--border-subtle)]" />
        <div className="h-2 w-px bg-[var(--text-muted)]" />
        <div className="h-4 w-14 rounded-full bg-[var(--inset-highlight)]" />
      </div>
      <div className="space-y-2">
        <div className="h-3 w-full rounded bg-[var(--border-subtle)]" />
        <div className="h-3 w-4/5 rounded bg-[var(--border-subtle)]" />
      </div>
      <div className="mt-3 flex items-center justify-between">
        <div className="h-2 w-20 rounded bg-[var(--inset-highlight)]" />
        <div className="h-2 w-10 rounded bg-[var(--inset-highlight)]" />
      </div>
    </div>
  );
}

function LoadingHeader() {
  return (
    <div className="mb-4 flex flex-col items-center gap-3 py-4">
      <div className="relative h-10 w-10">
        <div
          className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-blue-500"
          style={{ animationDuration: "1.2s" }}
        />
        <div
          className="absolute inset-1 animate-spin rounded-full border-2 border-transparent border-b-blue-400/40"
          style={{ animationDuration: "1.8s", animationDirection: "reverse" }}
        />
      </div>
      <p className="text-[10px] font-semibold tracking-widest text-blue-400/70 uppercase">
        Fetching stories
      </p>
    </div>
  );
}

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
  const panelRef = useRef<HTMLDivElement>(null);
  const [selectedTopics, setSelectedTopics] = useState<Set<string>>(
    () => new Set(savedFilters?.topics ?? [])
  );
  const [selectedSentiment, setSelectedSentiment] = useState<string | null>(
    savedFilters?.sentiment ?? null
  );
  const [searchQuery, setSearchQuery] = useState(savedFilters?.search ?? "");
  const [filterSummary, setFilterSummary] = useState<string | null>(savedFilterSummary ?? null);
  const [filterSummaryLoading, setFilterSummaryLoading] = useState(false);

  // Save filter state to parent on minimize/close so it persists
  const saveFilters = useCallback(() => {
    onFiltersChange?.(
      { topics: Array.from(selectedTopics), sentiment: selectedSentiment, search: searchQuery },
      filterSummary,
    );
  }, [onFiltersChange, selectedTopics, selectedSentiment, searchQuery, filterSummary]);

  // Clear filter summary when filters change
  useEffect(() => {
    setFilterSummary(null);
  }, [selectedTopics, selectedSentiment, searchQuery]);

  const availableTopics = useMemo(() => {
    if (!point) return [];
    const tags = new Set<string>();
    point.articles.forEach((a) => a.topicTags.forEach((t) => tags.add(t)));
    return Array.from(tags).sort();
  }, [point?.articles]);

  const filteredArticles = useMemo(() => {
    if (!point) return [];
    let result = point.articles;
    if (selectedTopics.size > 0) {
      result = result.filter((a) =>
        a.topicTags.some((t) => selectedTopics.has(t))
      );
    }
    if (selectedSentiment) {
      result = result.filter((a) => {
        if (selectedSentiment === "positive") return a.sentimentScore >= 0.5;
        if (selectedSentiment === "neutral") return a.sentimentScore >= 0 && a.sentimentScore < 0.5;
        return a.sentimentScore < 0; // negative
      });
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter((a) => a.title.toLowerCase().includes(q));
    }
    return result;
  }, [point?.articles, selectedTopics, selectedSentiment, searchQuery]);

  const hasActiveFilters = selectedTopics.size > 0 || selectedSentiment !== null || searchQuery.trim() !== "";

  const MAX_SUMMARIZE = 10;
  const canSummarize = hasActiveFilters && filteredArticles.length >= 2;

  const handleSummarize = useCallback(async () => {
    if (!canSummarize || filterSummaryLoading) return;
    setFilterSummaryLoading(true);
    try {
      const headlines = filteredArticles.slice(0, MAX_SUMMARIZE).map((a) => `${a.title} (${a.sourceName})`);
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

  // Click outside to minimize (or close if no minimize handler)
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        handleMinimize();
      }
    }
    if (point) {
      // Delay adding listener to avoid immediate trigger
      const timer = setTimeout(() => {
        document.addEventListener("mousedown", handleClickOutside);
      }, 100);
      return () => {
        clearTimeout(timer);
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [point, handleMinimize]);

  // ESC key to minimize (or close if no minimize handler)
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        handleMinimize();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleMinimize]);

  return (
    <AnimatePresence>
      {point && (
        <motion.div
          ref={panelRef}
          data-testid="news-panel"
          initial={{ x: "100%", opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: "100%", opacity: 0 }}
          transition={{ type: "spring", damping: 28, stiffness: 300 }}
          className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col"
          style={{
            background: "var(--surface-panel)",
            backdropFilter: "blur(24px) saturate(1.4)",
            borderLeft: "1px solid var(--border-accent)",
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-6 py-4">
            <div>
              <h2 className="text-sm font-semibold tracking-widest text-blue-400 uppercase">
                {point.isCluster
                  ? hasActiveFilters
                    ? `${filteredArticles.length} of ${point.count} Stories`
                    : `${point.count} Stories`
                  : point.articles[0]?.countryCode}
              </h2>
              <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                {point.locationName || `${point.lat.toFixed(2)}°, ${point.lng.toFixed(2)}°`}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {onMinimize && (
                <button
                  onClick={handleMinimize}
                  className="group flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] transition-colors hover:border-blue-500/30 hover:text-[var(--text-secondary)]"
                  aria-label="Minimize panel"
                >
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path
                      d="M3 7H11"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              )}
              <button
                onClick={onClose}
                className="group flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] transition-colors hover:border-blue-500/30 hover:text-[var(--text-secondary)]"
                aria-label="Close panel"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                  className="transition-transform group-hover:scale-110"
                >
                  <path
                    d="M1 1L13 13M13 1L1 13"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          </div>

          {/* Cards */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {/* AI Briefing */}
            {summaryLoading && (
              <div className="mb-4 rounded-xl border border-blue-500/10 bg-blue-500/[0.03] p-4">
                <div className="mb-2.5 flex items-center gap-1.5">
                  <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-blue-500/30" />
                  <div className="h-2 w-16 animate-pulse rounded bg-blue-500/20" />
                </div>
                <div className="space-y-2">
                  <div className="h-2 w-full animate-pulse rounded bg-[var(--inset-highlight)]" />
                  <div className="h-2 w-4/5 animate-pulse rounded bg-[var(--inset-highlight)]" />
                  <div className="h-2 w-3/5 animate-pulse rounded bg-[var(--inset-highlight)]" />
                </div>
              </div>
            )}
            {clusterSummary && !summaryLoading && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }}
                className="mb-4 rounded-xl border border-blue-500/10 bg-blue-500/[0.04] p-4"
              >
                <div className="mb-2 flex items-center gap-1.5">
                  <svg width="12" height="12" viewBox="0 0 10 10" fill="none">
                    <circle cx="5" cy="5" r="4" stroke="#3B82F6" strokeWidth="1" />
                    <circle cx="5" cy="5" r="1.5" fill="#3B82F6" />
                  </svg>
                  <span className="text-[10px] font-semibold tracking-widest text-blue-400 uppercase">
                    AI Briefing
                  </span>
                </div>
                <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
                  {clusterSummary}
                </p>
              </motion.div>
            )}

            {/* In-panel filters */}
            {point.articles.length > 0 && (
              <div className="mb-3 space-y-2">
                <div className="relative">
                  {/* Sentiment dots — pinned top-right, always on first line */}
                  <div className="absolute right-0 top-0 flex items-center gap-1.5">
                    <span className="text-[var(--text-muted)]">|</span>
                    {[
                      { key: "positive", color: "#10B981", title: "Positive" },
                      { key: "neutral", color: "#F59E0B", title: "Neutral" },
                      { key: "negative", color: "#EF4444", title: "Negative" },
                    ].map(({ key, color, title }) => (
                      <button
                        key={key}
                        onClick={() => setSelectedSentiment((prev) => (prev === key ? null : key))}
                        title={title}
                        className={`flex h-5 w-5 items-center justify-center rounded-full transition-all ${
                          selectedSentiment === key
                            ? ""
                            : "opacity-50 hover:opacity-80"
                        }`}
                        style={{
                          ...(selectedSentiment === key ? { boxShadow: `0 0 0 1px transparent, 0 0 0 3px ${color}` } : {}),
                        }}
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full"
                          style={{ backgroundColor: color }}
                        />
                      </button>
                    ))}
                  </div>

                  {/* Topic pills — wrap freely, with right padding to avoid sentiment dots */}
                  <div className="flex flex-wrap items-center gap-1.5 pr-24">
                    <button
                      onClick={() => { setSelectedTopics(new Set()); setSelectedSentiment(null); setSearchQuery(""); }}
                      className={`rounded-full px-2.5 py-1 text-[10px] font-medium tracking-wide transition-colors ${
                        !hasActiveFilters
                          ? "bg-blue-500/20 text-blue-400"
                          : "bg-[var(--inset-highlight)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                      }`}
                    >
                      All
                    </button>
                    {availableTopics.map((topic) => (
                      <button
                        key={topic}
                        onClick={() => {
                          setSelectedTopics((prev) => {
                            const next = new Set(prev);
                            if (next.has(topic)) next.delete(topic);
                            else next.add(topic);
                            return next;
                          });
                        }}
                        className={`rounded-full px-2.5 py-1 text-[10px] font-medium tracking-wide transition-colors ${
                          selectedTopics.has(topic)
                            ? "bg-blue-500/20 text-blue-400"
                            : "bg-[var(--inset-highlight)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                        }`}
                      >
                        {topic}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Title search */}
                <div className="relative">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search headlines..."
                    className="h-7 w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--inset-highlight)] pl-7 pr-3 text-[11px] text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none transition-colors focus:border-blue-500/30"
                  />
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 10 10"
                    fill="none"
                    className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
                  >
                    <circle cx="4.5" cy="4.5" r="3" stroke="currentColor" strokeWidth="1.2" />
                    <path d="M7 7L9 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                  </svg>
                </div>
              </div>
            )}

            {/* Filter summary */}
            {filterSummaryLoading && (
              <div className="mb-3 rounded-xl border border-purple-500/10 bg-purple-500/[0.03] p-4">
                <div className="mb-2.5 flex items-center gap-1.5">
                  <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-purple-500/30" />
                  <div className="h-2 w-24 animate-pulse rounded bg-purple-500/20" />
                </div>
                <div className="space-y-2">
                  <div className="h-2 w-full animate-pulse rounded bg-[var(--inset-highlight)]" />
                  <div className="h-2 w-4/5 animate-pulse rounded bg-[var(--inset-highlight)]" />
                </div>
              </div>
            )}
            {filterSummary && !filterSummaryLoading && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }}
                className="mb-3 rounded-xl border border-purple-500/10 bg-purple-500/[0.04] p-4"
              >
                <div className="mb-2 flex items-center gap-1.5">
                  <svg width="12" height="12" viewBox="0 0 10 10" fill="none">
                    <circle cx="5" cy="5" r="4" stroke="#A855F7" strokeWidth="1" />
                    <circle cx="5" cy="5" r="1.5" fill="#A855F7" />
                  </svg>
                  <span className="text-[10px] font-semibold tracking-widest text-purple-400 uppercase">
                    Filtered Summary
                  </span>
                  <span className="text-[9px] text-[var(--text-muted)]">
                    ({Math.min(filteredArticles.length, MAX_SUMMARIZE)} stories)
                  </span>
                </div>
                <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
                  {filterSummary}
                </p>
              </motion.div>
            )}

            {/* Summarize button */}
            {canSummarize && !filterSummary && !filterSummaryLoading && (
              <button
                onClick={handleSummarize}
                className="mb-3 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-purple-500/20 py-2.5 text-[11px] font-medium text-purple-400 transition-colors hover:border-purple-500/40 hover:bg-purple-500/[0.04]"
              >
                <svg width="12" height="12" viewBox="0 0 10 10" fill="none">
                  <circle cx="5" cy="5" r="4" stroke="currentColor" strokeWidth="1" />
                  <circle cx="5" cy="5" r="1.5" fill="currentColor" />
                </svg>
                Summarize
              </button>
            )}

            <div className="space-y-3">
              {articlesLoading && point.articles.length === 0 && (
                <>
                  <LoadingHeader />
                  {Array.from({ length: 3 }).map((_, i) => (
                    <ArticleSkeleton key={`skel-${i}`} delay={i * 150} />
                  ))}
                </>
              )}
              {!articlesLoading && point.articles.length === 0 && (
                <div
                  className="rounded-xl border border-[var(--border-subtle)] p-6 text-center"
                  style={{ background: "var(--surface-card)" }}
                >
                  <p className="text-sm text-[var(--text-muted)]">
                    No stories found for this topic in this area.
                  </p>
                </div>
              )}
              <AnimatePresence>
                {filteredArticles.map((article, index) => (
                  <motion.article
                    key={article.id}
                    initial={{ opacity: 0, y: 20, scale: 0.97 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -10, scale: 0.97 }}
                    transition={{
                      delay: index * 0.06,
                      duration: 0.35,
                      ease: [0.23, 1, 0.32, 1],
                    }}
                    className="group relative rounded-xl border border-[var(--border-subtle)] p-4 transition-colors hover:border-blue-500/20"
                    style={{
                      background: "var(--surface-card)",
                    }}
                  >
                    {/* Sentiment + Topic Tags */}
                    <div className="mb-2.5 flex items-center gap-2">
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{
                          backgroundColor: getSentimentColor(article.sentimentScore),
                          boxShadow: `0 0 6px ${getSentimentColor(article.sentimentScore)}60`,
                        }}
                        title={sentimentLabel(article.sentimentScore)}
                      />
                      <span
                        className="text-[10px] font-medium uppercase tracking-wider"
                        style={{
                          color: getSentimentColor(article.sentimentScore),
                        }}
                      >
                        {sentimentLabel(article.sentimentScore)}
                      </span>
                      <span className="text-[var(--text-muted)]">|</span>
                      {article.topicTags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-full bg-[var(--inset-highlight)] px-2 py-0.5 text-[10px] font-medium tracking-wide text-[var(--text-secondary)]"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>

                    {/* Title */}
                    <h3 className="text-[15px] leading-snug font-medium text-[var(--text-primary)] transition-colors">
                      {article.title}
                    </h3>

                    {/* Source + Time */}
                    <div className="mt-3 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-[var(--text-muted)]">
                          {article.sourceName}
                        </span>
                        <span className="text-[var(--text-muted)]">&middot;</span>
                        <span className="text-xs text-[var(--text-muted)]">
                          {timeAgo(article.publishedAt)}
                        </span>
                      </div>
                      <a
                        href={article.sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-xs text-blue-500/70 transition-colors hover:text-blue-400"
                      >
                        Read
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                          <path
                            d="M3 7L7 3M7 3H4M7 3V6"
                            stroke="currentColor"
                            strokeWidth="1.2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </a>
                    </div>
                  </motion.article>
                ))}
              </AnimatePresence>
              {hasActiveFilters && filteredArticles.length === 0 && point.articles.length > 0 && (
                <div className="rounded-xl border border-[var(--border-subtle)] p-4 text-center" style={{ background: "var(--surface-card)" }}>
                  <p className="text-sm text-[var(--text-muted)]">No stories match the selected filters.</p>
                </div>
              )}
              {/* Show more button — visible as long as there are unloaded articles */}
              {!articlesLoading && point.articles.length > 0 &&
                point.articles.length < point.count && (
                <div className="mt-3 flex justify-center">
                  <button
                    onClick={() => onLoadMore?.(
                      hasActiveFilters
                        ? { topics: Array.from(selectedTopics), sentiment: selectedSentiment, search: searchQuery }
                        : undefined
                    )}
                    disabled={loadingMore}
                    className="flex items-center gap-2 rounded-full border border-[var(--border-subtle)] px-4 py-2 text-xs font-medium text-blue-400 transition-colors hover:border-blue-500/30 hover:bg-blue-500/5 disabled:opacity-50"
                  >
                    {loadingMore ? (
                      <>
                        <span className="h-3 w-3 animate-spin rounded-full border border-blue-400/30 border-t-blue-400" />
                        Loading...
                      </>
                    ) : hasActiveFilters ? (
                      "Load more stories"
                    ) : (
                      `Show more (${point.count - point.articles.length} remaining)`
                    )}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Bottom fade */}
          <div
            className="pointer-events-none h-12 w-full"
            style={{
              background: "linear-gradient(to top, var(--surface-panel), transparent)",
            }}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
