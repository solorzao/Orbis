/**
 * The entity tracker: Track search (/api/search, and the loaded places),
 * entity dossiers (/api/entities/{type}/{name}), and the globe's focus mode
 * for a tracked person or organisation (dimmed dots, its places sized by
 * stories, arcs from its mention-weighted centre).
 */
import { apiFetch } from "@/lib/api";
import { cellKey, cellPoint } from "@/lib/cells";
import { canvasColor } from "@/lib/globeView";
import type { GlobeArc } from "@/lib/links";
import { cleanLabel, isWebUrl } from "@/hooks/useAgent";
import type { GlobePoint } from "@/types/news";

export type EntityType = "person" | "org";

/** A name to track, and its type when known (a thread's key entities don't say). */
export interface EntityRef {
  name: string;
  type?: EntityType;
}

/** The API's query bounds (routers/search.py): shorter asks only the loaded places. */
export const SEARCH_MIN = 2;
export const SEARCH_MAX = 80;
/** Typing pauses this long before the server is asked. */
export const SEARCH_DEBOUNCE_MS = 200;
/** Places listed, at most: the loaded globe's, searched here. */
export const PLACES_SHOWN = 5;

/** How faint the dots outside a tracked entity's places go (the mockup's board mirror). */
export const FOCUS_DIM_OPACITY = 0.25;
/** The focus arcs' width (tokens.md "Connection arc"): the busiest place's, and the least. */
export const ENTITY_STROKE = { base: 0.3, active: 0.55 } as const;
const DASH_LENGTH = 0.9;
const DASH_GAP = 0.12;

// ── The API's shapes (backend app/models/search.py, entities.py) ────

export interface ApiEntityResult {
  type: EntityType;
  name: string;
  /** Distinct stories this week, among the members read. */
  n: number;
  /** The member cap was reached: at least n ("{n}+"). */
  capped: boolean;
}

export interface ApiThreadResult {
  id: number;
  title: string;
}

export interface ApiSearchResults {
  people: ApiEntityResult[];
  orgs: ApiEntityResult[];
  threads: ApiThreadResult[];
}

export interface ApiEntityPlace {
  lat: number;
  lng: number;
  place: string;
  country_code: string;
  n: number;
  tone: number;
}

export interface ApiEntityDossier {
  name: string;
  type: EntityType;
  counts: { h24: number; d7: number };
  trend: number | null;
  capped: boolean;
  cap: number;
  countries: { country_code: string; n: number }[];
  places: ApiEntityPlace[];
  timeline: { t: string; n: number }[];
  co_mentions: { name: string; n: number; types: EntityType[] }[];
  headlines: {
    title: string;
    source_name: string;
    published_at: string;
    source_url: string;
    place: string;
  }[];
  since: string | null;
}

// ── The app's ───────────────────────────────────────────────────────

export type SearchResults = ApiSearchResults;
export type EntityResult = ApiEntityResult;
export type ThreadResult = ApiThreadResult;

export interface EntityPlace {
  lat: number;
  lng: number;
  place: string;
  countryCode: string;
  /** Distinct stories there. */
  n: number;
  /** Their mean tone, -1 to 1. */
  tone: number;
}

/** A name in the same coverage, and the types it can be tracked as (none: not trackable). */
export interface CoMention {
  name: string;
  n: number;
  types: EntityType[];
}

export interface EntityHeadline {
  title: string;
  sourceName: string;
  publishedAt: string;
  /** A web (http or https) link, or "" (shown without one). */
  sourceUrl: string;
  place: string;
}

export interface EntityDossier {
  name: string;
  type: EntityType;
  h24: number;
  d7: number;
  trend: number | null;
  capped: boolean;
  cap: number;
  /** Countries its stories come from. */
  countries: number;
  places: EntityPlace[];
  timeline: { t: string; n: number }[];
  coMentions: CoMention[];
  headlines: EntityHeadline[];
  /** The earliest story tracking holds: data starts here (the ramp). */
  since: string | null;
}

/** What the box holds, as the server will read it: invisible characters gone, spaces collapsed. */
export function searchQuery(raw: string): string {
  return cleanLabel(raw, SEARCH_MAX);
}

