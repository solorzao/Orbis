import type { GlobePoint } from "@/types/news";
import { TOPIC_COLORS } from "@/lib/clustering";

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

/** The 1° cell holding a point, e.g. "48:2": one key per dot, however its points refresh. */
export function cellKey(lat: number, lng: number): string {
  return `${cell(lat)}:${cell(lng)}`;
}

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

/** A place in a 1° cell, from a list the globe's dots may not include. */
export interface CellPlace {
  /** The cell's centre, as its dot would have it. */
  lat: number;
  lng: number;
  place: string;
  /** Its stories, as far as the list knows. */
  count: number;
}

/**
 * A stand-in dot for a cell the globe has none for (it shows the window's
 * busiest 500 places; a story breaking somewhere quiet may not be one). It
 * opens like a dot: the panel lists the cell's stories by its lat/lng and
 * corrects the count once a short page shows the cell's. No topic colour.
 */
export function cellPoint(cell: CellPlace): GlobePoint {
  return {
    id: `cell-${cellKey(cell.lat, cell.lng)}`,
    lat: cell.lat,
    lng: cell.lng,
    size: 1,
    color: TOPIC_COLORS.All,
    articles: [],
    isCluster: cell.count > 1,
    count: cell.count,
    locationName: cell.place,
    topic: "All",
  };
}

/**
 * The dot that opens a place from a list (breaking stories, the places new
 * since a visit): the globe's dot in the place's own cell, else a stand-in.
 * Not pointAt's nearest dot within NEAR_DEG: that would be another place's.
 */
export function dotInCell(points: readonly GlobePoint[], cell: CellPlace): GlobePoint {
  const key = cellKey(cell.lat, cell.lng);
  return points.find((p) => cellKey(p.lat, p.lng) === key) ?? cellPoint(cell);
}
