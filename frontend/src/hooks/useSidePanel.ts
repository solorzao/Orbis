"use client";

import { useCallback, useState, useSyncExternalStore } from "react";

export type SideTab = "copilot" | "stories";

/** From this width the side panel floats on the right; below it, it is a bottom sheet. */
export const SIDE_WIDE_QUERY = "(min-width: 1180px)";
const SIDE_WIDE_PX = 1180;

function subscribeWide(onChange: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const mql = window.matchMedia(SIDE_WIDE_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

function getWide(): boolean {
  if (typeof window.matchMedia !== "function") return window.innerWidth >= SIDE_WIDE_PX;
  return window.matchMedia(SIDE_WIDE_QUERY).matches;
}

// The server can't know the width: render closed, and the client opens the
// panel right after hydration on a wide screen (no hydration mismatch).
const onServer = () => false;

/**
 * State for the side panel (tokens.md principle 2: the co-pilot is open by
 * default on wide screens). Until the visitor opens or collapses it, the
 * panel follows the width: open from 1180px, a collapsed sheet below.
 */
export function useSidePanel() {
  const wide = useSyncExternalStore(subscribeWide, getWide, onServer);
  const [chosen, setChosen] = useState<boolean | null>(null);
  const [tab, setTab] = useState<SideTab>("copilot");

  const setOpen = useCallback((open: boolean) => setChosen(open), []);

  /** A dot was clicked: show its stories. */
  const showStories = useCallback(() => {
    setTab("stories");
    setChosen(true);
  }, []);

  return { tab, setTab, open: chosen ?? wide, setOpen, showStories };
}