/** People, organisations and threads named like `q` (2 to 80 characters). */
export function fetchSearch(q: string, signal?: AbortSignal): Promise<ApiSearchResults> {
  return apiFetch<ApiSearchResults>("/api/search", { q }, signal);
}

/** A person's or organisation's week. An unknown name throws an ApiError with status 404. */
export function fetchEntity({
  type,
  name,
  signal,
}: {
  type: EntityType;
  name: string;
  signal?: AbortSignal;
}): Promise<ApiEntityDossier> {
  return apiFetch<ApiEntityDossier>(
    `/api/entities/${type}/${encodeURIComponent(name)}`,
    { timespan: "168h" },
    signal,
  );
}

export function toSearchResults(api: Partial<ApiSearchResults>): SearchResults {
  return { people: api.people ?? [], orgs: api.orgs ?? [], threads: api.threads ?? [] };
}

export function toDossier(api: ApiEntityDossier): EntityDossier {
  return {
    name: api.name,
    type: api.type,
    h24: api.counts.h24,
    d7: api.counts.d7,
    trend: api.trend,
    capped: api.capped,
    cap: api.cap,
    countries: api.countries.length,
    places: api.places.map((p) => ({
      lat: p.lat,
      lng: p.lng,
      place: p.place,
      countryCode: p.country_code,
      n: p.n,
      tone: p.tone,
    })),
    timeline: api.timeline.map(({ t, n }) => ({ t, n })),
    coMentions: api.co_mentions.map((m) => ({ name: m.name, n: m.n, types: m.types ?? [] })),
    headlines: api.headlines.map((h) => ({
      title: h.title,
      sourceName: h.source_name,
      publishedAt: h.published_at,
      sourceUrl: isWebUrl(h.source_url) ? h.source_url : "",
      place: h.place,
    })),
    since: api.since,
  };
}

/** Lower case, without accents: "Zürich" finds "zurich". */
const fold = (s: string) =>
  s
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

/**
 * The loaded globe's places whose name matches `q`: its start first, then a
 * word's start, then anywhere in it; the busiest first among each; one per
 * name (the busiest); at most PLACES_SHOWN.
 */
export function searchPlaces(
  points: readonly GlobePoint[],
  q: string,
  limit = PLACES_SHOWN,
): GlobePoint[] {
  const needle = fold(q.trim());
  if (!needle) return [];
  const scored: { point: GlobePoint; score: number }[] = [];
  for (const point of points) {
    if (!point.locationName) continue;
    const name = fold(point.locationName);
    const score = name.startsWith(needle)
      ? 0
      : name.split(/[\s,()/-]+/).some((w) => w.startsWith(needle))
        ? 1
        : name.includes(needle)
          ? 2
          : -1;
    if (score >= 0) scored.push({ point, score });
  }
  scored.sort(
    (a, b) =>
      a.score - b.score ||
      b.point.count - a.point.count ||
      a.point.locationName!.localeCompare(b.point.locationName!),
  );
  const seen = new Set<string>();
  const found: GlobePoint[] = [];
  for (const { point } of scored) {
    const key = fold(point.locationName!);
    if (seen.has(key)) continue;
    seen.add(key);
    found.push(point);
    if (found.length === limit) break;
  }
  return found;
}

/** A count, "{n}+" when it is a floor (the server's cap was reached). */
export function countLabel(n: number, capped: boolean): string {
  return `${n.toLocaleString("en-GB")}${capped ? "+" : ""}`;
}

export function typeLabel(type: EntityType): "Person" | "Organisation" {
  return type === "person" ? "Person" : "Organisation";
}

/** "18 Oct", in UTC. */
export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/** The last 24 h over the 24 h before, as "1.5×", or a dash when there were none before. */
export function trendLabel(trend: number | null): string {
  return trend === null ? "–" : `${trend}×`;
}

const WEEK_MS = 7 * 24 * 3_600_000;

/**
 * While tracking holds less than a week (it began less than 7 days ago), when
 * it began: the dossier says "since {date}" rather than "7 days". Null after.
 */
