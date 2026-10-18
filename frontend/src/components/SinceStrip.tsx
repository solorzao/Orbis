"use client";

import { useId, useState } from "react";
import { sinceAgo, sinceSummary, type SinceDelta, type SincePlace } from "@/lib/sinceVisit";

interface SinceStripProps {
  /** The previous visit (ms). */
  lastVisit: number;
  delta: SinceDelta;
  /** Set the time window from the visit to now. */
  onShow: () => void;
  /** Fly to a place and open it in Inspect. */
  onOpen: (place: SincePlace) => void;
  /** Hide it for the session. */
  onDismiss: () => void;
  /**
   * The strip under the brand (from 1180px, soft-orbit.css), or a callout card
   * in the co-pilot, where narrow screens have room for it.
   */
  variant?: "strip" | "callout";
}

/**
 * "Since your last visit" (mockup .since): "Welcome back. 14 h since your
 * visit: 1,286 new stories, 4 breaking stories.", with Show (the window from
 * the visit to now), Top 5 (the places with the most new stories, each of
 * which opens) and Dismiss.
 */
export default function SinceStrip({
  lastVisit,
  delta,
  onShow,
  onOpen,
  onDismiss,
  variant = "strip",
}: SinceStripProps) {
  const [open, setOpen] = useState(false);
  const listId = useId();

  const body = (
    <>
      <p className="since-txt">
        <b>Welcome back.</b> {sinceSummary(sinceAgo(lastVisit, delta.at), delta)}
      </p>
      <div className="since-actions">
        <button type="button" className="pill on" onClick={onShow}>
          Show
        </button>
        {delta.top.length > 0 && (
          <button
            type="button"
            className="pill"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((o) => !o)}
          >
            Top 5
          </button>
        )}
        <button type="button" className="iconbtn since-x" aria-label="Dismiss" onClick={onDismiss}>
          <svg
            width="9"
            height="9"
            viewBox="0 0 10 10"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M2 2l6 6M8 2l-6 6" />
          </svg>
        </button>
      </div>
      {delta.top.length > 0 && (
        // Always there for Top 5's aria-controls; hidden while closed.
        <ul
          id={listId}
          className="since-top"
          aria-label="Places with the most new stories"
          hidden={!open}
        >
          {delta.top.map((p) => (
            <li key={`${p.lat}:${p.lng}`}>
              <button
                type="button"
                className="since-place"
                title={p.headline}
                onClick={() => onOpen(p)}
              >
                <span className="since-name">{p.place}</span>
                <span className="num">{p.new}</span>
                <span className="since-hl">{p.headline}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );

  if (variant === "callout") {
    return (
      <section
        className="callout since-callout"
        data-testid="since-callout"
        aria-label="Since your last visit"
      >
        {body}
      </section>
    );
  }
  return (
    <section className="pillbar since" data-testid="since-strip" aria-label="Since your last visit">
      {body}
    </section>
  );
}
