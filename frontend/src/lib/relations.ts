/**
 * Relations between countries (/api/relations): GDELT's reported events over a
 * fixed 7-day lens, the Relations layer's arcs, and the words that name one.
 * Events are machine-coded from news reports: the UI calls them reported events,
 * never facts, and the class is always in words, so colour never carries the
 * meaning alone.
 */
import type { ApiQuadCounts, ApiRelation, ApiRelationDetail, ApiRelations } from "@/lib/api";
import { arcStroke, linkKey, type ArcPillLabel, type GlobeArc } from "@/lib/links";
import type { TimeWindow } from "@/lib/timeWindow";
import type { LinkCountry } from "@/types/news";

/** The class switch: every class, or one side's events only. */
export type RelationKind = "all" | "cooperation" | "conflict";
/** Most arcs on the globe, as for links. */
export const RELATIONS_LIMIT = 40;

export const QUAD_LABELS = {
  verbal_cooperation: "Verbal cooperation",
  material_cooperation: "Material cooperation",
  verbal_conflict: "Verbal conflict",
  material_conflict: "Material conflict",
} as const;
export type QuadKey = keyof typeof QUAD_LABELS;
/** CAMEO QuadClass order: 1 verbal cooperation to 4 material conflict. */
export const QUAD_KEYS: readonly QuadKey[] = [
  "verbal_cooperation",
  "material_cooperation",
  "verbal_conflict",
  "material_conflict",
];

export interface Relation {
  a: LinkCountry;
  b: LinkCountry;
  /** Reported events between the two, either way. */
  n: number;
  /** Distinct outlets among those recorded (a lower bound). */
  outlets: number;
  /** Mentions in each event's first 15 minutes, summed: the arc's width. */
  mentions: number;
  quad: Record<QuadKey, number>;
  kind: "cooperation" | "conflict";
  goldstein: number;
  tone: number;
  /** ISO code of the country whose actors act in most of the events. */
  from: string;
}

export const relationKey = linkKey;

/** The lens's days, and since when it holds rollups (null: none at all). */
export interface RelationLens {
  firstDay: string;
  lastDay: string;
  since: string | null;
}

/** Reported events one way: `from`'s actors acting on `to`'s. */
export interface RelationDirection {
  from: string;
  to: string;
  n: number;
  quad: Record<QuadKey, number>;
}

/** One UTC day's reported events, by side. */
export interface RelationDay {
  day: string;
  cooperation: number;
  conflict: number;
}

/** A report some of the events came from. Its URL is untrusted: links go through isWebUrl. */
export interface RelationSample {
  url: string;
  outlet: string;
  title: string | null;
  day: string;
  /** CAMEO QuadClass, 1 to 4 by the contract (sampleQuad checks it). */
  quadClass: number;
  from: string;
}

/** What the inspector shows for a pair (/api/relations/detail): every class, whatever the switch. */
export interface RelationDetail {
  lens: RelationLens;
  /** The pair's totals, as a list item has them (all classes). */
  relation: Relation;
  directions: RelationDirection[];
  /** All 7 days, zero-filled (relationDays shows those from `since`). */
  daily: RelationDay[];
  samples: RelationSample[];
}

const quadOf = (q: ApiQuadCounts): Record<QuadKey, number> => ({
  verbal_cooperation: q.verbal_cooperation,
  material_cooperation: q.material_cooperation,
  verbal_conflict: q.verbal_conflict,
  material_conflict: q.material_conflict,
});

export function toRelations(api: ApiRelations): RelationLens & { relations: Relation[] } {
  return {
    firstDay: api.first_day,
    lastDay: api.last_day,
    since: api.since,
    relations: api.relations.map(toRelation),
  };
}

export function toRelation(r: ApiRelation): Relation {
  return {
    a: r.a,
    b: r.b,
    n: r.n,
    outlets: r.outlets,
    mentions: r.mentions,
    quad: quadOf(r.quad),
    kind: r.kind,
    goldstein: r.goldstein,
    tone: r.tone,
    from: r.from,
  };
}

