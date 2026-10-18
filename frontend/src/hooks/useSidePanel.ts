"use client";

import { useCallback, useState, useSyncExternalStore } from "react";

export type SideTab = "copilot" | "inspect";

/** From this width the side panel floats on the right; below it, it is a bottom sheet. */
export const SIDE_WIDE_QUERY = "(min-width: 1180px)";
const SIDE_WIDE_PX = 1180;

// Created on first use (never on the server), and again if matchMedia is replaced (tests).
let cached: { matchMedia: typeof window.matchMedia; query: MediaQueryList } | null = null;

function wideQuery(): MediaQueryList | null {
  if (typeof window.matchMedia !== "function") return null;
  if (cached?.matchMedia !== window.matchMedia) {
    cached = { matchMedia: window.matchMedia, query: window.matchMedia(SIDE_WIDE_QUERY) };
  }
  return cached.query;
}

function subscribeWide(onChange: () => void) {
  const query = wideQuery();
  if (!query) return () => {};
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function getWide(): boolean {
  return wideQuery()?.matches ?? window.innerWidth >= SIDE_WIDE_PX;
}

// The server can't know the width: null renders the panel without data-open,
// so CSS shows the default for the width (open from 1180px, a collapsed sheet
// below) until the client knows it, right after hydration.
const onServer = () => null;

/**
 * Whether the screen is wide (from 1180px), where the panel floats on the
 * right and the bottom row has room for the breaking ticker. False on the
 * server and before hydration.
 */
export function useWideScreen(): boolean {
  return useSyncExternalStore(subscribeWide, getWide, () => false);
}

/**
 * State for the side panel (tokens.md principle 2: the co-pilot is open by
 * default on wide screens). Until the visitor opens or collapses it, the
 * panel follows the width. `open` is null only before hydration.
 */
export function useSidePanel() {
  const wide = useSyncExternalStore<boolean | null>(subscribeWide, getWide, onServer);
  const [chosen, setChosen] = useState<boolean | null>(null);
  const [tab, setTab] = useState<SideTab>("copilot");

  const setOpen = useCallback((open: boolean) => setChosen(open), []);

  /** A dot or an arc was clicked: inspect it. */
  const showInspect = useCallback(() => {
    setTab("inspect");
    setChosen(true);
  }, []);

  return { tab, setTab, open: chosen ?? wide, setOpen, showInspect };
}