export function rampSince(since: string | null, now: number): string | null {
  if (!since) return null;
  return now - Date.parse(since) < WEEK_MS ? since : null;
}

/**
 * Which type a co-mentioned name pivots to: its one type, the tracked
 * entity's when it has both (a person and an org share the name), or null
 * when the graph has neither (not trackable).
 */
export function pivotType(m: CoMention, current: EntityType): EntityType | null {
  if (m.types.includes(current)) return current;
  return m.types[0] ?? null;
}

/**
 * What the page's announcer says of the tracking: what is tracked once its
 * dossier lands, an unknown name, or a dossier that couldn't load; nothing
 * before the answer.
 */
export function trackAnnouncement({
  tracked,
  dossier,
  notFound,
  error,
}: {
  tracked: EntityRef | null;
  dossier: Pick<EntityDossier, "name"> | null;
  notFound: boolean;
  error: boolean;
}): string {
  if (!tracked) return "";
  if (notFound) return `No coverage found for ${tracked.name}`;
  if (error) return `Couldn't load ${tracked.name}`;
  return dossier ? `Tracking ${dossier.name}` : "";
}

const counted = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What a screen reader hears when the results settle: "2 places and 1 person", or "No matches". */
export function searchAnnouncement(counts: {
  places: number;
  people: number;
  orgs: number;
  threads: number;
}): string {
  const parts = [
    counts.places ? counted(counts.places, "place", "places") : null,
    counts.people ? counted(counts.people, "person", "people") : null,
    counts.orgs ? counted(counts.orgs, "organisation", "organisations") : null,
    counts.threads ? counted(counts.threads, "thread", "threads") : null,
  ].filter((p): p is string => p !== null);
  if (parts.length === 0) return "No matches";
  if (parts.length === 1) return parts[0];
  return `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}

// ── Focus mode on the globe ─────────────────────────────────────────

const RAD = Math.PI / 180;

/**
 * The entity's centre of gravity: the middle of its places on the sphere,
 * each weighted by its stories (the weighted mean of their unit vectors).
 * The place itself for one; null for none, or places that cancel out.
 */
export function focusCentre(
  places: readonly { lat: number; lng: number; n: number }[],
): { lat: number; lng: number } | null {
  if (places.length === 0) return null;
  if (places.length === 1) return { lat: places[0].lat, lng: places[0].lng };
  const sum = [0, 0, 0];
  for (const { lat, lng, n } of places) {
    const w = Math.max(1, n);
    sum[0] += w * Math.cos(lat * RAD) * Math.cos(lng * RAD);
    sum[1] += w * Math.cos(lat * RAD) * Math.sin(lng * RAD);
    sum[2] += w * Math.sin(lat * RAD);
  }
  const length = Math.hypot(...sum);
  if (length < 1e-6) return null;
  return {
    lat: Math.asin(sum[2] / length) / RAD,
    lng: Math.atan2(sum[1], sum[0]) / RAD,
  };
}

/** The focus arcs' look, from tokens (a canvas can't use CSS variables). */
export interface FocusColors {
  /** --connection-highlight, where an arc ends. */
  highlight: string;
  /** The same, faint, where it starts. */
  start: string;
  /** --connection-flow, in ms */
  flowMs: number;
}

/**
 * Arcs from the entity's centre to each of its places (the connection arc
 * style): wider for busier places, a long slow dash flowing outwards when
 * motion allows. None to a place at the centre itself.
 */
export function focusArcs(
  key: string,
  centre: { lat: number; lng: number },
  places: readonly EntityPlace[],
  { colors, flow }: { colors: FocusColors; flow: boolean },
): GlobeArc[] {
  const maxN = Math.max(1, ...places.map((p) => p.n));
  return places
    .filter((p) => Math.abs(p.lat - centre.lat) + Math.abs(p.lng - centre.lng) > 0.01)
    .map((p) => ({
      key: `entity-${key}-${cellKey(p.lat, p.lng)}`,
      startLat: centre.lat,
      startLng: centre.lng,
      endLat: p.lat,
      endLng: p.lng,
      color: [colors.start, colors.highlight],
      stroke: ENTITY_STROKE.base + (ENTITY_STROKE.active - ENTITY_STROKE.base) * (p.n / maxN),
      dashLength: flow ? DASH_LENGTH : 1,
      dashGap: flow ? DASH_GAP : 0,
      dashAnimateTime: flow ? colors.flowMs : 0,
    }));
}

/**
 * The dots in focus mode: the globe's, plus a stand-in for each of the
 * entity's places that has none (the window's dots may not include it), and
 * each dot's stories in the entity's coverage (null: not one of its places).
 */
export function focusLayer(
  points: readonly GlobePoint[],
  places: readonly EntityPlace[],
): { dots: GlobePoint[]; n: (dot: GlobePoint) => number | null; maxN: number } {
  const byCell = new Map<string, number>();
  for (const p of places) byCell.set(cellKey(p.lat, p.lng), p.n);
  const covered = new Set(points.map((p) => cellKey(p.lat, p.lng)));
  const extra = places
    .filter((p) => !covered.has(cellKey(p.lat, p.lng)))
    .map((p) => cellPoint({ lat: p.lat, lng: p.lng, place: p.place, count: p.n }));
  return {
    dots: extra.length ? [...points, ...extra] : [...points],
    n: (dot) => byCell.get(cellKey(dot.lat, dot.lng)) ?? null,
    maxN: Math.max(1, ...places.map((p) => p.n)),
  };
}

/** A focus place's dot radius (globe degrees, before the zoom's scale): bigger with more stories. */
export function focusRadius(n: number, maxN: number): number {
  return 0.22 + 0.5 * Math.sqrt(Math.max(0, n) / Math.max(1, maxN));
}

/** A dot outside the entity's places, faded to FOCUS_DIM_OPACITY. */
export function dimColor(color: string): string {
  return canvasColor(color, "#c0c3e0", FOCUS_DIM_OPACITY);
}

// ── The dossier's constellation ─────────────────────────────────────

/** The drawing's box and rings: the busiest five near the entity, the rest further out. */
export const CONSTELLATION = {
  width: 360,
  height: 210,
  cx: 180,
  cy: 105,
  max: 15,
  innerCount: 5,
  inner: { rx: 72, ry: 40 },
  outer: { rx: 132, ry: 76 },
  /** Labels longer than this many characters are shortened with an ellipsis. */
  label: 12,
} as const;

export interface ConstellationNode extends CoMention {
  x: number;
  y: number;
  /** The node's radius, by its stories. */
  r: number;
  /** The line to it, by its stories. */
  width: number;
  /** The shown name (shortened), over or under the node. */
  label: string;
  labelY: number;
}

const shorten = (s: string, max: number) =>
  s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`;

/**
 * The co-mentioned names laid out around the entity (mockup drawConstellation):
 * up to 15, most stories first, the busiest five on an inner ring and the
 * rest on an outer one, each sized by its stories, labelled above when in
 * the upper half and below otherwise.
 */
export function constellation(co: readonly CoMention[]): ConstellationNode[] {
  const C = CONSTELLATION;
  const names = co.slice(0, C.max);
  const maxN = Math.max(1, ...names.map((m) => m.n));
  const innerN = Math.min(C.innerCount, names.length);
  const outerN = names.length - innerN;
  return names.map((m, i) => {
    const inner = i < innerN;
    const ring = inner ? C.inner : C.outer;
    const k = inner ? i : i - innerN;
    const count = inner ? innerN : outerN;
    // The outer ring starts half a step round, so its names fall between the inner ones.
    const a = ((k + (inner ? 0 : 0.5)) / count) * Math.PI * 2 - Math.PI / 2;
    const x = C.cx + Math.cos(a) * ring.rx;
    const y = C.cy + Math.sin(a) * ring.ry;
    const share = m.n / maxN;
    const r = 3 + 5 * Math.sqrt(share);
    return {
      ...m,
      x,
      y,
      r,
      width: 0.5 + 1.5 * share,
      label: shorten(m.name, C.label),
      labelY: Math.sin(a) > 0.2 ? y + r + 11 : y - r - 4,
    };
  });
}
