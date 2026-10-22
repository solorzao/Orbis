"use client";

import { useEffect, useMemo, useRef } from "react";
import { arcApex } from "@/lib/links";
import {
  labelledRelations,
  relationEnds,
  relationKey,
  relationTag,
  type Relation,
} from "@/lib/relations";
import type { ScreenPoint } from "@/lib/hoverCard";

interface ArcLabelsProps {
  /** The relations drawn (none while the layer is off or unavailable). */
  relations: readonly Relation[];
  /** Another focus leads (an entity tracked, the board): the arcs are muted, unlabelled. */
  muted: boolean;
  /** The relation whose pill shows (hovered, focused or inspected): its label yields. */
  yieldTo: string | null;
  /** Where a point above the globe is on screen, or null on its far side. */
  project: (lat: number, lng: number, altitude?: number) => ScreenPoint | null;
  /** A phone's width (760px and below): CSS hides the labels, so it runs no frame loop either. */
  narrow?: boolean;
  /**
   * How many labels it has rendered in the DOM (placed or not), each time that
   * changes: the globe shows it as data-relation-labels for the e2e tests.
   */
  onCount?: (rendered: number) => void;
}

/**
 * The strongest relation arcs' persistent labels (decision 6): a small chip
 * at each arc's top, "US–IR · 312 · conflict", the class in words. One
 * requestAnimationFrame loop places them all, as ArcPill places its pill; a
 * label whose top is on the far side is hidden (still rendered). They let
 * the pointer through, and are hidden from screen readers: the keyboard list
 * and the inspector say the same to everyone. On phones it renders none (CSS
 * hides them there too), as ArcPill does on touch screens. Wherever the
 * legend and its caveat give way, so do they (soft-orbit.css).
 */
export default function ArcLabels({
  relations,
  muted,
  yieldTo,
  project,
  narrow = false,
  onCount,
}: ArcLabelsProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const shown = useMemo(
    () => (narrow ? [] : labelledRelations(relations, { muted, yieldTo })),
    [relations, muted, yieldTo, narrow],
  );

  // The labels in the DOM now, counted there rather than recomputed elsewhere.
  useEffect(() => {
    onCount?.(boxRef.current?.querySelectorAll(".arc-tag").length ?? 0);
  }, [shown, onCount]);
  // Each label's arc top, in the order they render.
  const apexes = useMemo(
    () =>
      shown.map((rel) => {
        const [start, end] = relationEnds(rel);
        return arcApex(start, end);
      }),
    [shown],
  );

  useEffect(() => {
    if (apexes.length === 0) return;
    let frame = 0;
    const tick = () => {
      const tags = boxRef.current?.querySelectorAll<HTMLElement>(".arc-tag") ?? [];
      tags.forEach((tag, i) => {
        const apex = apexes[i];
        const p = apex ? project(apex.lat, apex.lng, apex.altitude) : null;
        if (p) {
          tag.style.left = `${Math.round(p.x)}px`;
          tag.style.top = `${Math.round(p.y)}px`;
          tag.dataset.placed = "true";
        } else {
          delete tag.dataset.placed;
        }
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [apexes, project]);

  if (shown.length === 0) return null;
  return (
    <div ref={boxRef} className="arc-tags" data-testid="arc-labels" aria-hidden="true">
      {shown.map((rel) => {
        const key = relationKey(rel.a.iso, rel.b.iso);
        return (
          <span key={key} className={`arc-tag ${rel.kind}`} data-relation-tag={key}>
            {relationTag(rel)}
          </span>
        );
      })}
    </div>
  );
}
