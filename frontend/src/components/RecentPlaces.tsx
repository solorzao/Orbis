"use client";

import type { CSSProperties, ReactNode } from "react";
import type { LinkEntry, PanelEntry, RelationEntry } from "@/types/news";
import { MAX_PANELS } from "@/lib/panelQuery";
import { linkPairLabel } from "@/lib/links";
import { relationPairLabel, reportedEvents } from "@/lib/relations";

interface RecentPlacesProps {
  /** Open places. */
  places: PanelEntry[];
  /** Open links between countries. */
  links?: LinkEntry[];
  /** Open relations between countries (their reported events). */
  relations?: RelationEntry[];
  /** The tracked person or organisation (its dossier's id), shown first. */
  entity?: { id: string; name: string } | null;
  /** The place, link or dossier inspected below. */
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
  /** What the × says it does. */
  closeLabel: string;
  content: ReactNode;
  /** Its stories, or none (the tracked entity). */
  count: number | null;
}

const stories = (n: number) => `${n} ${n === 1 ? "story" : "stories"}`;

function placePill(entry: PanelEntry): Pill {
  const { name, short } = placeNames(entry);
  return {
    id: entry.panelId,
    createdAt: entry.createdAt,
    title: name,
    closeLabel: `Close ${short}`,
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
    closeLabel: `Close ${long}`,
    count: n,
    content: <span className="place-name">{short}</span>,
  };
}

/** A relation's pill: "US ↔ IR · events", from the acting country, with its event count. */
function relationPill(entry: RelationEntry): Pill {
  const { short, long } = relationPairLabel(entry.relation);
  const n = entry.detail?.relation.n ?? entry.relation.n;
  const shown = `${short} · events`;
  return {
    id: entry.relationId,
    createdAt: entry.createdAt,
    title: `${long}: reported events, last 7 days`,
    label: `${shown}: ${long}, ${reportedEvents(n)}`, // the visible words first (label in name)
    closeLabel: `Close ${long} reported events`,
    count: n,
    content: <span className="place-name">{shown}</span>,
  };
}

/** The tracked entity's pill: its dossier, and × to stop tracking. */
function entityPill(entity: { id: string; name: string }): Pill {
  return {
    id: entity.id,
    createdAt: -Infinity,
    title: `Tracking ${entity.name}`,
    label: `Tracking ${entity.name}`,
    closeLabel: `Stop tracking ${entity.name}`,
    count: null,
    content: (
      <>
        <span className="ent-mark" aria-hidden="true" />
        <span className="place-name">{entity.name}</span>
      </>
    ),
  };
}

/**
 * The places, links and relations opened from the globe, as a row of pills
 * at the top of the Inspect tab, oldest first: pick one to inspect it, × to
 * close it. A link reads "US ↔ IR", from where most of its stories come; a
 * relation "US ↔ IR · events", from its acting country. A tracked person or
 * organisation comes first, its × stopping the tracking.
 */
export default function RecentPlaces({
  places,
  links = [],
  relations = [],
  entity = null,
  activeId,
  onSelect,
  onClose,
}: RecentPlacesProps) {
  if (places.length + links.length + relations.length === 0 && !entity) return null;
  // A stable sort: what opened at the same moment keeps its order.
  const opened = [...places.map(placePill), ...links.map(linkPill), ...relations.map(relationPill)]
    .sort((a, b) => a.createdAt - b.createdAt)
    .slice(-MAX_PANELS);
  const pills = entity ? [entityPill(entity), ...opened] : opened;

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
              {pill.count !== null && <span className="num">{pill.count}</span>}
            </button>
            <button
              type="button"
              className="place-close"
              aria-label={pill.closeLabel}
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
