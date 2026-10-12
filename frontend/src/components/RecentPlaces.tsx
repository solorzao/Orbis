"use client";

import type { CSSProperties, ReactNode } from "react";
import type { LinkEntry, PanelEntry } from "@/types/news";
import { MAX_PANELS } from "@/lib/panelQuery";
import { linkPairLabel } from "@/lib/links";

interface RecentPlacesProps {
  /** Open places. */
  places: PanelEntry[];
  /** Open links between countries. */
  links?: LinkEntry[];
  /** The place or link inspected below. */
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
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

interface Pill {
  id: string;
  createdAt: number;
  /** Hover text: the full name. */
  title: string;
  /** For screen readers, when the pill's text is shorthand. */
  label?: string;
  /** Who the × closes. */
  closeName: string;
  content: ReactNode;
  count: number;
}

const stories = (n: number) => `${n} ${n === 1 ? "story" : "stories"}`;

function placePill(entry: PanelEntry): Pill {
  const { name, short } = placeNames(entry);
  return {
    id: entry.panelId,
    createdAt: entry.createdAt,
    title: name,
    closeName: short,
    count: entry.point.count,
    content: (
      <>
        <span
          className="dot"
          aria-hidden="true"
          style={{ "--c": entry.point.color } as CSSProperties}
        />
        <span className="place-name">{short}</span>
      </>
    ),
  };
}

function linkPill(entry: LinkEntry): Pill {
  const { short, long } = linkPairLabel(entry.link);
  const n = entry.detail?.n ?? entry.link.n;
  return {
    id: entry.linkId,
    createdAt: entry.createdAt,
    title: long,
    label: `${short}: ${long}, ${stories(n)}`, // the visible codes first (label in name)
    closeName: long,
    count: n,
    content: <span className="place-name">{short}</span>,
  };
}

/**
 * The places and links opened from the globe, as a row of pills at the top of
 * the Inspect tab, oldest first: pick one to inspect it, × to close it. A
 * link reads "US ↔ IR", from where most of its stories come.
 */
export default function RecentPlaces({
  places,
  links = [],
  activeId,
  onSelect,
  onClose,
}: RecentPlacesProps) {
  if (places.length + links.length === 0) return null;
  // A stable sort: what opened at the same moment keeps its order.
  const pills = [...places.map(placePill), ...links.map(linkPill)]
    .sort((a, b) => a.createdAt - b.createdAt)
    .slice(-MAX_PANELS);

  return (
    <div
      className="places"
      role="group"
      aria-label="Recent places and links"
      data-testid="recent-places"
    >
      {pills.map((pill) => {
        const active = pill.id === activeId;
        return (
          <span key={pill.id} className={`pill place${active ? " on" : ""}`}>
            <button
              type="button"
              className="place-pick"
              data-place={pill.id}
              aria-pressed={active}
              aria-label={pill.label}
              title={pill.title}
              onClick={() => onSelect(pill.id)}
            >
              {pill.content}
              <span className="num">{pill.count}</span>
            </button>
            <button
              type="button"
              className="place-close"
              aria-label={`Close ${pill.closeName}`}
              onClick={() => onClose(pill.id)}
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
