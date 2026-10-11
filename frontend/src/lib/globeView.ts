import { escapeHtml } from "@/lib/html";
import type { GlobePoint } from "@/types/news";

/** Where the camera rests, and the centre of the calm drift. */
export const HOME_VIEW = { lat: 20, lng: 0, altitude: 2.5 };

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
