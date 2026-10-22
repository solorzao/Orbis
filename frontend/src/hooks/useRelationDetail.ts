"use client";

import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import { fetchRelationDetail, retryOnce503 } from "@/lib/api";
import { toRelationDetail, type Relation, type RelationDetail } from "@/lib/relations";
import type { RelationEntry } from "@/types/news";

/**
 * The shown relation's detail (every class, over the same lens), asked each
 * time a relation is shown (opened, or shown again from its pill or arc) and
 * again for each new list answer while it is shown (`answer`: a patch keeps
 * it), so its inspector and its arc agree after a refresh too. An answer goes
 * to its own entry and patches its own pair's arc, and only an entry's latest
 * request counts. A 404 (the pair's last day left the lens around UTC
 * midnight) is said as text, not an error; a refetch that fails or finds
 * nothing keeps the detail shown.
 */
export function useRelationDetail(
  shown: RelationEntry | null,
  answer: number,
  {
    setRelations,
    patch,
  }: {
    setRelations: Dispatch<SetStateAction<RelationEntry[]>>;
    /** useRelations' patch: the pair's arc, label and row take the detail's figures. */
    patch: (detail: RelationDetail) => void;
  },
): void {
  // Each entry's latest request: an earlier one's answer, landing late, is dropped.
  const latest = useRef(new Map<string, number>());
  const requests = useRef(0);

  const load = useCallback(
    async (relationId: string, relation: Relation) => {
      const request = ++requests.current;
      latest.current.set(relationId, request);
      const settle = (update: (r: RelationEntry) => RelationEntry) => {
        if (latest.current.get(relationId) !== request) return false;
        latest.current.delete(relationId);
        setRelations((prev) => prev.map((r) => (r.relationId === relationId ? update(r) : r)));
        return true;
      };
      // Only a newer detail replaces the one shown.
      const failed = (updates: Partial<RelationEntry>) =>
        settle((r) => (r.detail === null ? { ...r, ...updates, detailLoading: false } : r));
      try {
        // A 503 (a read stopped at a cycle's boundary) is asked once more, as the arcs are.
        const api = await retryOnce503(
          () => fetchRelationDetail({ a: relation.a.iso, b: relation.b.iso }),
          new AbortController().signal,
        );
        if (api === null) {
          failed({ notFound: true });
          return;
        }
        const detail = toRelationDetail(api);
        const landed = { detail, detailLoading: false, detailError: false, notFound: false };
        if (settle((r) => ({ ...r, ...landed }))) patch(detail);
      } catch {
        failed({ detailError: true });
      }
    },
    [setRelations, patch],
  );

  // An entry's update (its detail landing) or a patch is neither a new relation
  // shown nor a new answer: only those ask.
  const last = useRef<{ id: string | null; answer: number }>({ id: null, answer });
  useEffect(() => {
    const before = last.current;
    last.current = { id: shown?.relationId ?? null, answer };
    if (shown === null) return;
    // Answer 0 is none (the layer off, unavailable or failed): nothing to agree with.
    if (shown.relationId !== before.id || (answer !== before.answer && answer !== 0)) {
      void load(shown.relationId, shown.relation);
    }
  }, [shown, answer, load]);
}
