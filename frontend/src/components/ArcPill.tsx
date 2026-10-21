"use client";

import { useEffect, useRef } from "react";
import { arcApex, type ArcPillLabel } from "@/lib/links";
import type { ScreenPoint } from "@/lib/hoverCard";

interface ArcPillProps {
  /**
   * The arc to name (lib/links linkPill, lib/relations relationPill): the
   * hovered one, else the focused or inspected one, or null: no pill, no frame loop.
   */
  label: ArcPillLabel | null;
  /** Where a point above the globe is on screen, or null on its far side. */
  project: (lat: number, lng: number, altitude?: number) => ScreenPoint | null;
  /** A touch screen ((hover: none)): CSS hides the pill, so it runs no frame loop either. */
  touch?: boolean;
}

/**
 * The floating pill that names an arc at its top (mockup .arc-pill): a link's
 * "41 stories link United States and Iran, mostly politics", or a relation's
 * "312 reported events between United States and Iran, mostly verbal conflict".
 * The globe moves without telling React, so a requestAnimationFrame loop
 * places it (only while it shows), and hides it while the arc's top is on
 * the far side. It lets the pointer through to the arc beneath, and is
 * hidden from screen readers: the inspectors say the same to everyone.
 */
export default function ArcPill({ label, project, touch = false }: ArcPillProps) {
  const ref = useRef<HTMLDivElement>(null);
  const shown = touch ? null : label;
  const startLat = shown?.start.lat;
  const startLng = shown?.start.lng;
  const endLat = shown?.end.lat;
  const endLng = shown?.end.lng;

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
  return (
    <div ref={ref} className="arc-pill" data-testid="arc-pill" aria-hidden="true">
      <span className="num">{shown.n}</span> {shown.text}
    </div>
  );
}
