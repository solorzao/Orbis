"use client";

import { isWebUrl } from "@/hooks/useAgent";
import type { ThreadArticle } from "@/lib/threads";
import { timeAgo } from "@/lib/timeAgo";

interface ThreadStoriesProps {
  title: string;
  /** Every story in the thread. */
  total: number;
  /** The stories loaded so far, newest first. */
  articles: readonly ThreadArticle[];
  /** The first page is on its way. */
  loading: boolean;
  loadingMore: boolean;
  /** The last page was full: more may follow. */
  hasMore: boolean;
  onLoadMore: () => void;
  onClose: () => void;
}

/**
 * A thread's stories in the Inspect tab ("All {n} stories"), as a place's
 * are listed (NewsPanel's .insp and .art): each headline links to its story
 * (a web URL only: anything else shows as plain text), with its outlet, age
 * and place, 20 at a time.
 */
export default function ThreadStories({
  title,
  total,
  articles,
  loading,
  loadingMore,
  hasMore,
  onLoadMore,
  onClose,
}: ThreadStoriesProps) {
  return (
    <div
      data-testid="thread-stories"
      className="insp"
      aria-busy={loading || undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="insp-head">
        <div className="min-w-0">
          <h2 className="insp-title">{title}</h2>
          <p className="insp-count">
            {total} {total === 1 ? "story" : "stories"} in this thread
          </p>
        </div>
        <div className="end">
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

      <div className="scrim insp-list">
        {loading && articles.length === 0 && <p className="insp-status">Fetching stories…</p>}
        {articles.map((a, i) => (
          <article key={`${i}:${a.sourceUrl}`} className="art">
            {isWebUrl(a.sourceUrl) ? (
              <a className="h" href={a.sourceUrl} target="_blank" rel="noopener noreferrer">
                {a.title}
              </a>
            ) : (
              <span className="h">{a.title}</span>
            )}
            <div className="m">
              <span>{a.sourceName}</span>
              <span suppressHydrationWarning>{timeAgo(a.publishedAt)}</span>
              {a.place && <span>{a.place}</span>}
            </div>
          </article>
        ))}
      </div>

      {hasMore && articles.length > 0 && (
        <div className="insp-more">
          <button type="button" className="pill" disabled={loadingMore} onClick={onLoadMore}>
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
