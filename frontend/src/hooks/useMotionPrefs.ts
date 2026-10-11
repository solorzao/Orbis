"use client";

import { useEffect, useSyncExternalStore } from "react";

/** localStorage key: "1" forces low-power mode on, any other value forces it off. */
export const LOW_POWER_KEY = "orbis-low-power";

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

export interface MotionPrefs {
  /** The visitor asked for reduced motion. */
  reduced: boolean;
  /** A slow device (or the override): no drift, no satellites, no backdrop blur. */
  lowPower: boolean;
}

function reducedQuery(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(REDUCED_QUERY);
}

function subscribeReduced(onChange: () => void) {
  const mql = reducedQuery();
  if (!mql) return () => {};
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

function getReduced(): boolean {
  return reducedQuery()?.matches ?? false;
}

function readLowPower(): boolean {
  let override: string | null = null;
  try {
    override = window.localStorage.getItem(LOW_POWER_KEY);
  } catch {
    // Storage can be blocked (privacy mode, sandboxed frames); use the core count.
  }
  if (override !== null) return override === "1";
  return (navigator.hardwareConcurrency || 8) <= 4;
}

function subscribeLowPower(onChange: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key === LOW_POWER_KEY) onChange();
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}

// The server can't know either preference; the client corrects it after hydration.
const onServer = () => false;

/**
 * Motion preferences for the globe, orbits and glass. Also puts `low-power` on
 * <html> so the CSS primitives drop their backdrop blur on slow devices.
 */
export function useMotionPrefs(): MotionPrefs {
  const reduced = useSyncExternalStore(subscribeReduced, getReduced, onServer);
  const lowPower = useSyncExternalStore(subscribeLowPower, readLowPower, onServer);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("low-power", lowPower);
    return () => root.classList.remove("low-power");
  }, [lowPower]);

  return { reduced, lowPower };
}
