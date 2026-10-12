/**
 * The city hover card's geometry and wording, kept pure so they are tested
 * on their own: where the card goes (mockup lines 1366-1373), the reticle
 * and leader that tie it to its dot, and the small labels it prints.
 */
import type { GlobePoint, Topic } from "@/types/news";
import { windowLabel, type TimeWindow } from "@/lib/timeWindow";

export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface ScreenPoint {
  x: number;
  y: number;
}

/** The chrome the card keeps clear of: the top bar, the side panel (or its pill), the bottom row. */
export interface Chrome {
  top: Box[];
  side: Box[];
  bottom: Box[];
}

/** How far inside the viewport the card stays. */
export const CARD_EDGE_PX = 16;
/** The gap the card keeps from other chrome, as every region does (layout.spec.ts). */
export const CARD_GAP_PX = 12;
/** How far beside its dot the card sits. */
export const CARD_OFFSET_PX = 48;
/** The card never covers its dot or the reticle's ring around it. */
export const DOT_CLEARANCE_PX = 26;
/** What a spot on the side towards the globe's centre costs, in px of distance. */
const NEAR_SIDE_COST_PX = 60;

const grow = (b: Box, by: number): Box => ({
  left: b.left - by,
  top: b.top - by,
  right: b.right + by,
  bottom: b.bottom + by,
});

const overlaps = (a: Box, b: Box) =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, hi));

/**
 * Where the floating card goes (its top-left corner), beside its dot.
 *
 * It prefers the side away from the globe's centre, over space or ocean, at
 * the dot's height (a little above its middle). It never covers the dot, the
 * `avoid` boxes (12px clear of each) or the viewport's 16px edge: among the
 * spots that keep every rule it takes the closest to the preferred one, so
 * near the side panel it moves to the other side, and near the top bar or the
 * bottom row it slides along them. If no spot keeps every rule (a tiny
 * window), it is clamped into the viewport.
 */
export function placeHoverCard({
  dot,
  centreX,
  card,
  viewport,
  avoid,
}: {
  dot: ScreenPoint;
  /** The globe's centre on screen. */
  centreX: number;
  card: Size;
  viewport: Size;
  avoid: readonly Box[];
}): { left: number; top: number } {
  const { width: w, height: h } = card;
  const maxLeft = viewport.width - CARD_EDGE_PX - w;
  const maxTop = viewport.height - CARD_EDGE_PX - h;
  const clampLeft = (x: number) => clamp(x, CARD_EDGE_PX, maxLeft);
  const clampTop = (y: number) => clamp(y, CARD_EDGE_PX, maxTop);

  const ideal = { left: dot.x - CARD_OFFSET_PX - w, right: dot.x + CARD_OFFSET_PX };
  const away = dot.x >= centreX ? "right" : "left";
  const near = away === "right" ? "left" : "right";
  const idealTop = dot.y - h * 0.45;

  const blocks = [
    ...avoid.map((b) => grow(b, CARD_GAP_PX)),
    grow({ left: dot.x, top: dot.y, right: dot.x, bottom: dot.y }, DOT_CLEARANCE_PX),
  ];
  // Candidate edges: the ideal spots, and flush against each block's sides.
  const lefts = new Set(
    [ideal.left, ideal.right, ...blocks.flatMap((b) => [b.left - w, b.right])].map(clampLeft),
  );
  const tops = new Set([idealTop, ...blocks.flatMap((b) => [b.top - h, b.bottom])].map(clampTop));

  let best: { left: number; top: number } | null = null;
  let bestCost = Infinity;
  for (const left of lefts) {
    for (const top of tops) {
      const spot = { left, top, right: left + w, bottom: top + h };
      if (left > maxLeft || top > maxTop) continue; // larger than the viewport
      if (blocks.some((b) => overlaps(spot, b))) continue;
      const cost =
        Math.min(Math.abs(left - ideal[away]), Math.abs(left - ideal[near]) + NEAR_SIDE_COST_PX) +
        Math.abs(top - idealTop);
      if (cost < bestCost) {
        bestCost = cost;
        best = { left, top };
      }
    }
  }
  return best ?? { left: clampLeft(ideal[away]), top: clampTop(idealTop) };
}

/**
 * The docked card on a touch screen: full width less 12px a side, its bottom
 * 12px above the chrome under it (the bottom row and the sheet), as tall as
 * fits under the chrome above it (the top bar). `bottom` is CSS's: from the
 * viewport's bottom edge.
 */
export function dockHoverCard({
  viewport,
  below,
  above,
}: {
  viewport: Size;
  /** Chrome the card stays below: the top bar. */
  below: readonly Box[];
  /** Chrome the card stays above: the bottom row and the sheet. */
  above: readonly Box[];
}): { left: number; width: number; bottom: number; maxHeight: number } {
  const floor = Math.min(viewport.height - CARD_GAP_PX, ...above.map((b) => b.top - CARD_GAP_PX));
  const ceiling = Math.max(CARD_GAP_PX, ...below.map((b) => b.bottom + CARD_GAP_PX));
  return {
    left: CARD_GAP_PX,
    width: viewport.width - 2 * CARD_GAP_PX,
    bottom: viewport.height - floor,
    maxHeight: Math.max(0, floor - ceiling),
  };
}

