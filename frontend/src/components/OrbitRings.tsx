"use client";

import { useEffect, useId, useState } from "react";
import type { GlobeGeometry } from "@/lib/globeView";

interface OrbitRingsProps {
  /** The globe's on-screen centre and radius, or null before it renders. */
  getGeometry: () => GlobeGeometry | null;
  reduced: boolean;
  lowPower: boolean;
}

const round = (g: GlobeGeometry): GlobeGeometry => ({
  cx: Math.round(g.cx),
  cy: Math.round(g.cy),
  R: Math.round(g.R),
});

const sameGeometry = (a: GlobeGeometry | null, b: GlobeGeometry | null) =>
  a === b || (!!a && !!b && a.cx === b.cx && a.cy === b.cy && a.R === b.R);

/**
 * Orbital rings around the globe (mockup `renderOrbits`): a dashed ring at
 * 1.08R with ticks every 15 degrees, and two tilted orbits whose far halves
 * pass behind the globe. Satellites fly only with full motion.
 *
 * The globe moves without telling React (drag, zoom, resize), so this polls
 * its geometry each frame and re-renders only when it moves a whole pixel.
 */
export default function OrbitRings({ getGeometry, reduced, lowPower }: OrbitRingsProps) {
  const [geometry, setGeometry] = useState<GlobeGeometry | null>(null);
  const ids = useId().replace(/[^a-zA-Z0-9_-]/g, "");

  useEffect(() => {
    let frame = 0;
    let last: GlobeGeometry | null = null;
    const tick = () => {
      const g = getGeometry();
      const next = g ? round(g) : null;
      if (!sameGeometry(next, last)) {
        last = next;
        setGeometry(next);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [getGeometry]);

  if (!geometry) return null;

  const { cx, cy, R } = geometry;
  const behind = `${ids}-behind`;
  const satellites = !reduced && !lowPower;

  const ticks = [];
  for (let d = 0; d < 360; d += 15) {
    const a = (d * Math.PI) / 180;
    const r0 = R * 1.08;
    const r1 = r0 + (d % 90 === 0 ? 8 : 4);
    ticks.push(
      <line
        key={d}
        x1={cx + r0 * Math.cos(a)}
        y1={cy + r0 * Math.sin(a)}
        x2={cx + r1 * Math.cos(a)}
        y2={cy + r1 * Math.sin(a)}
        stroke="var(--orbit-tick)"
      />,
    );
  }

  const orbit = (rx: number, ry: number, rotate: number, name: string, periodS: number) => {
    const pathId = `${ids}-${name}`;
    // The upper half is the far side: masked where it crosses the globe.
    const back = `M${cx - rx} ${cy} A${rx} ${ry} 0 0 1 ${cx + rx} ${cy}`;
    const front = `M${cx + rx} ${cy} A${rx} ${ry} 0 0 1 ${cx - rx} ${cy}`;
    const full = `M${cx - rx} ${cy} A${rx} ${ry} 0 1 1 ${cx + rx} ${cy} A${rx} ${ry} 0 1 1 ${cx - rx} ${cy}`;
    return (
      <g className="orbit" transform={`rotate(${rotate} ${cx} ${cy})`}>
        <path d={back} fill="none" stroke="var(--orbit-ring)" mask={`url(#${behind})`} />
        <path d={front} fill="none" stroke="var(--orbit-ring)" />
        <path id={pathId} d={full} fill="none" stroke="none" />
        {satellites && (
          <circle r="2.4" fill="var(--orbit-reticle)" opacity="0.9">
            <animateMotion dur={`${periodS}s`} repeatCount="indefinite">
              <mpath href={`#${pathId}`} />
            </animateMotion>
          </circle>
        )}
      </g>
    );
  };

  return (
    <svg className="orbits" aria-hidden="true" focusable="false">
      <defs>
        <mask id={behind} maskUnits="userSpaceOnUse">
          <rect x="0" y="0" width="100%" height="100%" fill="#fff" />
          <circle cx={cx} cy={cy} r={R * 1.01} fill="#000" />
        </mask>
      </defs>
      <circle
        cx={cx}
        cy={cy}
        r={R * 1.08}
        fill="none"
        stroke="var(--orbit-ring)"
        strokeDasharray="1 5"
      />
      {ticks}
      {orbit(R * 1.32, R * 0.34, -16, "o1", 90)}
      {orbit(R * 1.22, R * 0.3, 24, "o2", 130)}
    </svg>
  );
}
