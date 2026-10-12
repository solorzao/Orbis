"use client";

import { useId } from "react";

export type GlobeLayer = "dots" | "intensity";

/**
 * The globe's base layers, one at a time. Mood, Links and Threads join when
 * their data exists (PRs 12, 13 and 16); Phase 2 shows only working layers.
 */
export const LAYERS: readonly { id: GlobeLayer; label: string }[] = [
  { id: "dots", label: "Dots" },
  { id: "intensity", label: "Intensity" },
];

interface LayerSwitcherProps {
  layer: GlobeLayer;
  onChange: (layer: GlobeLayer) => void;
  /** Layers that can't be used here, with the reason (shown and announced). */
  unavailable?: Partial<Record<GlobeLayer, string>>;
}

/**
 * Layer switcher (mockup .layers), bottom left of the bottom row. An
 * unavailable layer stays focusable (aria-disabled) so its reason can be read.
 */
export default function LayerSwitcher({ layer, onChange, unavailable = {} }: LayerSwitcherProps) {
  const id = useId();
  return (
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
      {LAYERS.map(
        (l) =>
          unavailable[l.id] && (
            <span key={l.id} id={`${id}-${l.id}`} className="sr-only">
              {unavailable[l.id]}
            </span>
          ),
      )}
    </div>
  );
}
