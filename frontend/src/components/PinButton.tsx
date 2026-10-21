"use client";

import { createContext, useContext, useId } from "react";
import { MAX_PINS, type PinSnapshot } from "@/lib/board";

/** What a pin button needs of the board: the page provides it (useBoard, plus its announcements). */
export interface PinControls {
  has: (item: string) => boolean;
  full: boolean;
  toggle: (item: string, snapshot: PinSnapshot) => void;
}

/** The board's pin controls; without a provider, pin buttons don't show. */
export const PinContext = createContext<PinControls | null>(null);

const FULL_NOTE = `The board holds ${MAX_PINS} pins. Remove one to pin another.`;

/** A pushpin, filled once pinned. */
function PinIcon({ pinned }: { pinned: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill={pinned ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4.4 1.5h3.2l-.5 3.1 1.9 1.9H3l1.9-1.9z" />
      <path d="M6 6.5v4" fill="none" />
    </svg>
  );
}

interface PinButtonProps {
  /** The item's board id (lib/board), or null when it has none (it isn't pinnable). */
  item: string | null;
  /** What to save with the pin: built only when it is pinned. */
  snapshot: () => PinSnapshot;
  /** An icon alone (a story's row), named for what it pins. */
  compact?: boolean;
  /** What it pins, for the compact button's name. */
  label?: string;
}

/**
 * "Pin to board": pressed, and "Pinned", while the item is on the board
 * (pressing it again unpins it). When the board is full it is disabled
 * (still focusable) with a note saying why.
 */
export default function PinButton({ item, snapshot, compact = false, label }: PinButtonProps) {
  const board = useContext(PinContext);
  const noteId = useId();
  if (!board || !item) return null;
  const pinned = board.has(item);
  const blocked = !pinned && board.full;
  const words = pinned ? "Pinned" : blocked ? "Board full" : "Pin to board";
  const name = compact && label ? `${words}: ${label}` : undefined;
  return (
    <>
      <button
        type="button"
        className={compact ? "iconbtn pin-btn compact" : "pill pin-btn"}
        aria-pressed={pinned}
        aria-disabled={blocked || undefined}
        aria-label={name}
        aria-describedby={blocked ? noteId : undefined}
        title={blocked ? FULL_NOTE : compact ? words : undefined}
        data-pin={item}
        onClick={() => {
          if (!blocked) board.toggle(item, snapshot());
        }}
      >
        <PinIcon pinned={pinned} />
        {!compact && words}
      </button>
      {blocked && (
        <span id={noteId} className="sr-only">
          {FULL_NOTE}
        </span>
      )}
    </>
  );
}
