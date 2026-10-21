/**
 * The globe's arc overlays: Links and Relations draw arcs between the same
 * countries' label points, so only one is on at a time (Phase 5 decision 5).
 * Every way to turn either on (the layer switcher, the phone chip, the
 * co-pilot's "Show links") goes through this reducer, so turning one on
 * always turns the other off.
 */

export interface Overlays {
  links: boolean;
  relations: boolean;
}

export type OverlayAction = { type: "links" | "relations"; on: boolean };

export const NO_OVERLAYS: Overlays = { links: false, relations: false };

export function overlays(state: Overlays, action: OverlayAction): Overlays {
  const next: Overlays =
    action.type === "links"
      ? { links: action.on, relations: action.on ? false : state.relations }
      : { relations: action.on, links: action.on ? false : state.links };
  return next.links === state.links && next.relations === state.relations ? state : next;
}

const NAMES = { links: "Links", relations: "Relations" } as const;

/** What the announcer says when turning one on turns the other off, else null. */
export function overlayNote(state: Overlays, action: OverlayAction): string | null {
  const other = action.type === "links" ? "relations" : "links";
  if (!action.on || !state[other]) return null;
  return `${NAMES[action.type]} on. ${NAMES[other]} off.`;
}
