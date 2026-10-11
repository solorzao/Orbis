"use client";

import { useSyncExternalStore } from "react";

const TICK_MS = 30_000;

function utcClock(): string {
  const now = new Date();
  const hh = String(now.getUTCHours()).padStart(2, "0");
  const mm = String(now.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function subscribeClock(onTick: () => void) {
  const id = setInterval(onTick, TICK_MS);
  return () => clearInterval(id);
}

// The server's time would never match the visitor's; hydrate with a placeholder.
const serverClock = () => "--:--";

interface StatusPillProps {
  isLive: boolean;
  isLoading: boolean;
  isOffline: boolean;
}

/** UTC clock and the feed's state, top right. */
export default function StatusPill({ isLive, isLoading, isOffline }: StatusPillProps) {
  const time = useSyncExternalStore(subscribeClock, utcClock, serverClock);

  return (
    <div className="pillbar status" data-testid="status-pill">
      <span className="clock">
        <span className="num">{time}</span>
        <span className="lbl">UTC</span>
      </span>
      {/* Always mounted, so screen readers announce Loading… → Live → Offline. */}
      <span role="status" className="state-region">
        {isOffline ? (
          <span className="state offline">Offline</span>
        ) : isLoading ? (
          <span className="state muted">Loading…</span>
        ) : isLive ? (
          <span className="state live">Live</span>
        ) : null}
      </span>
    </div>
  );
}
