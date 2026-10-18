"use client";

import { useEffect, useState, type FocusEvent } from "react";
import { outletsLabel, type BreakingStory } from "@/lib/breaking";
import { useWideScreen } from "@/hooks/useSidePanel";

/** How long each breaking story shows before the next. */
export const ROTATE_MS = 6000;

interface BreakingTickerProps {
  /** What is breaking now, in the API's order; none hides the ticker. */
  stories: readonly BreakingStory[];
  /** Reduced motion: it doesn't move on by itself. */
  reduced: boolean;
  /** Fly to the story's place and open it in Inspect. */
  onOpen: (story: BreakingStory) => void;
}

function Chevron({ back }: { back?: boolean }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 10 10"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={back ? "M6.5 2 3.5 5l3 3" : "M3.5 2l3 3-3 3"} />
    </svg>
  );
}

/**
 * The breaking ticker, the bottom row's right track (mockup `.surges`, as
 * `.breaking`): "Breaking · headline · place · 12 outlets · 1 of 4", one story
 * at a time with previous and next. It moves on every 6 s, but not while the
 * pointer or the focus is on it, nor with reduced motion; while it moves by
 * itself it is quiet to screen readers (a carousel's live region is off).
 * The story shown follows a refresh that still lists it. Below 1180px CSS
 * hides it, and it runs no timer.
 */
export default function BreakingTicker({ stories, reduced, onOpen }: BreakingTickerProps) {
  const [shown, setShown] = useState<string | null>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const wide = useWideScreen();
  const n = stories.length;
  const found = stories.findIndex((s) => s.headline === shown);
  const index = found >= 0 ? found : 0;

  // Nothing to move on to, or hidden: a pointer or focus it had is gone
  // without a mouseleave or blur (its buttons unmount), so the pause ends.
  const turns = n > 1 && wide;
  if (!turns && (hovered || focused)) {
    setHovered(false);
    setFocused(false);
  }
  const rotating = turns && !reduced && !hovered && !focused;

  const show = (i: number) => setShown(stories[(i + n) % n]?.headline ?? null);

  useEffect(() => {
    if (!rotating) return;
    const id = setTimeout(() => setShown(stories[(index + 1) % n].headline), ROTATE_MS);
    return () => clearTimeout(id);
  }, [rotating, index, n, stories]);

  if (n === 0) return null;
  const story = stories[index];

  const onBlur = (e: FocusEvent<HTMLElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
  };

  return (
    <section
      className="pillbar breaking"
      data-testid="breaking-ticker"
      aria-label="Breaking stories"
      aria-roledescription="carousel"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={onBlur}
    >
      <span className="breaking-lab">Breaking</span>
      <div
        className="breaking-live"
        data-testid="breaking-live"
        aria-live={rotating ? "off" : "polite"}
        aria-atomic="true"
      >
        <button
          type="button"
          className="breaking-item"
          data-testid="breaking-item"
          // Its position too, which the count beside it shows outside the live region.
          aria-label={[
            story.headline,
            story.place,
            outletsLabel(story.outlets),
            ...(n > 1 ? [`${index + 1} of ${n}`] : []),
          ].join(", ")}
          title={story.headline}
          onClick={() => onOpen(story)}
        >
          <span className="breaking-head">{story.headline}</span>
          {/* The place gives way first, so the outlet count always shows. */}
          <span className="breaking-meta">
            <span className="breaking-place">{story.place}</span>
            <span className="breaking-outlets">{"\u00a0· " + outletsLabel(story.outlets)}</span>
          </span>
        </button>
      </div>
      {n > 1 && (
        <>
          <span className="breaking-count">
            {index + 1} of {n}
          </span>
          <span className="breaking-nav">
            <button
              type="button"
              className="iconbtn"
              aria-label="Previous breaking story"
              onClick={() => show(index - 1)}
            >
              <Chevron back />
            </button>
            <button
              type="button"
              className="iconbtn"
              aria-label="Next breaking story"
              onClick={() => show(index + 1)}
            >
              <Chevron />
            </button>
          </span>
        </>
      )}
    </section>
  );
}
