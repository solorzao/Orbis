/**
 * What a pin saves of each thing pinned, as /api/board/resolve would answer
 * for it (backend services/board.py): enough to show it once its data has
 * expired. Each goes through toSnapshot, so text is cleaned and capped and a
 * story's link is http(s) or nothing.
 */
import { toSnapshot, type PinSnapshot } from "@/lib/board";
import type { EntityDossier } from "@/lib/entities";
import type { Thread, ThreadPlace } from "@/lib/threads";
import type { CountryLink, GlobePoint, NewsArticle } from "@/types/news";

function snapshot(fields: Partial<PinSnapshot> & { title: string }): PinSnapshot {
  return (
    toSnapshot(fields) ?? {
      title: "Untitled",
      place: null,
      lat: null,
      lng: null,
      time: null,
      url: null,
    }
  );
}

const newest = (times: readonly string[]) =>
  times.reduce<string | null>(
    (best, t) =>
      Number.isFinite(Date.parse(t)) && (best === null || Date.parse(t) > Date.parse(best))
        ? t
        : best,
    null,
  );

/** A place: its name (or coordinates) where its dot is, as of its newest story. */
export function placeSnapshot(point: GlobePoint): PinSnapshot {
  const name = point.locationName?.trim() || null;
  return snapshot({
    title: name ?? `${point.lat.toFixed(2)}°, ${point.lng.toFixed(2)}°`,
    place: name,
    lat: point.lat,
    lng: point.lng,
    time: newest(point.articles.map((a) => a.publishedAt)) ?? point.lead?.publishedAt ?? null,
  });
}

/** A story: its headline, place, coordinates, time and web link. */
export function articleSnapshot(article: NewsArticle, place?: string): PinSnapshot {
  return snapshot({
    title: article.title,
    place: article.region?.trim() || place || null,
    lat: article.latitude,
    lng: article.longitude,
    time: article.publishedAt,
    url: article.sourceUrl,
  });
}

/** Two countries covered together: "France and United Kingdom", in code order as the server says. */
export function linkSnapshot(link: CountryLink): PinSnapshot {
  const [a, b] = [link.a, link.b].sort((x, y) => (x.iso < y.iso ? -1 : 1));
  return snapshot({ title: `${a.name} and ${b.name}` });
}

/** A thread: its title, where it was first reported, and its last story's time. */
export function threadSnapshot(thread: Thread & { spread?: readonly ThreadPlace[] }): PinSnapshot {
  const first = (thread.spread ?? thread.places)[0];
  return snapshot({
    title: thread.title,
    place: first?.place ?? null,
    lat: first?.lat ?? null,
    lng: first?.lng ?? null,
    time: thread.lastSeen,
  });
}

/** A person or organisation: the dossier's spelling, and its top place. */
export function entitySnapshot(dossier: EntityDossier): PinSnapshot {
  const top = dossier.places[0];
  return snapshot({
    title: dossier.name,
    place: top?.place ?? null,
    lat: top?.lat ?? null,
    lng: top?.lng ?? null,
  });
}
