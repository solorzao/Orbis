"use client";

import type { CSSProperties } from "react";
import type { PanelEntry } from "@/types/news";

/** The queue's cap in page.tsx (MAX_PANELS). */
const MAX_SHOWN = 5;

interface RecentPlacesProps {
  /** Open places, oldest first. */
  places: PanelEntry[];
  /** The place whose stories show below. */
  activeId: string | null;
  onSelect: (panelId: string) => void;
  onClose: (panelId: string) => void;
}

/** The full place name, and the part before its first comma for the pill. */
function placeNames(entry: PanelEntry): { name: string; short: string } {
  const { point } = entry;
  if (!point.locationName) {
    const coords = `${point.lat.toFixed(1)}°, ${point.lng.toFixed(1)}°`;
    return { name: coords, short: coords };
  }
  return { name: point.locationName, short: point.locationName.split(",")[0].trim() };
}

/**
 * The places opened from the globe, as a row of pills at the top of the
 * Stories tab: pick one to read its stories, × to close it.
 */
export default function RecentPlaces({ places, activeId, onSelect, onClose }: RecentPlacesProps) {
  if (places.length === 0) return null;

  return (
    <div className="places" role="group" aria-label="Recent places" data-testid="recent-places">
      {places.slice(-MAX_SHOWN).map((entry) => {
        const { name, short } = placeNames(entry);
        const active = entry.panelId === activeId;
        return (
          <span key={entry.panelId} className={`pill place${active ? " on" : ""}`}>
            <button
              type="button"
              className="place-pick"
              aria-pressed={active}
              title={name}
              onClick={() => onSelect(entry.panelId)}
            >
              <span
                className="dot"
                aria-hidden="true"
                style={{ "--c": entry.point.color } as CSSProperties}
              />
              <span className="place-name">{short}</span>
              <span className="num">{entry.point.count}</span>
            </button>
            <button
              type="button"
              className="place-close"
              aria-label={`Close ${short}`}
              onClick={() => onClose(entry.panelId)}
            >
              <svg
                width="8"
                height="8"
                viewBox="0 0 10 10"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M2 2l6 6M8 2l-6 6" />
              </svg>
            </button>
          </span>
        );
      })}
    </div>
  );
}
