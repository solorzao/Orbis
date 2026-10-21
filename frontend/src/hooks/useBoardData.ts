"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  SHARE_PARAM,
  decodeShare,
  mergePlan,
  sharedEntries,
  type Pin,
  type PinSnapshot,
} from "@/lib/board";
import { analyzePins, fetchBoardLinks, resolveItems, type BoardMemo } from "@/lib/boardApi";
import { boardMirror, type BoardEdge, type BoardMirror } from "@/lib/boardEdges";
import { FETCH_DEBOUNCE_MS } from "@/hooks/useGlobePoints";
import type { BoardControls } from "@/hooks/useBoard";

const NO_EDGES: BoardEdge[] = [];

const pinWords = (n: number) => `${n} ${n === 1 ? "pin" : "pins"}`;

/**
 * The typed edges between the pins (/api/board/links), asked for while the
 * board shows and two or more pins are on it, after a short pause (as the
 * globe's requests), for the pins in board order. A change of pins aborts the
 * last request and ignores its answer; the last edges stay while the next
 * load (boardEdges keeps only those between pins still on the board). An id
 * the server refuses is left out (fetchBoardLinks); any other failure (a 429,
 * an outage) draws none and says so (`failed`).
 */
export function useBoardLinks(
  items: readonly string[],
  enabled: boolean,
): { edges: BoardEdge[]; coCoverageChecked: boolean; loading: boolean; failed: boolean } {
  const key = items.join("\n");
  const on = enabled && items.length >= 2;
  const [result, setResult] = useState<{
    key: string;
    edges: BoardEdge[];
    coCoverageChecked: boolean;
    failed: boolean;
  } | null>(null);

  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchBoardLinks(key.split("\n"), controller.signal)
        .then(({ edges, coCoverageChecked }) => {
          if (!controller.signal.aborted) {
            setResult({ key, edges, coCoverageChecked, failed: false });
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setResult({ key, edges: NO_EDGES, coCoverageChecked: true, failed: true });
          }
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [on, key]);

  if (!on) return { edges: NO_EDGES, coCoverageChecked: true, loading: false, failed: false };
  const current = result?.key === key;
  return {
    edges: result?.edges ?? NO_EDGES,
    coCoverageChecked: result?.coCoverageChecked ?? true,
    loading: !current,
    failed: current && result.failed,
  };
}

/**
 * The board's AI memo (/api/board/analyze): asked for by Analyze, one at a
 * time. It describes the pins in the order they were when asked (its [n]
 * cite them by number), so a pin added or removed drops it; moving cards
 * doesn't.
 */
export function useBoardMemo(pins: readonly Pin[]): {
  memo: BoardMemo | null;
  analyzing: boolean;
  analyze: () => void;
  dismiss: () => void;
} {
  const key = pins.map((p) => p.item).join("\n");
  const [state, setState] = useState<{ key: string; memo: BoardMemo | null; analyzing: boolean }>({
    key,
    memo: null,
    analyzing: false,
  });
  const pinsRef = useRef(pins);
  const controllerRef = useRef<AbortController | null>(null);
  useEffect(() => {
    pinsRef.current = pins;
  });
  // Pins changed: a memo on its way is for the old ones.
  useEffect(() => () => controllerRef.current?.abort(), [key]);

  const analyze = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ key, memo: null, analyzing: true });
    analyzePins(pinsRef.current, controller.signal)
      .then((memo) => {
        if (!controller.signal.aborted) setState({ key, memo, analyzing: false });
      })
      .catch(() => {
        // aborted: the pins changed or the memo was closed
      });
  }, [key]);

  const dismiss = useCallback(() => {
    controllerRef.current?.abort();
    setState({ key, memo: null, analyzing: false });
  }, [key]);

  const current = state.key === key ? state : null;
  return { memo: current?.memo ?? null, analyzing: current?.analyzing ?? false, analyze, dismiss };
}

/** Whether two mirrors draw the same: the same places and arcs, in order. */
function sameMirror(a: BoardMirror | null, b: BoardMirror | null): boolean {
  if (a === null || b === null) return a === b;
  const place = (p: BoardMirror["places"][number]) => `${p.lat},${p.lng},${p.place}`;
  const arc = (x: BoardMirror["arcs"][number]) =>
    `${x.key},${x.kind},${x.startLat},${x.startLng},${x.endLat},${x.endLng}`;
  return (
    a.places.map(place).join("|") === b.places.map(place).join("|") &&
    a.arcs.map(arc).join("|") === b.arcs.map(arc).join("|")
  );
}

