"use client";

import { useId } from "react";
import type { LinkRank } from "@/lib/links";

export type GlobeLayer = "dots" | "intensity";

/**
 * The globe's base layers, one at a time (Mood joins when its data exists).
 * Links and Threads are overlays on either base layer, after the divider,
 * and may both be on.
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
}: LayerSwitcherProps) {
  const id = useId();
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
        </span>
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
    </div>
  );
}
