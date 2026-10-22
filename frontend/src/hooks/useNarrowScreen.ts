"use client";

import { useSyncExternalStore } from "react";

/** At this width and below, CSS hides the layers and the arcs' labels (soft-orbit.css). */
const NARROW_QUERY = "(max-width: 760px)";

function narrowQuery(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(NARROW_QUERY);
}

function subscribeNarrow(onChange: () => void) {
  const mql = narrowQuery();
  if (!mql) return () => {};
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

/** A phone's width (760px and below). False on the server and before hydration. */
export function useNarrowScreen(): boolean {
  return useSyncExternalStore(
    subscribeNarrow,
    () => narrowQuery()?.matches ?? false,
    () => false,
  );
}