export function toRelationDetail(api: ApiRelationDetail): RelationDetail {
  return {
    lens: { firstDay: api.first_day, lastDay: api.last_day, since: api.since },
    relation: toRelation(api),
    directions: api.directions.map((d) => ({
      from: d.from,
      to: d.to,
      n: d.n,
      quad: quadOf(d.quad),
    })),
    daily: api.daily.map((d) => ({ day: d.day, cooperation: d.cooperation, conflict: d.conflict })),
    samples: api.samples.map((s) => ({
      url: s.url,
      outlet: s.outlet,
      title: s.title,
      day: s.day,
      quadClass: s.quad_class,
      from: s.from,
    })),
  };
}

/** The relation's ends, starting at the acting country. */
export function relationEnds(rel: Relation): [LinkCountry, LinkCountry] {
  return rel.from === rel.b.iso ? [rel.b, rel.a] : [rel.a, rel.b];
}

/** A relation's names from the acting country: "US ↔ IR", and "United States and Iran" in full. */
export function relationPairLabel(rel: Relation): { short: string; long: string } {
  const [from, to] = relationEnds(rel);
  return { short: `${from.iso} ↔ ${to.iso}`, long: `${from.name} and ${to.name}` };
}

/** Which side a class is on. */
export function quadSide(key: QuadKey): "cooperation" | "conflict" {
  return key.endsWith("cooperation") ? "cooperation" : "conflict";
}

/**
 * A sample's QuadClass (1 to 4) as its class, or null for anything else: the
 * value comes from GDELT through the API, so the inspector skips a class it
 * can't name rather than fail.
 */
export function sampleQuad(quadClass: number): QuadKey | null {
  return Number.isInteger(quadClass) && quadClass >= 1 && quadClass <= 4
    ? QUAD_KEYS[quadClass - 1]
    : null;
}

/** How a set of events splits, in words: its main class, else its side, else mixed. */
export function quadWords(quad: Record<QuadKey, number>, n: number): string {
  const total = Math.max(n, 1);
  const [top, topN] = (Object.entries(quad) as [QuadKey, number][]).reduce((best, e) =>
    e[1] > best[1] ? e : best,
  );
  if (topN / total >= 0.5) return `mostly ${QUAD_LABELS[top].toLowerCase()}`;
  const conflict = (quad.verbal_conflict + quad.material_conflict) / total;
  if (conflict >= 0.6) return "mostly conflict";
  if (conflict <= 0.4) return "mostly cooperation";
  return "mixed cooperation and conflict";
}

export function relationWords(rel: Relation): string {
  return quadWords(rel.quad, rel.n);
}

/** "312 reported events", or one. */
export function reportedEvents(n: number): string {
  return `${n} ${n === 1 ? "reported event" : "reported events"}`;
}

/** The arc pill's words: "312" and "reported events between United States and Iran, mostly verbal conflict". */
export function relationPillText(rel: Relation): { n: number; text: string } {
  const [from, to] = relationEnds(rel);
  const noun = rel.n === 1 ? "reported event" : "reported events";
  return { n: rel.n, text: `${noun} between ${from.name} and ${to.name}, ${relationWords(rel)}` };
}

/** A relation's arc pill: "312 reported events between United States and Iran, mostly verbal conflict". */
export function relationPill(rel: Relation): ArcPillLabel {
  const [start, end] = relationEnds(rel);
  return { start, end, ...relationPillText(rel) };
}

/** The relation arc tokens, read from CSS (a canvas can't use variables). */
export interface RelationColors {
  /** --arc-relation-cooperation */
  cooperation: string;
  /** --arc-relation-conflict */
  conflict: string;
  /** --arc-highlight */
  highlight: string;
  /** --arc-muted */
  muted: string;
  /** --dur-arc-flow, in ms */
  flowMs: number;
}

/**
 * The Relations layer's arcs: one per pair, from the acting country, coloured
 * by its class (the inspected one highlighted), stroked by mentions, its
 * dashes flowing when motion allows. Muted (another focus leads: an entity,
 * the board), every arc dims, with no highlight and no flow.
 */
