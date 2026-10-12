/**
 * Co-coverage links between countries (/api/links): the Links layer's arcs,
 * their look on the globe and the pill that names one.
 */
import type { ApiLink, ApiLinkDetail } from "@/lib/api";
import { apiArticlesToNewsArticles, mapApiTopic, mapTopicMix } from "@/lib/clustering";
import type { CountryLink, LinkCountry, LinkDetail, Topic } from "@/types/news";

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

/** Arcs flow only with full motion: not with reduced motion, nor in low-power mode. */
export function arcFlows(motion: { reduced: boolean; lowPower: boolean }): boolean {
  return !motion.reduced && !motion.lowPower;
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

/** One arc as globe.gl draws it. */
export interface GlobeArc {
  link: CountryLink;
  key: string;
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
  color: string;
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