/**
 * The globe's mirror of the board while it shows (its pinned places, arcs
 * between them), or null. The same object while it draws the same, so
 * moving a card doesn't make three-globe rebuild the arcs or restyle the dots.
 */
export function useBoardMirror(
  pins: readonly Pin[],
  edges: readonly BoardEdge[],
  shown: boolean,
): BoardMirror | null {
  const next = shown ? boardMirror(pins, edges) : null;
  const [held, setHeld] = useState(next);
  if (!sameMirror(held, next)) {
    setHeld(next);
    return next;
  }
  return held;
}

/**
 * Each time the board opens, its pins are refreshed from /api/board/resolve:
 * fresh snapshots (an expired pin keeps its own), merged threads adopted.
 * A pin the server refuses is unpinned, and `announce` says so: kept, it
 * would fail every request for edges and every analysis.
 */
export function useBoardRefresh(
  open: boolean,
  board: BoardControls,
  announce: (note: string) => void,
) {
  const { ready, refresh } = board;
  const pinsRef = useRef(board.pins);
  const announceRef = useRef(announce);
  useEffect(() => {
    pinsRef.current = board.pins;
    announceRef.current = announce;
  });
  useEffect(() => {
    if (!open || !ready) return;
    const items = pinsRef.current.map((p) => p.item);
    if (items.length === 0) return;
    const controller = new AbortController();
    resolveItems(items, controller.signal)
      .then(({ items: results, rejected }) => {
        if (controller.signal.aborted) return;
        refresh(results, rejected);
        if (rejected.length > 0) {
          announceRef.current(`Removed ${pinWords(rejected.length)} the server no longer accepts.`);
        }
      })
      .catch(() => {
        // offline: the stored snapshots stand
      });
    return () => controller.abort();
  }, [open, ready, refresh]);
}

/** The page's address without the share parameter (so a reload doesn't ask again). */
function dropShareParam() {
  const url = new URL(window.location.href);
  if (!url.searchParams.has(SHARE_PARAM)) return;
  url.searchParams.delete(SHARE_PARAM);
  window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
}

/**
 * A share link (`?board=`) opened: its ids, read defensively, are resolved
 * through /api/board/resolve (a stand-in from the id for any the server no
 * longer knows; when resolving fails, all of them). An empty board takes them
 * and opens; a board with pins of its own asks first (`offer`), never merging
 * by itself. The parameter goes from the address once read.
 */
export function useSharedBoard(
  board: BoardControls,
  { onOpen, announce }: { onOpen: () => void; announce: (note: string) => void },
): {
  offer: { shared: number; fresh: number; fit: number } | null;
  accept: () => void;
  decline: () => void;
} {
  const [entries, setEntries] = useState<{ item: string; snapshot: PinSnapshot }[] | null>(null);
  const latest = useRef({ board, onOpen, announce });
  useEffect(() => {
    latest.current = { board, onOpen, announce };
  });

  useEffect(() => {
    if (!board.ready) return;
    const param = new URLSearchParams(window.location.search).get(SHARE_PARAM);
    if (param === null) return;
    const ids = decodeShare(param);
    if (ids.length === 0) {
      dropShareParam();
      return;
    }
    const controller = new AbortController();
    const arrive = (shared: { item: string; snapshot: PinSnapshot }[]) => {
      if (controller.signal.aborted) return;
      dropShareParam();
      const { board: current, onOpen: open, announce: say } = latest.current;
      if (shared.length === 0) return;
      if (current.pins.length > 0 && mergePlan(current, shared).fresh > 0) {
        setEntries(shared);
        return;
      }
      const { added } = current.merge(shared);
      say(
        added > 0
          ? `Opened a shared board: ${pinWords(added)}.`
          : "The shared pins are on your board already.",
      );
      open();
    };
    resolveItems(ids, controller.signal)
      .then(({ items, rejected }) => arrive(sharedEntries(ids, items, rejected)))
      .catch(() => arrive(sharedEntries(ids, [], [])));
    return () => controller.abort();
  }, [board.ready]);

  const accept = useCallback(() => {
    if (!entries) return;
    const { board: current, onOpen: open, announce: say } = latest.current;
    const { added } = current.merge(entries);
    setEntries(null);
    say(`Added ${pinWords(added)} to the board.`);
    open();
  }, [entries]);

  const decline = useCallback(() => {
    setEntries(null);
    latest.current.announce("Kept your board as it was.");
  }, []);

  const offer = entries ? { shared: entries.length, ...mergePlan(board, entries) } : null;
  return { offer, accept, decline };
}
