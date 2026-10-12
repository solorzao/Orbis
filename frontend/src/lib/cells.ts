import type { GlobePoint } from "@/types/news";

/** The globe's grid: dots stand for 1° cells (backend grid.cell_index, cell_size=1.0). */
const CELL_DEG = 1;

/** How far from a point a dot may stand and still be its place: about one cell's diagonal. */
export const NEAR_DEG = 1.5;

/** Great-circle distance between two points, in degrees of arc. */
function arcDegrees(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const rad = Math.PI / 180;
  const dLat = (bLat - aLat) * rad;
  const dLng = (bLng - aLng) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLng / 2) ** 2;
  return (2 * Math.asin(Math.min(1, Math.sqrt(h)))) / rad;
}

const cell = (deg: number) => Math.floor(deg / CELL_DEG);

/**
 * The dot for a place the co-pilot names: the one in the same 1° cell (FLOOR,
 * as the backend groups them), else the nearest within NEAR_DEG, else null.
 */
export function pointAt(
  points: readonly GlobePoint[],
  lat: number,
  lng: number,
): GlobePoint | null {
  const same = points.find((p) => cell(p.lat) === cell(lat) && cell(p.lng) === cell(lng));
  if (same) return same;
  let nearest: GlobePoint | null = null;
  let best = NEAR_DEG;
  for (const p of points) {
    const d = arcDegrees(lat, lng, p.lat, p.lng);
    if (d <= best) {
      best = d;
      nearest = p;
    }
  }
  return nearest;
}
