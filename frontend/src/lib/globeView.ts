import { escapeHtml } from "@/lib/html";
import type { GlobePoint } from "@/types/news";

/** Where the camera rests, and the centre of the calm drift. */
export const HOME_VIEW = { lat: 20, lng: 0, altitude: 2.5 };

/** The globe canvas starts this far above the viewport and is this much taller. */
export const GLOBE_OVERSCAN_PX = 32;

/** Drift amplitude: a few degrees out and back (mockup `frame`). */
const DRIFT_DEG = 5;

/** Where the globe sits on screen, for the orbital rings. */
export interface GlobeGeometry {
  cx: number;
  cy: number;
  R: number;
}

/**
 * On-screen radius of the globe's silhouette in px (mockup `globeGeom`): a
 * camera `altitude` globe radii above the surface sees the sphere at
 * asin(1 / (1 + altitude)) from its centre.
 */
export function projectedRadius(viewportHeight: number, fovDeg: number, altitude: number): number {
  const halfFov = (fovDeg * Math.PI) / 360;
  return ((viewportHeight / 2) * Math.tan(Math.asin(1 / (1 + altitude)))) / Math.tan(halfFov);
}

/** Longitude offset of the drift `elapsedMs` in: +-5 degrees, one swing per period. */
export function driftLng(elapsedMs: number, periodMs: number): number {
  return Math.sin((elapsedMs / periodMs) * Math.PI * 2) * DRIFT_DEG;
}

/** A CSS duration token ("40000ms", "40s") in ms, or the fallback. */
export function durationMs(value: string, fallbackMs: number): number {
  const v = value.trim();
  const n = parseFloat(v);
  if (!Number.isFinite(n)) return fallbackMs;
  return v.endsWith("ms") ? n : v.endsWith("s") ? n * 1000 : n;
}

/** Pulse interval for the rings under the dots; 0 emits one ring and stops (mockup). */
export function ringRepeatMs(motion: { reduced: boolean; lowPower: boolean }): number {
  return motion.reduced || motion.lowPower ? 0 : 2500;
}

/** The Intensity layer's heatmap (mockup initGlobe, line 1290). */
export const HEATMAP = {
  bandwidth: 1.8, // degrees
  colorSaturation: 1.8,
  baseAltitude: 0.006,
  topAltitude: 0.04,
  /** Places the main-thread fallback computes from (see heatmapPoints). */
  maxPointsWithoutGpu: 60,
  /** The held heatmap's opacity under a replay's dots (see showDots). */
  dimmedOpacity: 0.35,
} as const;

/**
 * The Intensity ramp's colours: --accent-periwinkle, --accent-lavender and
 * --text-primary (a canvas can't read CSS variables; a test keeps these equal
 * to tokens.css). Never --signal-warning: that marks surges.
 */
export const HEAT_COLORS = {
  periwinkle: "#8b9cff",
  lavender: "#c3a6ff",
  peak: "#eef0ff",
} as const;

/** Where the ramp passes each colour, and how opaque it is there. */
const HEAT_STOPS = [
  { t: 0, color: HEAT_COLORS.periwinkle, alpha: 0 },
  { t: 0.35, color: HEAT_COLORS.periwinkle, alpha: 0.45 },
  { t: 0.7, color: HEAT_COLORS.lavender, alpha: 0.75 },
  { t: 1, color: HEAT_COLORS.peak, alpha: 0.95 },
] as const;

const rgb = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

/**
 * The Intensity heatmap's colour for heat t (0 to 1): clear where there is no
 * heat, so the land shows through, then periwinkle, lavender and near-white
 * at the peak, more opaque as it rises. "rgba(r,g,b,a)" with whole-number
 * channels, as three-globe parses it.
 */
export function heatColor(t: number): string {
  const x = Math.min(1, Math.max(0, t));
  let i = 0;
  while (i < HEAT_STOPS.length - 2 && x > HEAT_STOPS[i + 1].t) i++;
  const a = HEAT_STOPS[i];
  const b = HEAT_STOPS[i + 1];
  const f = (x - a.t) / (b.t - a.t);
  const [r0, g0, b0] = rgb(a.color);
  const [r1, g1, b1] = rgb(b.color);
  const mix = (p: number, q: number) => Math.round(p + (q - p) * f);
  const alpha = Math.round((a.alpha + (b.alpha - a.alpha) * f) * 1000) / 1000;
  return `rgba(${mix(r0, r1)},${mix(g0, g1)},${mix(b0, b1)},${alpha})`;
}

/**
 * The places the Intensity heatmap is computed from. three-globe evaluates
 * every place at each of the sphere's ~246,000 vertices: with WebGPU (see
 * webGpuReady) that takes about 0.35 s whatever the count, so every place
 * goes in. Without it (Firefox, older Safari, no usable GPU) the work runs on
 * the main thread at about 10 ms per place on a fast desktop, so only the
 * busiest HEATMAP.maxPointsWithoutGpu go in (a pause of about 0.7 s); the
 * quiet places dropped barely tint it.
 */
export function heatmapPoints<P extends { count: number }>(
  points: readonly P[],
  { gpu }: { gpu: boolean },
): P[] {
  if (gpu) return [...points];
  return [...points].sort((a, b) => b.count - a.count).slice(0, HEATMAP.maxPointsWithoutGpu);
}

/**
 * Whether Intensity recomputes its heatmap for new dots. On the main-thread
 * path (no WebGPU) a recompute blocks for about 0.7 s, so while `hold` is on
 * (a replay plays, or new dots are loading) it keeps the heatmap it has and
 * recomputes once when released. With WebGPU it always recomputes.
 */
export function recomputeHeatmap({ gpu, hold }: { gpu: boolean; hold: boolean }): boolean {
  return gpu || !hold;
}

/**
 * Whether the globe draws its dots. Always on the Dots layer, never under
 * Intensity, except during a replay on the main-thread path: there the
 * heatmap is held (see recomputeHeatmap), so each day's dots show over it.
 * With WebGPU the heatmap itself changes each day.
 */
export function showDots(
  layer: "dots" | "intensity",
  { replaying, cpuPath }: { replaying: boolean; cpuPath: boolean },
): boolean {
  return layer === "dots" || (replaying && cpuPath);
}

/** "#rrggbb" to "rgba(r,g,b,a)", for canvas colours built from tokens. */
export function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.trim().replace("#", ""), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/**
 * The hover tooltip for a point. globe.gl renders it as HTML, and the place
 * name comes from news data, so it is escaped and the count forced to a number.
 */
export function pointTooltipHtml(p: GlobePoint): string {
  const count = `<span style="color:${p.color};font-weight:600">${Number(p.count) || 0} stories</span>`;
  const place = escapeHtml(p.locationName ?? "");
  const label = place ? `${count} <span style="color:var(--text-muted)">•</span> ${place}` : count;
  return `<div style="background:var(--surface-panel);backdrop-filter:blur(12px);border:1px solid var(--border-accent);border-radius:8px;padding:8px 12px;font-family:system-ui;color:var(--text-primary);font-size:12px;max-width:300px;pointer-events:none">${label}</div>`;
}