export function relationArcs(
  relations: readonly Relation[],
  {
    inspected,
    colors,
    flow,
    muted,
  }: { inspected: string | null; colors: RelationColors; flow: boolean; muted: boolean },
): GlobeArc[] {
  const max = Math.max(0, ...relations.map((r) => r.mentions));
  const flowing = flow && !muted;
  return relations.map((rel) => {
    const [start, end] = relationEnds(rel);
    const key = relationKey(rel.a.iso, rel.b.iso);
    return {
      relation: rel,
      key,
      startLat: start.lat,
      startLng: start.lng,
      endLat: end.lat,
      endLng: end.lng,
      color: muted ? colors.muted : key === inspected ? colors.highlight : colors[rel.kind],
      stroke: Math.round(arcStroke(rel.mentions, max) * 100) / 100,
      dashLength: flowing ? 0.9 : 1,
      dashGap: flowing ? 0.1 : 0,
      dashAnimateTime: flowing ? colors.flowMs : 0,
    };
  });
}

// Fixed English month names: Intl's en-GB says "Sept" on newer ICU builds.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const utcDay = (day: string) => new Date(`${day}T00:00:00Z`);

/** One UTC day in words: "21 Oct". */
export function dayWords(day: string): string {
  const d = utcDay(day);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** The UTC days a relations answer covers, in words. */
export function relationDaysWords(first: string, last: string): string {
  if (first === last) return `${dayWords(first)} (UTC)`;
  const a = utcDay(first);
  const b = utcDay(last);
  const sameMonth = a.getUTCMonth() === b.getUTCMonth();
  return sameMonth
    ? `${a.getUTCDate()}–${dayWords(last)} (UTC days)`
    : `${dayWords(first)} – ${dayWords(last)} (UTC days)`;
}

/**
 * The legend's and the inspector kicker's label ("Relation" there). During
 * the first week after ingestion starts, the lens isn't covered yet, so it
 * says since when it is (as Phase 4's dossier ramp does).
 */
export function relationLensLabel(
  { firstDay, lastDay, since }: RelationLens,
  noun: "Relations" | "Relation" = "Relations",
): string {
  if (since !== null && since > firstDay) return `${noun} · since ${dayWords(since)} (UTC)`;
  return `${noun} · last 7 days · ${relationDaysWords(firstDay, lastDay)}`;
}

/** A detail's days to show: from `since` (or the lens's first day) on; none exist before it. */
export function relationDays(daily: readonly RelationDay[], lens: RelationLens): RelationDay[] {
  const from = lens.since !== null && lens.since > lens.firstDay ? lens.since : lens.firstDay;
  return daily.filter((d) => d.day >= from && d.day <= lens.lastDay);
}

/** What the layer says when it draws nothing; nothing while it loads or has arcs. */
export function relationsStatus(s: {
  loading: boolean;
  error: boolean;
  count: number;
}): string | null {
  if (s.loading) return null;
  if (s.error) return "Relations couldn't load";
  return s.count === 0 ? "No reported events between countries in the last 7 days" : null;
}

/** How many arcs carry a persistent label (decision 6). */
export const LABELLED_ARCS = 5;

/** The strongest relations, by mentions then events: those labelled on the globe. */
export function strongestRelations(relations: readonly Relation[], n = LABELLED_ARCS): Relation[] {
  return [...relations].sort((x, y) => y.mentions - x.mentions || y.n - x.n).slice(0, n);
}

/**
 * The relations whose arcs carry a persistent label now: the strongest, but
 * none while another focus mutes the arcs (an entity, the board), and not the
 * one whose pill shows (hovered, focused or inspected: its pill says more).
 */
export function labelledRelations(
  relations: readonly Relation[],
  { muted, yieldTo }: { muted: boolean; yieldTo: string | null },
): Relation[] {
  if (muted) return [];
  return strongestRelations(relations).filter((r) => relationKey(r.a.iso, r.b.iso) !== yieldTo);
}

/** A persistent label: "US–IR · 312 · conflict", from the acting country, the class in words. */
export function relationTag(rel: Relation): string {
  const [from, to] = relationEnds(rel);
  return `${from.iso}–${to.iso} · ${rel.n} · ${rel.kind}`;
}

export const RELATIONS_UNAVAILABLE =
  "Relations cover the last 7 days: not available for a range or replay";

/** Why the 7-day lens can't show now (a range, or a replay running), or null. */
export function relationsUnavailable(window: TimeWindow, replaying: boolean): string | null {
  return window.kind !== "live" || replaying ? RELATIONS_UNAVAILABLE : null;
}
