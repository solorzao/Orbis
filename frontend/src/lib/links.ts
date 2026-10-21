/**
 * Co-coverage links between countries (/api/links): the Links layer's arcs,
 * their look on the globe and the pill that names one.
 */
import type { ApiLink, ApiLinkDetail } from "@/lib/api";
import { pointAt } from "@/lib/cells";
import { apiArticlesToNewsArticles, mapApiTopic, mapTopicMix } from "@/lib/clustering";
import type { Relation } from "@/lib/relations";
import type { CountryLink, GlobePoint, LinkCountry, LinkDetail, Topic } from "@/types/news";

/** How links are ranked: surprisingly often together (lift), or by stories (count). */
export type LinkRank = "lift" | "count";

/** Most arcs on the globe: more is clutter (feature-exploration Q2). */
export const LINKS_LIMIT = 40;

/** three-globe's arcAltitudeAutoScale for the links (mockup initGlobe). */
export const ARC_ALTITUDE_SCALE = 0.4;

/** The coverage arcs' dash: 0.9 on, 0.1 off (tokens.md "Connection arc"). */
const DASH_LENGTH = 0.9;
const DASH_GAP = 0.1;

export function toCountryLinks(api: readonly ApiLink[]): CountryLink[] {
  return api.map((l) => ({
    a: l.a,
    b: l.b,
    n: l.n,
    lift: l.lift,
    topic: mapApiTopic(l.topic),
    tone: l.tone,
    from: l.from,
  }));
}

/** One key per pair, whichever way round it is named: "IR-US". */
export function linkKey(a: string, b: string): string {
  return [a.toUpperCase(), b.toUpperCase()].sort().join("-");
}

/** The link's ends, starting where most of its stories come from. */
export function linkEnds(link: CountryLink): [LinkCountry, LinkCountry] {
  return link.from === link.b.iso ? [link.b, link.a] : [link.a, link.b];
}

/** An arc's width: 0.16, plus up to 0.5 by its share of the busiest link's stories. */
export function arcStroke(n: number, maxN: number): number {
  return 0.16 + (maxN > 0 ? n / maxN : 0) * 0.5;
}

/**
 * Whether the arcs' dashes flow. Ambient motion (tokens.md): never with
 * reduced motion or in low-power mode, off by default on a touch-only
 * screen, and paused while the visitor drags the globe.
 */
export function arcFlows(motion: {
  reduced: boolean;
  lowPower: boolean;
  touch?: boolean;
  dragging?: boolean;
}): boolean {
  return !motion.reduced && !motion.lowPower && !motion.touch && !motion.dragging;
}

/** The arc tokens, read from CSS (a canvas can't use variables). */
export interface ArcColors {
  /** --arc-coverage */
  coverage: string;
  /** --arc-highlight */
  highlight: string;
  /** --dur-arc-flow, in ms */
  flowMs: number;
}

/** One arc as globe.gl draws it: a link's, a relation's, or a thread's spread (lib/threads). */
export interface GlobeArc {
  /** The link it draws (Links layer); none for a thread's arc. */
  link?: CountryLink;
  /** The relation it draws (Relations layer, lib/relations): its click opens the inspector. */
  relation?: Relation;
  /** The thread whose spread it draws. */
  thread?: number;
  key: string;
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
  /** One colour, or a gradient from start to end (the aurora). */
  color: string | string[];
  stroke: number;
  dashLength: number;
  dashGap: number;
  dashAnimateTime: number;
}

/**
 * The Links layer's arcs: each from its origin to the other end, stroked by
 * its stories, faint unless it is the inspected link, its dashes flowing
 * away from the origin when motion allows.
 */
export function linkArcs(
  links: readonly CountryLink[],
  {
    inspected,
    colors,
    flow,
  }: {
    /** The inspected link's linkKey, or null. */
    inspected: string | null;
    colors: ArcColors;
    flow: boolean;
  },
): GlobeArc[] {
  const maxN = Math.max(0, ...links.map((l) => l.n));
  return links.map((link) => {
    const [start, end] = linkEnds(link);
    const key = linkKey(link.a.iso, link.b.iso);
    return {
      link,
      key,
      startLat: start.lat,
      startLng: start.lng,
      endLat: end.lat,
      endLng: end.lng,
      color: key === inspected ? colors.highlight : colors.coverage,
      stroke: arcStroke(link.n, maxN),
      dashLength: flow ? DASH_LENGTH : 1,
      dashGap: flow ? DASH_GAP : 0,
      dashAnimateTime: flow ? colors.flowMs : 0,
    };
  });
}

/**
 * The arcs' dash speed while the globe is dragged or not: dragging pauses
 * the flow (tokens.md). As an accessor on the arcs already drawn, so their
 * meshes and dash pattern stay and only the animation stops.
 */
export function arcDashTime(dragging: boolean): (arc: GlobeArc) => number {
  return (arc) => (dragging ? 0 : arc.dashAnimateTime);
}

type Vec = [number, number, number];
const RAD = Math.PI / 180;

/** three-globe's polar2Cartesian, on a unit globe. */
function toVec(lat: number, lng: number, r = 1): Vec {
  return [
    r * Math.cos(lat * RAD) * Math.sin(lng * RAD),
    r * Math.sin(lat * RAD),
    r * Math.cos(lat * RAD) * Math.cos(lng * RAD),
  ];
}

