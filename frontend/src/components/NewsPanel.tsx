"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { GlobePoint } from "@/types/news";
import { getSentimentColor } from "@/lib/clustering";

interface NewsPanelProps {
  point: GlobePoint | null;
  onClose: () => void;
  onMinimize?: () => void;
  clusterSummary?: string | null;
  summaryLoading?: boolean;
  articlesLoading?: boolean;
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
  if (score >= -0.5) return "Negative";
  return "Critical";
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
  clusterSummary,
  summaryLoading,
  articlesLoading,
}: NewsPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Click outside to minimize (or close if no minimize handler)
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        if (onMinimize) onMinimize();
        else onClose();
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
  }, [point, onClose, onMinimize]);

  // ESC key to minimize (or close if no minimize handler)
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (onMinimize) onMinimize();
        else onClose();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose, onMinimize]);

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
                {point.isCluster ? `${point.count} Stories` : point.articles[0]?.countryCode}
              </h2>
              <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                {point.locationName || `${point.lat.toFixed(2)}°, ${point.lng.toFixed(2)}°`}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {onMinimize && (
                <button
                  onClick={onMinimize}
                  className="group flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border-subtle)] text-[var(--text-muted)] transition-colors hover:border-blue-500/30 hover:text-[var(--text-secondary)]"
                  aria-label="Minimize panel"
                >
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M3 7H11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
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
                <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{clusterSummary}</p>
              </motion.div>
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
                <div className="rounded-xl border border-[var(--border-subtle)] p-6 text-center" style={{ background: "var(--surface-card)" }}>
                  <p className="text-sm text-[var(--text-muted)]">No stories found for this topic in this area.</p>
                </div>
              )}
              <AnimatePresence mode="popLayout">
                {point.articles.map((article, index) => (
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

                    {/* AI Summary */}
                    {article.summary && (
                      <div className="mt-2.5 rounded-lg border border-blue-500/10 bg-blue-500/[0.04] px-3 py-2">
                        <div className="mb-1 flex items-center gap-1.5">
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                            <circle cx="5" cy="5" r="4" stroke="#3B82F6" strokeWidth="1" />
                            <circle cx="5" cy="5" r="1.5" fill="#3B82F6" />
                          </svg>
                          <span className="text-[9px] font-semibold tracking-widest text-blue-400 uppercase">
                            AI Summary
                          </span>
                        </div>
                        <p className="text-xs leading-relaxed text-[var(--text-secondary)]">{article.summary}</p>
                      </div>
                    )}

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
