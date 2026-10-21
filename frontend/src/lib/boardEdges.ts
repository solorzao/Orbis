/**
 * The board's edges: the typed ones /api/board/links computes (same thread,
 * shared names, same place, covered together) and "close in time", computed
 * here from the pins' snapshots. Where they go on the board's canvas, how
 * they read in the list view, and the globe's mirror of them.
 */
import { cleanLabel } from "@/hooks/useAgent";
import { cellKey } from "@/lib/cells";
import { parseItem, type Pin } from "@/lib/board";
import type { GlobeArc } from "@/lib/links";

/** The server's kinds, then the board's own (backend EDGE_KINDS, then close in time). */
export const EDGE_KINDS = [
  "same_thread",
  "shared_entity",
  "same_place",
  "co_covered",
  "close_in_time",
] as const;
export type EdgeKind = (typeof EDGE_KINDS)[number];
const SERVER_KINDS: readonly string[] = EDGE_KINDS.slice(0, 4);

/** An edge between two pins, from the earlier one on the board. */
export interface BoardEdge {
  a: string;
  b: string;
  kind: EdgeKind;
  /** "same thread", "shared: A, B", "same place", "covered together: A and B", "45 min apart". */
  label: string;
}

/** The legend's words for each kind. */
export const EDGE_LEGEND: { kind: EdgeKind; label: string }[] = [
  { kind: "same_thread", label: "Same thread" },
  { kind: "shared_entity", label: "Shared names" },
  { kind: "same_place", label: "Same place" },
  { kind: "co_covered", label: "Covered together" },
  { kind: "close_in_time", label: "Close in time" },
];

/** Two stories published at most this far apart are close in time. */
export const CLOSE_IN_TIME_MS = 2 * 60 * 60_000;

/** /api/board/links' answer, well-formed edges only. */
export function toBoardLinks(raw: unknown): { edges: BoardEdge[]; coCoverageChecked: boolean } {
  const r = (raw ?? {}) as { edges?: unknown; co_coverage_checked?: unknown };
  const edges: BoardEdge[] = [];
  for (const e of Array.isArray(r.edges) ? r.edges : []) {
    const { a, b, kind, label } = (e ?? {}) as Record<string, unknown>;
    const words = cleanLabel(label, 200);
    if (!parseItem(a) || !parseItem(b) || typeof kind !== "string") continue;
    if (!SERVER_KINDS.includes(kind) || !words) continue;
    edges.push({ a: a as string, b: b as string, kind: kind as EdgeKind, label: words });
  }
  return { edges, coCoverageChecked: r.co_coverage_checked === true };
}

/** "45 min apart", "1.5 h apart". */
function apart(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 1) return "under 1 min apart";
  if (minutes < 60) return `${minutes} min apart`;
  return `${(minutes / 60).toFixed(1).replace(/\.0$/, "")} h apart`;
}

/**
 * Stories published within two hours of each other. Only stories: a place's
 * time is its newest story's and a thread's its last, so any two busy ones
 * would be "close"; names and links have none.
 */
export function closeInTimeEdges(pins: readonly Pin[]): BoardEdge[] {
  const timed = pins
    .filter((p) => parseItem(p.item)?.kind === "article" && p.snapshot.time)
    .map((p) => ({ item: p.item, t: Date.parse(p.snapshot.time!) }))
    .filter((p) => Number.isFinite(p.t));
  const edges: BoardEdge[] = [];
  for (let i = 0; i < timed.length; i++) {
    for (let j = i + 1; j < timed.length; j++) {
      const gap = Math.abs(timed[i].t - timed[j].t);
      if (gap <= CLOSE_IN_TIME_MS) {
        edges.push({
          a: timed[i].item,
          b: timed[j].item,
          kind: "close_in_time",
          label: apart(gap),
        });
      }
    }
  }
  return edges;
}

/**
 * The board's edges: the server's, for pins still on it, with close in time
 * added; each from the earlier pin, sorted by pins, then kind (as the server sorts).
 */
