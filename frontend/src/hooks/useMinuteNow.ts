"use client";

import { useSyncExternalStore } from "react";

const MINUTE_MS = 60_000;

function subscribeMinute(onTick: () => void) {
  const id = setInterval(onTick, 15_000);
  return () => clearInterval(id);
}
const minuteNow = () => Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
const noNowOnServer = () => null;

/**
 * "Now" to the minute (epoch ms), so what is told from it (a chart's end, a
 * story's age) moves on as time passes. Null on the server and while
 * hydrating: the server can't know the visitor's clock.
 */
export function useMinuteNow(): number | null {
  return useSyncExternalStore(subscribeMinute, minuteNow, noNowOnServer);
}