/** Spherical interpolation between two unit vectors `angle` apart, at t. */
function slerp(p: Vec, q: Vec, angle: number, t: number): Vec {
  const s = Math.sin(angle);
  const u = Math.sin((1 - t) * angle) / s;
  const v = Math.sin(t * angle) / s;
  return [p[0] * u + q[0] * v, p[1] * u + q[1] * v, p[2] * u + q[2] * v];
}

/**
 * The top of the arc globe.gl draws between two places, for the pill that
 * names it. three-globe's arc (calcCurve, 2.45) is a cubic Bezier from one
 * end to the other with control points a quarter and three quarters along
 * the great circle, raised 1.5x the arc's altitude (half the angle between
 * the ends times the auto-scale); its midpoint is (P0 + 3 P1 + 3 P2 + P3) / 8.
 */
export function arcApex(
  start: { lat: number; lng: number },
  end: { lat: number; lng: number },
  scale = ARC_ALTITUDE_SCALE,
): { lat: number; lng: number; altitude: number } {
  const p = toVec(start.lat, start.lng);
  const q = toVec(end.lat, end.lng);
  const dot = Math.min(1, Math.max(-1, p[0] * q[0] + p[1] * q[1] + p[2] * q[2]));
  const angle = Math.acos(dot);
  if (angle < 1e-9) return { lat: start.lat, lng: start.lng, altitude: 0 };
  const r = 1 + 1.5 * ((angle / 2) * scale);
  const m1 = slerp(p, q, angle, 0.25).map((c) => c * r);
  const m2 = slerp(p, q, angle, 0.75).map((c) => c * r);
  const mid = [0, 1, 2].map((i) => (p[i] + 3 * m1[i] + 3 * m2[i] + q[i]) / 8) as Vec;
  const len = Math.hypot(...mid);
  return {
    lat: Math.asin(mid[1] / len) / RAD,
    lng: Math.atan2(mid[0], mid[2]) / RAD,
    altitude: len - 1,
  };
}

/** The arc pill's words: "41" and "stories link United States and Iran, mostly politics". */
export function arcPillText(link: CountryLink): { n: number; text: string } {
  const [from, to] = linkEnds(link);
  const verb = link.n === 1 ? "story links" : "stories link";
  const topic = link.topic === "All" ? "" : `, mostly ${link.topic.toLowerCase()}`;
  return { n: link.n, text: `${verb} ${from.name} and ${to.name}${topic}` };
}

/** What the arc pill names: an arc's ends (from its origin), its number and its words. */
export interface ArcPillLabel {
  start: LinkCountry;
  end: LinkCountry;
  n: number;
  text: string;
}

/** A link's arc pill: "41 stories link United States and Iran, mostly politics". */
export function linkPill(link: CountryLink): ArcPillLabel {
  const [start, end] = linkEnds(link);
  return { start, end, ...arcPillText(link) };
}

/** A link's names from its origin: "US ↔ IR" for its pill, "United States and Iran" in full. */
export function linkPairLabel(link: CountryLink): { short: string; long: string } {
  const [from, to] = linkEnds(link);
  return { short: `${from.iso} ↔ ${to.iso}`, long: `${from.name} and ${to.name}` };
}

/** The topic most of a link's stories carry (its topic mix), else the arc's. */
export function linkTopic(mix: Partial<Record<Topic, number>>, fallback: Topic): Topic {
  let best: Topic = fallback;
  let most = 0;
  for (const [topic, n] of Object.entries(mix) as [Topic, number][]) {
    if (n > most) {
      best = topic;
      most = n;
    }
  }
  return best;
}

export function toLinkDetail(api: ApiLinkDetail): LinkDetail {
  return {
    a: api.a,
    b: api.b,
    n: api.n,
    lift: api.lift,
    topicMix: mapTopicMix(api.topic_mix),
    tone: api.tone,
    shared: api.shared,
    themes: api.themes,
    articles: apiArticlesToNewsArticles(api.articles),
  };
}

/** How many other countries a country's links reach (the hover card's footer). */
export function linkedCountries(links: readonly CountryLink[], iso: string | undefined): number {
  if (!iso) return 0;
  const code = iso.toUpperCase();
  const others = new Set<string>();
  for (const l of links) {
    if (l.a.iso === code) others.add(l.b.iso);
    else if (l.b.iso === code) others.add(l.a.iso);
  }
  return others.size;
}

/**
 * The countries of the places an answer names, each once, in order: the
 * country of the globe's dot at each place (cells pointAt). A place with no
 * dot, or a dot with no country, counts for none.
 */
export function actionCountries(
  actions: readonly { lat: number; lng: number }[],
  points: readonly GlobePoint[],
): string[] {
  const codes: string[] = [];
  for (const a of actions) {
    const code = pointAt(points, a.lat, a.lng)?.countryCode?.toUpperCase();
    if (code && !codes.includes(code)) codes.push(code);
  }
  return codes;
}

/**
 * What the Links layer says when it draws nothing: an empty window, or links
 * that could not load. Nothing while it is off or loading, or has arcs.
 */
export function linksStatus({
  on,
  links,
  loading,
  error,
}: {
  on: boolean;
  links: readonly CountryLink[];
  loading: boolean;
  error: boolean;
}): string | null {
  if (!on || loading) return null;
  if (error) return "Links unavailable right now";
  return links.length === 0 ? "No links in this window" : null;
}
