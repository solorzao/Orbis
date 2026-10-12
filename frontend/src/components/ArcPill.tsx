"use client";

import { useEffect, useRef } from "react";
import { arcApex, arcPillText, linkEnds } from "@/lib/links";
import type { ScreenPoint } from "@/lib/hoverCard";
import type { CountryLink } from "@/types/news";

interface ArcPillProps {
  /** The hovered link, else the inspected one, or null: no pill, no frame loop. */
  link: CountryLink | null;
  /** Where a point above the globe is on screen, or null on its far side. */
  project: (lat: number, lng: number, altitude?: number) => ScreenPoint | null;
  /** A touch screen ((hover: none)): CSS hides the pill, so it runs no frame loop either. */
  touch?: boolean;
}

/**
 * The floating pill that names a link at the top of its arc (mockup
 * .arc-pill): "41 stories link United States and Iran, mostly politics".
 * The globe moves without telling React, so a requestAnimationFrame loop
 * places it (only while it shows), and hides it while the arc's top is on
 * the far side. It lets the pointer through to the arc beneath, and is
 * hidden from screen readers: the link inspector says the same to everyone.
 */
export default function ArcPill({ link, project, touch = false }: ArcPillProps) {
  const ref = useRef<HTMLDivElement>(null);
  const shown = touch ? null : link;
  const [start, end] = shown ? linkEnds(shown) : [null, null];
  const startLat = start?.lat;
  const startLng = start?.lng;
  const endLat = end?.lat;
  const endLng = end?.lng;

  useEffect(() => {
    if (startLat === undefined || startLng === undefined) return;
    if (endLat === undefined || endLng === undefined) return;
    const apex = arcApex({ lat: startLat, lng: startLng }, { lat: endLat, lng: endLng });
    let frame = 0;
    const tick = () => {
      const pill = ref.current;
      if (pill) {
        const p = project(apex.lat, apex.lng, apex.altitude);
        if (p) {
          pill.style.left = `${Math.round(p.x)}px`;
          pill.style.top = `${Math.round(p.y)}px`;
          pill.dataset.placed = "true";
        } else {
          delete pill.dataset.placed;
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [startLat, startLng, endLat, endLng, project]);

  if (!shown) return null;
  const { n, text } = arcPillText(shown);
  return (
    <div ref={ref} className="arc-pill" data-testid="arc-pill" aria-hidden="true">
      <span className="num">{n}</span> {text}
    </div>
  );
}
