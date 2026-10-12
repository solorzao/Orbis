"use client";

import { useEffect, useState, type RefObject } from "react";
import type { GlobeGeometry } from "@/lib/globeView";
import {
  cardMaxHeight,
  dockHoverCard,
  leaderPath,
  placeHoverCard,
  reticleRadius,
  type Box,
  type Chrome,
  type ScreenPoint,
} from "@/lib/hoverCard";
import type { GlobePoint } from "@/types/news";

/** What the HUD draws for the card's dot: the reticle, and the leader to a floating card. */
interface Hud {
  /** The dot it was drawn for. */
  key: string;
  x: number;
  y: number;
  r: number;
  leader: string | null;
}

const sameHud = (a: Hud | null, b: Hud | null) =>
  a === b ||
  (!!a &&
    !!b &&
    a.key === b.key &&
    a.x === b.x &&
    a.y === b.y &&
    a.r === b.r &&
    a.leader === b.leader);

function toBox(el: Element): Box | null {
  const visible =
    typeof (el as HTMLElement).checkVisibility !== "function" ||
    (el as HTMLElement).checkVisibility({
      checkVisibilityCSS: true,
      visibilityProperty: true,
    } as CheckVisibilityOptions);
  const r = el.getBoundingClientRect();
  return visible && r.width > 0 && r.height > 0
    ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom }
    : null;
}

const boxesOf = (selector: string) =>
  Array.from(document.querySelectorAll(selector), toBox).filter((b): b is Box => b !== null);

/**
 * The chrome on screen now (soft-orbit.css): the top bar, the side panel or
 * its reopen pill (the sheet below 1180px), and the bottom row.
 */
export function readChrome(): Chrome {
  return {
    top: boxesOf(".topbar"),
    side: boxesOf('[data-testid="side-panel"], [data-testid="side-open"]'),
    bottom: boxesOf(".bottombar"),
  };
}

interface GlobeHudProps {
  /** The dot whose card is shown, or null: no card, no frame loop. */
  point: GlobePoint | null;
  /** Where a place is on screen, or null when it is on the globe's far side. */
  project: (lat: number, lng: number) => ScreenPoint | null;
  getGeometry: () => GlobeGeometry | null;
  /** The card to place (HoverCard). */
  cardRef: RefObject<HTMLElement | null>;
  /** Touch screens: the card docks above the bottom row, with no leader. */
  docked: boolean;
  reduced: boolean;
  getChrome?: () => Chrome;
}

/**
 * The hover card's HUD (mockup `frame`, lines 1356-1382): a soft reticle
 * that locks onto the card's dot, and a curved leader from it to the card,
 * which it also places (lib/hoverCard): beside the dot, clear of the chrome,
 * or docked on a touch screen. The globe moves without telling React (drag,
 * zoom, drift), so it follows the dot on a requestAnimationFrame loop, which
 * runs only while a card is shown. It positions the card directly, so the
 * card doesn't re-render each frame, and keeps it hidden while its dot is
 * on the globe's far side.
 */
export default function GlobeHud({
  point,
  project,
  getGeometry,
  cardRef,
  docked,
  reduced,
  getChrome = readChrome,
}: GlobeHudProps) {
  const [hud, setHud] = useState<Hud | null>(null);
  const lat = point?.lat;
  const lng = point?.lng;
  const key = point ? `${point.lat}:${point.lng}` : null;

  useEffect(() => {
    if (lat === undefined || lng === undefined) return;
    const dotKey = `${lat}:${lng}`;
    let frame = 0;
    let start: number | null = null;
    let last: Hud | null = null;

    const tick = (now: number) => {
      start ??= now;
      const card = cardRef.current;
      const dot = project(lat, lng);
      let next: Hud | null = null;
      if (dot) {
        const r = reticleRadius(now - start, reduced);
        const viewport = { width: window.innerWidth, height: window.innerHeight };
        const chrome = getChrome();
        let leader: string | null = null;
        if (card) {
          if (docked) {
            // The sheet docks the card above it too (below 1180px it is at the bottom).
            const sheet = chrome.side.filter((b) => b.top > viewport.height / 2);
            const dock = dockHoverCard({
              viewport,
              below: chrome.top,
              above: [...chrome.bottom, ...sheet],
            });
            Object.assign(card.style, {
              left: "",
              top: "",
              bottom: `${dock.bottom}px`,
              maxHeight: `${dock.maxHeight}px`,
            });
          } else {
            // Set the cap before measuring, so a tall card is placed at its capped height.
            const maxHeight = cardMaxHeight({
              viewport,
              below: chrome.top,
              above: chrome.bottom,
            });
            card.style.maxHeight = `${maxHeight}px`;
            const size = { width: card.offsetWidth, height: card.offsetHeight };
            const spot = placeHoverCard({
              dot,
              centreX: getGeometry()?.cx ?? viewport.width / 2,
              card: size,
              viewport,
              avoid: [...chrome.top, ...chrome.side, ...chrome.bottom],
            });
            Object.assign(card.style, {
              left: `${spot.left}px`,
              top: `${spot.top}px`,
              bottom: "",
            });
            leader = leaderPath(dot, r, {
              ...spot,
              right: spot.left + size.width,
              bottom: spot.top + size.height,
            });
          }
          card.dataset.placed = "true";
        }
        next = {
          key: dotKey,
          x: Math.round(dot.x),
          y: Math.round(dot.y),
          r: Math.round(r * 10) / 10,
          leader,
        };
      } else if (card) {
        delete card.dataset.placed; // its dot turned away: hide it until it is back
      }
      if (!sameHud(next, last)) {
        last = next;
        setHud(next);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [lat, lng, project, getGeometry, cardRef, docked, reduced, getChrome]);

  if (!hud || hud.key !== key) return null;
  const { x, y, r } = hud;
  return (
    <svg className="hud" aria-hidden="true" focusable="false">
      <circle cx={x} cy={y} r={r} fill="none" stroke="var(--orbit-reticle)" strokeOpacity="0.75" />
      <circle
        cx={x}
        cy={y}
        r={r + 7}
        fill="none"
        stroke="var(--orbit-reticle)"
        strokeOpacity="0.25"
      />
      {[0, 90, 180, 270].map((deg) => {
        const a = (deg * Math.PI) / 180;
        return (
          <line
            key={deg}
            x1={x + Math.cos(a) * (r + 3)}
            y1={y + Math.sin(a) * (r + 3)}
            x2={x + Math.cos(a) * (r + 11)}
            y2={y + Math.sin(a) * (r + 11)}
            stroke="var(--orbit-reticle)"
            strokeLinecap="round"
          />
        );
      })}
      {hud.leader && (
        <path
          className="leader"
          d={hud.leader}
          fill="none"
          stroke="var(--orbit-reticle)"
          strokeOpacity="0.5"
        />
      )}
    </svg>
  );
}
