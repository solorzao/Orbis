"use client";

import { useEffect, useRef, type RefObject } from "react";
import { spreadView } from "@/lib/threads";

export type ThreadView = { lat: number; lng: number; altitude: number };

/**
 * The globe goes to a selected thread's places (spreadView), once per
 * selection: not on a re-render, nor when its detail brings more places, nor
 * when the same thread is chosen again (a chip). A thread whose places arrive
 * later (a chip's, not in the list) is flown to only if the visitor hasn't
 * grabbed the globe since choosing it (`grabs` counts their presses).
 */
export function useFlyToThread(
  selectedId: number | null,
  spread: readonly { lat: number; lng: number }[] | undefined,
  fly: (view: ThreadView) => void,
  grabs: RefObject<number>,
) {
  const selection = useRef<{ id: number; grabs: number; done: boolean } | null>(null);

  useEffect(() => {
    if (selectedId === null) {
      selection.current = null;
      return;
    }
    if (selection.current?.id !== selectedId) {
      selection.current = { id: selectedId, grabs: grabs.current, done: false };
    }
    const s = selection.current;
    if (s.done || !spread) return;
    s.done = true;
    if (grabs.current !== s.grabs) return; // the visitor has the globe where they want it
    const view = spreadView(spread);
    if (view) fly(view);
  }, [selectedId, spread, fly, grabs]);
}
