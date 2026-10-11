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

/** "#rrggbb" to "rgba(r,g,b,a)", for canvas colours built from tokens. */
export function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.trim().replace("#", ""), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