/**
 * The floating card's greatest height: the room between the chrome it stays
 * below (the top bar) and the chrome it stays above (the bottom row), 12px
 * clear of each and 16px inside the viewport. A taller card scrolls inside.
 */
export function cardMaxHeight({
  viewport,
  below,
  above,
}: {
  viewport: Size;
  below: readonly Box[];
  above: readonly Box[];
}): number {
  const floor = Math.min(viewport.height - CARD_EDGE_PX, ...above.map((b) => b.top - CARD_GAP_PX));
  const ceiling = Math.max(CARD_EDGE_PX, ...below.map((b) => b.bottom + CARD_GAP_PX));
  return Math.max(0, floor - ceiling);
}

/** The reticle locks on (mockup `frame`): its ring closes from 22px to 14px. */
const RETICLE = { from: 22, to: 14, lockMs: 380 } as const;

/** The reticle's radius `elapsedMs` after its card showed; still with reduced motion. */
export function reticleRadius(elapsedMs: number, reduced: boolean): number {
  if (reduced) return RETICLE.to;
  const k = clamp(elapsedMs / RETICLE.lockMs, 0, 1);
  const eased = 1 - Math.pow(1 - k, 3);
  return RETICLE.from - (RETICLE.from - RETICLE.to) * eased;
}

const round1 = (v: number) => Math.round(v * 10) / 10;

/**
 * The leader (mockup `frame`): a soft curve from just outside the reticle of
 * radius `r` to the card's near edge, level with the dot but at least 30px
 * inside the card's corners.
 */
export function leaderPath(dot: ScreenPoint, r: number, card: Box): string {
  const ex = card.left > dot.x ? card.left : card.right;
  const ey = clamp(dot.y, card.top + 30, card.bottom - 30);
  const sx = dot.x + (ex > dot.x ? r + 11 : -(r + 11));
  const mx = (sx + ex) / 2;
  const [a, b, c, d, e] = [sx, dot.y, mx, ey, ex].map(round1);
  return `M${a} ${b} C ${c} ${b}, ${c} ${d}, ${e} ${d}`;
}

/** The topic pills' order, which the mix bar keeps. */
export const TOPIC_ORDER: readonly Exclude<Topic, "All">[] = [
  "Politics",
  "Conflict",
  "Technology",
  "Climate",
  "Economy",
  "Health",
];

export interface MixPart {
  topic: Exclude<Topic, "All">;
  count: number;
  /** Of all the mix's counts, 0 to 1. */
  share: number;
}

/** The topic mix as bar segments, in the pills' order (mockup `mixList`). */
export function topicMixList(mix: Partial<Record<Topic, number>> | undefined): MixPart[] {
  const parts = TOPIC_ORDER.filter((t) => (mix?.[t] ?? 0) > 0).map((t) => ({
    topic: t,
    count: mix![t]!,
  }));
  const total = parts.reduce((sum, p) => sum + p.count, 0);
  return parts.map((p) => ({ ...p, share: p.count / total }));
}

/** "12 min ago", "2 h 25 min ago", "2 d ago" (mockup `fmtAgo`). */
export function formatAgo(publishedAt: string, nowMs: number): string {
  const mins = Math.floor((nowMs - Date.parse(publishedAt)) / 60_000);
  if (!(mins >= 1)) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours >= 24) return `${Math.floor(hours / 24)} d ago`;
  const rest = mins % 60;
  return rest ? `${hours} h ${rest} min ago` : `${hours} h ago`;
}

/** A place's name, or its coordinates when it has none ("48.5°, 2.5°"). */
export function placeName(point: Pick<GlobePoint, "lat" | "lng" | "locationName">): string {
  return point.locationName || `${point.lat.toFixed(1)}°, ${point.lng.toFixed(1)}°`;
}

/**
 * The card's short label, which the page announces when it shows: "Paris,
 * France: 5 stories. France announces new climate policy".
 */
export function cardLabel(point: GlobePoint): string {
  const stories = `${point.count} ${point.count === 1 ? "story" : "stories"}`;
  const label = `${placeName(point)}: ${stories}`;
  return point.lead ? `${label}. ${point.lead.title}` : label;
}

/** "37 stories, last 24 h", "5 stories, last 7 days" or "5 stories, Tue 14:00 – Wed 02:00 UTC". */
export function cardCountLabel(count: number, window: TimeWindow): string {
  const stories = `${count} ${count === 1 ? "story" : "stories"}`;
  if (window.kind === "range") return `${stories}, ${windowLabel(window)}`;
  return `${stories}, ${window.hours === 168 ? "last 7 days" : `last ${window.hours} h`}`;
}

/** The sparkline's line and filled area (mockup `spark`): the busiest hour reaches the top. */
export function sparkPaths(values: readonly number[], width: number, height: number) {
  const max = Math.max(...values, 1);
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const line = values
    .map((v, i) => {
      const x = i * step;
      const y = height - 2 - (v / max) * (height - 4);
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return { line, area: `${line} L${width} ${height} L0 ${height} Z` };
}