export function boardEdges(server: readonly BoardEdge[], pins: readonly Pin[]): BoardEdge[] {
  const index = new Map(pins.map((p, i) => [p.item, i]));
  const seen = new Set<string>();
  const edges: BoardEdge[] = [];
  for (const e of [...server, ...closeInTimeEdges(pins)]) {
    const i = index.get(e.a);
    const j = index.get(e.b);
    if (i === undefined || j === undefined || i === j) continue;
    const edge = i < j ? e : { ...e, a: e.b, b: e.a };
    const key = `${edge.a}|${edge.b}|${edge.kind}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push(edge);
  }
  const rank = (e: BoardEdge) => [index.get(e.a)!, index.get(e.b)!, EDGE_KINDS.indexOf(e.kind)];
  return edges.sort((x, y) => {
    const [a, b] = [rank(x), rank(y)];
    return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
  });
}

/** An edge as the list view shows it under one of its pins: the other pin, by its number. */
export interface PinEdge {
  other: string;
  /** The other pin's number on the board (1-based). */
  n: number;
  kind: EdgeKind;
  label: string;
}

/** Each pin's edges, in the board's order. */
export function pinEdges(
  pins: readonly Pin[],
  edges: readonly BoardEdge[],
): Map<string, PinEdge[]> {
  const index = new Map(pins.map((p, i) => [p.item, i + 1]));
  const by = new Map<string, PinEdge[]>(pins.map((p) => [p.item, []]));
  for (const e of edges) {
    const { kind, label } = e;
    by.get(e.a)?.push({ other: e.b, n: index.get(e.b) ?? 0, kind, label });
    by.get(e.b)?.push({ other: e.a, n: index.get(e.a) ?? 0, kind, label });
  }
  return by;
}

// ── On the board's canvas ───────────────────────────────────────────

/** How far an edge bows off the straight line between its cards (px). */
export const EDGE_BOW = 28;
/** How far apart the bows of one pair's edges are, so each label shows. */
const EDGE_SPREAD = 48;

/** An edge drawn: its SVG path and where its label goes. */
export interface LaidEdge extends BoardEdge {
  key: string;
  d: string;
  x: number;
  y: number;
}

const r1 = (v: number) => Math.round(v * 10) / 10;

/**
 * The edges between the cards' centres (px), as quadratic curves bowed to one
 * side; the edges of one pair bow apart. Each label sits at its curve's middle.
 */
export function layoutEdges(
  centres: ReadonlyMap<string, { x: number; y: number }>,
  edges: readonly BoardEdge[],
): LaidEdge[] {
  const pairs = new Map<string, number>();
  for (const e of edges) pairs.set(`${e.a}|${e.b}`, (pairs.get(`${e.a}|${e.b}`) ?? 0) + 1);
  const nth = new Map<string, number>();
  const laid: LaidEdge[] = [];
  for (const e of edges) {
    const p = centres.get(e.a);
    const q = centres.get(e.b);
    if (!p || !q) continue;
    const pair = `${e.a}|${e.b}`;
    const k = nth.get(pair) ?? 0;
    nth.set(pair, k + 1);
    const bow = EDGE_BOW + (k - ((pairs.get(pair) ?? 1) - 1) / 2) * EDGE_SPREAD;
    const dx = q.x - p.x;
    const dy = q.y - p.y;
    const len = Math.hypot(dx, dy);
    const [nx, ny] = len < 1 ? [0, -1] : [dy / len, -dx / len];
    const cx = r1((p.x + q.x) / 2 + nx * bow);
    const cy = r1((p.y + q.y) / 2 + ny * bow);
    laid.push({
      ...e,
      key: `${pair}|${e.kind}`,
      d: `M${r1(p.x)} ${r1(p.y)} Q${cx} ${cy} ${r1(q.x)} ${r1(q.y)}`,
      x: (r1(p.x) + 2 * cx + r1(q.x)) / 4,
      y: (r1(p.y) + 2 * cy + r1(q.y)) / 4,
    });
  }
  return laid;
}

// ── On the globe ────────────────────────────────────────────────────

/** An arc between two pinned places: one per pair, its strongest kind. */
export interface MirrorArc {
  key: string;
  kind: EdgeKind;
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
}

/** What the globe mirrors of the board: its pinned places, and arcs between them. */
export interface BoardMirror {
  places: { lat: number; lng: number; place: string }[];
  arcs: MirrorArc[];
}

const where = (p: Pin) =>
  p.snapshot.lat !== null && p.snapshot.lng !== null
    ? { lat: p.snapshot.lat, lng: p.snapshot.lng }
    : null;

/**
 * The board on the globe: each pinned place once (by its 1° cell), and an arc
 * for each pair of pins with an edge that are in different places.
 */
export function boardMirror(pins: readonly Pin[], edges: readonly BoardEdge[]): BoardMirror {
  const byItem = new Map(pins.map((p) => [p.item, p]));
  const places: BoardMirror["places"] = [];
  const cells = new Set<string>();
  for (const p of pins) {
    const at = where(p);
    if (!at || cells.has(cellKey(at.lat, at.lng))) continue;
    cells.add(cellKey(at.lat, at.lng));
    places.push({ ...at, place: p.snapshot.place ?? p.snapshot.title });
  }
  const arcs = new Map<string, MirrorArc>();
  for (const e of edges) {
    const from = byItem.get(e.a);
    const to = byItem.get(e.b);
    const start = from && where(from);
    const end = to && where(to);
    if (!start || !end || cellKey(start.lat, start.lng) === cellKey(end.lat, end.lng)) continue;
    const key = `board-${e.a}|${e.b}`;
    const held = arcs.get(key);
    if (held && EDGE_KINDS.indexOf(held.kind) <= EDGE_KINDS.indexOf(e.kind)) continue;
    arcs.set(key, {
      key,
      kind: e.kind,
      startLat: start.lat,
      startLng: start.lng,
      endLat: end.lat,
      endLng: end.lng,
    });
  }
  return { places, arcs: [...arcs.values()] };
}

/** The board arcs' look, from the --board-* tokens (a canvas can't use CSS variables). */
export interface BoardArcColors {
  /** --board-same-thread, where a same-thread arc ends. */
  thread: string;
  /** The same, faint, where it starts. */
  start: string;
  /** The other kinds: --board-same-thread, faint. */
  other: string;
  /** --dur-arc-flow, in ms */
  flowMs: number;
}

const THREAD_STROKE = 0.5;
const OTHER_STROKE = 0.3;

/** The mirror's arcs as globe.gl draws them: same thread flowing when motion allows, the rest still. */
export function boardArcs(
  arcs: readonly MirrorArc[],
  { colors, flow }: { colors: BoardArcColors; flow: boolean },
): GlobeArc[] {
  return arcs.map((a) => {
    const thread = a.kind === "same_thread";
    const flows = thread && flow;
    return {
      key: a.key,
      startLat: a.startLat,
      startLng: a.startLng,
      endLat: a.endLat,
      endLng: a.endLng,
      color: thread ? [colors.start, colors.thread] : colors.other,
      stroke: thread ? THREAD_STROKE : OTHER_STROKE,
      dashLength: flows ? 0.9 : 1,
      dashGap: flows ? 0.12 : 0,
      dashAnimateTime: flows ? colors.flowMs : 0,
    };
  });
}
