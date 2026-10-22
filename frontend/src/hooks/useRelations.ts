"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchRelations, retryOnce503 } from "@/lib/api";
import {
  RELATIONS_LIMIT,
  patchRelations,
  toRelations,
  type Relation,
  type RelationDetail,
  type RelationKind,
  type RelationLens,
} from "@/lib/relations";
import { FETCH_DEBOUNCE_MS } from "@/hooks/useGlobePoints";

/**
 * How often an open layer asks again. The API's relations caches refresh each
 * ingestion cycle (db:*), so meanwhile the list and an opened pair's detail can
 * differ: `patch` makes that pair's arc agree with its inspector.
 */
export const REFRESH_MS = 30 * 60_000;

const NO_RELATIONS: Relation[] = [];

interface Result {
  kind: RelationKind;
  /** The refresh it answers. */
  tick: number;
  relations: Relation[];
  lens: RelationLens | null;
  error: boolean;
  /** Which answer fetched this is, from 1 (0 for an error): a patch keeps it. */
  answer: number;
}

/**
 * The Relations layer's arcs, fetched only while the layer is on and
 * available (`enabled`: false under a range or a replay). The lens is the
 * last 7 UTC days whatever the timeline shows, so only the class switch
 * (`kind`) refetches; while on, it asks again every 30 minutes. It follows
 * useLinks: a new class cancels the last request and ignores its answer if
 * it comes anyway, the last arcs stay up while the next load, a 503 is asked
 * once more, and off forgets the answer. `patch` puts a pair's detail into
 * the answer up, when it is every class's over the same days (patchRelations);
 * `answer` changes with each answer fetched, not with a patch (0: none).
 */
export function useRelations(
  kind: RelationKind,
  enabled: boolean,
): {
  relations: Relation[];
  lens: RelationLens | null;
  loading: boolean;
  error: boolean;
  answer: number;
  patch: (detail: RelationDetail) => void;
} {
  const [result, setResult] = useState<Result | null>(null);
  const [tick, setTick] = useState(0);
  const answers = useRef(0);

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
          answers.current += 1;
          setResult({ kind, tick, relations, lens, error: false, answer: answers.current });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setResult({ kind, tick, relations: NO_RELATIONS, lens: null, error: true, answer: 0 });
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, kind, tick]);

  // Checked against the answer up (its class and days), not the switch: the
  // last arcs stay drawn while another class loads.
  const patch = useCallback((detail: RelationDetail) => {
    setResult((r) => {
      if (r === null) return r;
      const relations = patchRelations(r.relations, detail, r);
      return relations === r.relations ? r : { ...r, relations };
    });
  }, []);

  // Off forgets the last answer: turned on again, an old error must not be
  // shown (and announced) before the new request answers.
  if (!enabled && result !== null) setResult(null);
  if (!enabled) {
    return { relations: NO_RELATIONS, lens: null, loading: false, error: false, answer: 0, patch };
  }
  const current = result !== null && result.kind === kind && result.tick === tick;
  return {
    relations: result?.relations ?? NO_RELATIONS,
    lens: result?.lens ?? null,
    error: result?.error ?? false,
    loading: !current,
    answer: result?.answer ?? 0,
    patch,
  };
}
