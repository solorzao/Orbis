"use client";

import { useEffect, useState } from "react";
import {
  SEARCH_DEBOUNCE_MS,
  SEARCH_MIN,
  fetchSearch,
  searchQuery,
  toSearchResults,
  type SearchResults,
} from "@/lib/entities";

/**
 * People, organisations and threads for what the Track search holds, from
 * /api/search once typing pauses (SEARCH_DEBOUNCE_MS). A new query aborts the
 * last request and its late answer is ignored; only the current query's
 * results are returned (none while they load). Under two characters, nothing
 * is asked: the places, searched on the page, are all there is.
 */
export function useTrackSearch(query: string): {
  results: SearchResults | null;
  loading: boolean;
  error: boolean;
} {
  const q = searchQuery(query);
  const asks = q.length >= SEARCH_MIN;
  const [answer, setAnswer] = useState<{
    q: string;
    results: SearchResults | null;
    error: boolean;
  } | null>(null);

  useEffect(() => {
    if (!asks) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchSearch(q, controller.signal)
        .then((api) => {
          if (!controller.signal.aborted) {
            setAnswer({ q, results: toSearchResults(api), error: false });
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) setAnswer({ q, results: null, error: true });
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q, asks]);

  if (!asks) return { results: null, loading: false, error: false };
  if (answer?.q !== q) return { results: null, loading: true, error: false };
  return { results: answer.results, loading: false, error: answer.error };
}
