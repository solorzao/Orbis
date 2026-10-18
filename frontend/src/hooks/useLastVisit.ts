"use client";

import { useEffect, useSyncExternalStore } from "react";

/** localStorage: when this browser last had Orbis open (an ISO time). */
export const LAST_VISIT_KEY = "orbis-last-visit";

/** A visit counts once it has lasted this long, in case it ends in a crash. */
export const LAST_VISIT_WRITE_MS = 60_000;

/** The visit stored before this page load, read once: writing now must not change it. */
let readOnce: { value: number | null } | null = null;

function readStored(): number | null {
  try {
    const raw = localStorage.getItem(LAST_VISIT_KEY);
    if (!raw) return null;
    const t = Date.parse(raw);
    return Number.isFinite(t) ? t : null;
  } catch {
    return null; // storage blocked: a first visit, so no strip
  }
}

function writeNow() {
  try {
    localStorage.setItem(LAST_VISIT_KEY, new Date().toISOString());
  } catch {
    // storage blocked: this visit isn't remembered
  }
}

const getSnapshot = () => (readOnce ??= { value: readStored() }).value;
const noChanges = () => () => {};
// The server can't know it: the strip comes after hydration.
const onServer = () => null;

/** Tests: read the stored visit afresh, as a new page load does. */
export function forgetLastVisitRead() {
  readOnce = null;
}

/**
 * The previous visit (ms), read from localStorage at mount and kept in
 * memory, or null on a first visit, for garbage or blocked storage. This
 * visit is written as now when the page is hidden or left, and once a minute
 * in, so a visit that crashes still counts.
 */
export function useLastVisit(): number | null {
  const lastVisit = useSyncExternalStore(noChanges, getSnapshot, onServer);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") writeNow();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", writeNow);
    const id = setTimeout(writeNow, LAST_VISIT_WRITE_MS);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", writeNow);
      clearTimeout(id);
    };
  }, []);

  return lastVisit;
}
