"use client";

import { useId } from "react";
import type { LinkRank } from "@/lib/links";
import {
  RELATIONS_CAVEAT,
  relationLensLabel,
  type RelationKind,
  type RelationLens,
} from "@/lib/relations";

export type GlobeLayer = "dots" | "intensity";

/**
 * The globe's base layers, one at a time (Mood joins when its data exists).
 * Links, Threads and Relations are overlays on either base layer, after the
 * divider. Threads goes with either arc overlay; Links and Relations draw arcs
 * between the same countries, so the page keeps one of them on (lib/overlays).
 */
export const LAYERS: readonly { id: GlobeLayer; label: string }[] = [
  { id: "dots", label: "Dots" },
  { id: "intensity", label: "Intensity" },
];

/** The Links layer's rank switch: surprising pairs (lift), or the most covered (count). */
const RANKS: readonly { id: LinkRank; label: string }[] = [
  { id: "lift", label: "Surprising" },
  { id: "count", label: "Most covered" },
];

/** The Relations layer's class switch: every class, or one side's events only. */
const KINDS: readonly { id: RelationKind; label: string }[] = [
  { id: "all", label: "All" },
  { id: "cooperation", label: "Cooperation" },
  { id: "conflict", label: "Conflict" },
];

interface LayerSwitcherProps {
  layer: GlobeLayer;
  onChange: (layer: GlobeLayer) => void;
  /** Layers that can't be used here, with the reason (shown and announced). */
  unavailable?: Partial<Record<GlobeLayer, string>>;
  /** The Links overlay: co-coverage arcs over the base layer. */
  links: boolean;
  onLinksChange: (on: boolean) => void;
  rank: LinkRank;
  onRankChange: (rank: LinkRank) => void;
  /** While Links is on: why it draws nothing ("No links in this window"), or null. */
  linksStatus?: string | null;
  /** The Threads overlay: the developing stories' rail, and the selected one's spread. */
  threads: boolean;
  onThreadsChange: (on: boolean) => void;
  /** The Relations overlay: reported events between countries over the last 7 days. */
  relations?: boolean;
  onRelationsChange?: (on: boolean) => void;
  relationKind?: RelationKind;
  onRelationKindChange?: (kind: RelationKind) => void;
  /** While Relations is on: why it draws nothing, or null. */
  relationsStatus?: string | null;
  /** The lens its relations cover, or null while they load. */
  relationLens?: RelationLens | null;
  /** Why Relations can't show now (a range or a replay), or null. */
  relationsUnavailable?: string | null;
}

/**
 * Layer switcher (mockup .layers), bottom left of the bottom row. An
 * unavailable layer stays focusable (aria-disabled) so its reason can be read.
 * While Links is on, its rank switch (and its status, when it draws nothing)
 * float beside the pill (soft-orbit.css), outside it, so the bottom row keeps
 * its size and the timeline its place.
 */
export default function LayerSwitcher({
  layer,
  onChange,
  unavailable = {},
  links,
  onLinksChange,
  rank,
  onRankChange,
  linksStatus = null,
  threads,
  onThreadsChange,
  relations = false,
  onRelationsChange = () => {},
  relationKind = "all",
  onRelationKindChange = () => {},
  relationsStatus = null,
  relationLens = null,
  relationsUnavailable = null,
}: LayerSwitcherProps) {
  const id = useId();
  // Relations' class switch, legend and status show only while it is on and can show.
  const relationsShown = relations && relationsUnavailable === null;
  return (
    <div className="layer-dock">
      <div
        className="pillbar layers"
        role="group"
        aria-label="Globe layers"
        data-testid="layer-switcher"
      >
        <div className="seg">
          {LAYERS.map((l) => {
            const reason = unavailable[l.id];
            return (
              <button
                key={l.id}
                type="button"
                aria-pressed={layer === l.id}
                aria-disabled={reason ? true : undefined}
                aria-describedby={reason ? `${id}-${l.id}` : undefined}
                title={reason}
                onClick={() => {
                  if (!reason) onChange(l.id);
                }}
              >
                {l.label}
              </button>
            );
          })}
        </div>
        <span className="sep" aria-hidden="true" />
        <span className="overlays">
          <button
            type="button"
            className="tg"
            aria-pressed={links}
            title="Countries covered in the same stories"
            onClick={() => onLinksChange(!links)}
          >
            Links
          </button>
          <button
            type="button"
            className="tg"
            aria-pressed={threads}
            title="The same developing story across outlets and places"
            onClick={() => onThreadsChange(!threads)}
          >
            Threads
          </button>
          {/* Unavailable under a range or a replay: aria-disabled keeps it focusable, its note read. */}
          <button
            type="button"
            className="tg"
            aria-pressed={relations}
            aria-disabled={relationsUnavailable ? true : undefined}
            aria-describedby={relationsUnavailable ? `${id}-relations` : undefined}
            title={
              relationsUnavailable ??
              "Reported events between countries over the last 7 days (GDELT)"
            }
            onClick={() => {
              if (!relationsUnavailable) onRelationsChange(!relations);
            }}
          >
            Relations
          </button>
        </span>
        {relationsUnavailable && (
          <span id={`${id}-relations`} className="sr-only">
            {relationsUnavailable}
          </span>
        )}
        {LAYERS.map(
          (l) =>
            unavailable[l.id] && (
              <span key={l.id} id={`${id}-${l.id}`} className="sr-only">
                {unavailable[l.id]}
              </span>
            ),
        )}
      </div>
      {links && (
        <div
          className="pillbar link-rank"
          role="group"
          aria-label="Rank links"
          data-testid="link-rank"
        >
          <div className="seg">
            {RANKS.map((r) => (
              <button
                key={r.id}
                type="button"
                aria-pressed={rank === r.id}
                onClick={() => onRankChange(r.id)}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {links && linksStatus && (
        // Read out by the page's announcer, so no live region here.
        <p className="pillbar links-status" data-testid="links-status">
          {linksStatus}
        </p>
      )}
      {relationsShown && (
        <div
          className="pillbar link-rank relation-kind"
          role="group"
          aria-label="Show relations"
          data-testid="relation-kind"
        >
          <div className="seg">
            {KINDS.map((k) => (
              <button
                key={k.id}
                type="button"
                aria-pressed={relationKind === k.id}
                onClick={() => onRelationKindChange(k.id)}
              >
                {k.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {relationsShown && (
        // The legend, and the status when nothing is drawn, float above the class switch.
        <div className="relations-float">
          {relationsStatus && (
            // Read out by the page's announcer, so no live region here.
            <p className="pillbar relations-status" data-testid="relations-status">
              {relationsStatus}
            </p>
          )}
          <p className="pillbar relations-legend" data-testid="relations-legend">
            <span className="rl-lens">
              {relationLens ? relationLensLabel(relationLens) : "Relations · last 7 days"}
            </span>
            <span className="rl-key">
              <span className="sw sw-coop" aria-hidden="true" />
              <span>Cooperation</span>
              <span className="sw sw-conf" aria-hidden="true" />
              <span>Conflict</span>
            </span>
            <span className="rl-note">{RELATIONS_CAVEAT}</span>
            <span className="rl-note rl-topics">Topic filters don&apos;t apply to relations.</span>
          </p>
        </div>
      )}
    </div>
  );
}
