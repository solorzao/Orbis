"use client";

import { useEffect, useState } from "react";
import { fetchRelations, retryOnce503 } from "@/lib/api";
import {
  RELATIONS_LIMIT,
  toRelations,
  type Relation,
  type RelationKind,
  type RelationLens,
} from "@/lib/relations";
import { FETCH_DEBOUNCE_MS } from "@/hooks/useGlobePoints";

/** How often an open layer asks again: the API's lens refreshes hourly (wk:*). */
export const REFRESH_MS = 30 * 60_000;

const NO_RELATIONS: Relation[] = [];

interface Result {
  kind: RelationKind;
  /** The refresh it answers. */
  tick: number;
  relations: Relation[];
  lens: RelationLens | null;
  error: boolean;
}

/**
 * The Relations layer's arcs, fetched only while the layer is on and
 * available (`enabled`: false under a range or a replay). The lens is the
 * last 7 UTC days whatever the timeline shows, so only the class switch
 * (`kind`) refetches; while on, it asks again every 30 minutes. It follows
 * useLinks: a new class cancels the last request and ignores its answer if
 * it comes anyway, the last arcs stay up while the next load, a 503 is asked
 * once more, and off forgets the answer.
 */
export function useRelations(
  kind: RelationKind,
  enabled: boolean,
): { relations: Relation[]; lens: RelationLens | null; loading: boolean; error: boolean } {
  const [result, setResult] = useState<Result | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const timer = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(timer);
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      retryOnce503(
        () => fetchRelations({ kind, limit: RELATIONS_LIMIT, signal: controller.signal }),
        controller.signal,
      )
        .then((api) => {
          if (controller.signal.aborted) return;
          const { relations, ...lens } = toRelations(api);
          setResult({ kind, tick, relations, lens, error: false });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setResult({ kind, tick, relations: NO_RELATIONS, lens: null, error: true });
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, kind, tick]);

  // Off forgets the last answer: turned on again, an old error must not be
  // shown (and announced) before the new request answers.
  if (!enabled && result !== null) setResult(null);
  if (!enabled) return { relations: NO_RELATIONS, lens: null, loading: false, error: false };
  const current = result !== null && result.kind === kind && result.tick === tick;
  return {
    relations: result?.relations ?? NO_RELATIONS,
    lens: result?.lens ?? null,
    error: result?.error ?? false,
    loading: !current,
  };
}
