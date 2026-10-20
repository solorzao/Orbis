"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { GlobeInstance } from "globe.gl";
import type { CountryLink, GlobePoint } from "@/types/news";
import {
  GLOBE_OVERSCAN_PX,
  HEATMAP,
  canvasColor,
  HOME_VIEW,
  driftLng,
  durationMs,
  heatColor,
  heatmapPoints,
  hexToRgba,
  recomputeHeatmap,
  showDots,
  projectedRadius,
  ringFade,
  ringRepeatMs,
  type GlobeGeometry,
} from "@/lib/globeView";
import type { ScreenPoint } from "@/lib/hoverCard";
import { ARC_ALTITUDE_SCALE, arcDashTime, arcFlows, linkArcs, type GlobeArc } from "@/lib/links";
import { revealedArcs, spreadArcs, type ThreadPlace } from "@/lib/threads";
import { webGpuReady } from "@/lib/webgpu";
import type { GlobeLayer } from "@/components/LayerSwitcher";

/** How high the dots stand off the globe (in globe radii). */
const DOT_ALTITUDE = 0.01;
const NO_DOTS: GlobePoint[] = [];
const NO_LINKS: CountryLink[] = [];
const NO_ALERTS: readonly { lat: number; lng: number }[] = [];
const NO_ARCS: GlobeArc[] = [];

// Natural Earth 1:110m countries without Antarctica, self-hosted and cached as
// immutable: a changed file gets a new version (see public/geo/README.md).
const LAND_URL = "/geo/land-110m.v1.geojson";

export interface GlobeControls {
  /** Move the camera there over 1500 ms, or `ms` (0: at once, for reduced motion). */
  flyTo: (lat: number, lng: number, altitude: number, ms?: number) => void;
  /** Where the globe sits on screen (for the orbital rings), or null once torn down. */
  getGeometry: () => GlobeGeometry | null;
  /**
   * Where a place's dot is on screen, or null on the globe's far side (the
   * hover card's HUD). With an altitude (in globe radii), a point above it:
   * the top of an arc, for its pill.
   */
  project: (lat: number, lng: number, altitude?: number) => ScreenPoint | null;
}

interface GlobeProps {
  points: GlobePoint[];
  onPointClick: (point: GlobePoint) => void;
  /** The dot under the pointer, or null when it leaves the dots. */
  onPointHover?: (point: GlobePoint | null) => void;
  /** A click or tap on the globe that hit no dot (or ended a drag). */
  onEmptyClick?: () => void;
  onZoomChange: (altitude: number) => void;
  onReady?: (controls: GlobeControls) => void;
  /** prefers-reduced-motion: the globe holds still. */
  reduced?: boolean;
  /** Low-power mode: the globe holds still. */
  lowPower?: boolean;
  /** A touch-only screen: the arcs' dashes hold still. */
  touch?: boolean;
  /** Dots (the default) or Intensity, a heatmap of the same places; dots hide under it. */
  layer?: GlobeLayer;
  /**
   * Hold Intensity's heatmap while a replay plays or dots load: without WebGPU
   * each recompute blocks the page, so it recomputes once when released.
   */
  holdHeatmap?: boolean;
  /** A replay is playing: on the main-thread path the dots show over the held heatmap. */
  replaying?: boolean;
  /** The Links layer's links, drawn as arcs (none while it is off). */
  links?: CountryLink[];
  /** Places breaking now (useBreaking): only they pulse, in --signal-warning. */
  alerts?: readonly { lat: number; lng: number }[];
  /** The inspected link's linkKey: its arc takes the highlight colour. */
  inspectedLink?: string | null;
  /** The link whose arc is under the pointer, or null when it leaves the arcs. */
  onArcHover?: (link: CountryLink | null) => void;
  onArcClick?: (link: CountryLink) => void;
  /** The selected thread: its spread drawn as aurora arcs, first place to each later one. */
  thread?: { id: number; spread: readonly ThreadPlace[] } | null;
  /** While its spread replays, the places lit so far: only their arcs show (null: all). */
  threadLit?: number | null;
  /** The visitor pressed or scrolled the globe (to leave the camera where they put it). */
  onGrab?: () => void;
}

interface LandFeature {
  properties: { ISO_A2?: string };
}

/** Soft Orbit tokens for the WebGL scene, read once: a canvas can't use CSS variables. */
function readGlobeTokens() {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    ocean: token("--globe-ocean", "#151433"),
    land: token("--globe-land", "#6f78c9"),
    atmosphere: token("--globe-atmosphere", "#8fb4ff"),
    driftMs: durationMs(token("--dur-drift", "40000ms"), 40000),
    warning: canvasColor(token("--signal-warning", ""), "#f5c27a"),
    arcs: {
      coverage: canvasColor(token("--arc-coverage", ""), "rgba(180, 190, 255, 0.30)"),
      highlight: canvasColor(token("--arc-highlight", ""), "#7fe6ff"),
      flowMs: durationMs(token("--dur-arc-flow", "6000ms"), 6000),
    },
    // The active thread's arcs (tokens.md "Aurora gradient"): faint cyan to lavender.
    spread: {
      aurora: [
        canvasColor(token("--aurora-start", ""), "#00d4ff", 0.25),
        canvasColor(token("--aurora-mid", ""), "#8b9cff"),
        canvasColor(token("--aurora-end", ""), "#c3a6ff"),
      ],
      flowMs: durationMs(token("--dur-arc-flow", "6000ms"), 6000),
    },
  };
}

export default function Globe({
  points,
  onPointClick,
  onPointHover,
  onEmptyClick,
  onZoomChange,
  onReady,
  reduced = false,
  lowPower = false,
  touch = false,
  layer = "dots",
  holdHeatmap = false,
  replaying = false,
  links = NO_LINKS,
  alerts = NO_ALERTS,
  inspectedLink = null,
  onArcHover,
  onArcClick,
  thread = null,
  threadLit = null,
  onGrab,
}: GlobeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const globeRef = useRef<GlobeInstance | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  // The visitor is dragging the globe: the arcs' dashes pause until they let go.
  const [dragging, setDragging] = useState(false);

  const onPointClickRef = useRef(onPointClick);
  onPointClickRef.current = onPointClick;

  const onPointHoverRef = useRef(onPointHover);
  onPointHoverRef.current = onPointHover;

  const onEmptyClickRef = useRef(onEmptyClick);
  onEmptyClickRef.current = onEmptyClick;

  const onArcHoverRef = useRef(onArcHover);
  onArcHoverRef.current = onArcHover;

  const onArcClickRef = useRef(onArcClick);
  onArcClickRef.current = onArcClick;

  const onGrabRef = useRef(onGrab);
  onGrabRef.current = onGrab;

  // The tokens the scene was built with, for the effects that redraw it.
  const tokensRef = useRef<ReturnType<typeof readGlobeTokens> | null>(null);
  // The arcs last built for the links and for the thread: kept while their
  // inputs hold, so a replay step or a new link list leaves the other's arc
  // objects (and three-globe's meshes and dash phase) as they were.
  const linkArcsRef = useRef<{ key: unknown[]; arcs: GlobeArc[] } | null>(null);
  const threadArcsRef = useRef<{ key: unknown[]; arcs: GlobeArc[] } | null>(null);
  // What each step of the thread's last replay drew ("lit:arcs"), for the e2e tests.
  const replayLogRef = useRef<{ thread: number; steps: string[] } | null>(null);

  const onZoomChangeRef = useRef(onZoomChange);
  onZoomChangeRef.current = onZoomChange;

  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  const motionRef = useRef({ reduced, lowPower });
  motionRef.current = { reduced, lowPower };

  const altitudeRef = useRef(HOME_VIEW.altitude);
  const pointsRef = useRef(points);
  pointsRef.current = points;
  // Whether dots are drawn (the Dots layer, or over a held heatmap during a replay).
  const dotsShownRef = useRef(layer === "dots");
  // The dots the heatmap on screen was computed from, so the same ones never recompute.
  const heatForRef = useRef<GlobePoint[] | null>(null);
  const zoomTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Once the visitor grabs, scrolls or flies the globe, the drift is over for good.
  const driftStoppedRef = useRef(false);
  const teardownRef = useRef<(() => void) | null>(null);

  const initGlobe = useCallback(async () => {
    if (!containerRef.current || globeRef.current) return;

    const GlobeGL = (await import("globe.gl")).default;
    // Unmounted while loading, or Strict Mode's second mount got there first.
    if (!containerRef.current || globeRef.current) return;
    const container = containerRef.current;
    const tokens = readGlobeTokens();
    tokensRef.current = tokens;
    // Set when globe.gl reports a dot (or arc) click, for the empty-click check below.
    let pointClicked = false;

    const globe = new GlobeGL(container, { animateIn: false })
      .backgroundColor("rgba(0,0,0,0)")
      .showAtmosphere(true)
      .atmosphereColor(tokens.atmosphere)
      .atmosphereAltitude(0.24)
      // Dotted land over a plain night ocean (no textures)
      .hexPolygonResolution(3)
      .hexPolygonMargin(0.42)
      .hexPolygonUseDots(true)
      .hexPolygonAltitude(0.003)
      .hexPolygonColor(() => hexToRgba(tokens.land, 0.55))
      .pointsData([])
      .pointLat("lat")
      .pointLng("lng")
      .pointRadius((d: object) => {
        const p = d as GlobePoint;
        const alt = altitudeRef.current;
        // Constant apparent size: dots shrink in globe-units as you zoom in
        // so they don't overlap when the surface expands visually
        const base = 0.15 + Math.log2(Math.max(1, p.count)) * 0.06;
        // Scale down more aggressively at close zoom so dots don't dominate
        const scale = alt < 1 ? alt : Math.sqrt(alt);
        return Math.max(0.04, base * scale);
      })
      .pointColor("color")
      .pointAltitude(DOT_ALTITUDE)
      .pointResolution(12)
      // Rings pulse at the places breaking now, alerts only (mockup): fading
      // --signal-warning, spreading wider than a dot (mockup initGlobe).
      .ringsData([])
      .ringLat("lat")
      .ringLng("lng")
      .ringColor(() => ringFade(tokens.warning))
      // Intensity (mockup initGlobe): a heatmap weighted by each place's story count
      .heatmapPointLat("lat")
      .heatmapPointLng("lng")
      .heatmapPointWeight("count")
      .heatmapColorFn(() => heatColor) // an accessor: each heatmap gets the Soft Orbit ramp
      .heatmapBandwidth(HEATMAP.bandwidth)
      .heatmapColorSaturation(HEATMAP.colorSaturation)
      .heatmapBaseAltitude(HEATMAP.baseAltitude)
      .heatmapTopAltitude(HEATMAP.topAltitude)
      .ringMaxRadius(4.5)
      .ringPropagationSpeed(1.4)
      .ringRepeatPeriod(ringRepeatMs(motionRef.current))
      // No pointLabel: the hover card (HoverCard, GlobeHud) replaces the tooltip.
      .onPointHover((point: object | null) => {
        onPointHoverRef.current?.((point as GlobePoint | null) ?? null);
      })
      .onPointClick((point: object) => {
        pointClicked = true;
        onPointClickRef.current(point as GlobePoint);
      })
      // Links (lib/links): co-coverage arcs, each an object from linkArcs
      .arcsData([])
      .arcStartLat("startLat")
      .arcStartLng("startLng")
      .arcEndLat("endLat")
      .arcEndLng("endLng")
      .arcColor("color")
      .arcStroke("stroke")
      .arcDashLength("dashLength")
      .arcDashGap("dashGap")
      .arcDashAnimateTime("dashAnimateTime")
      .arcAltitudeAutoScale(ARC_ALTITUDE_SCALE)
      .arcsTransitionDuration(0)
      // No arcLabel: the arc pill (ArcPill) names the hovered link.
      .onArcHover((arc: object | null) => {
        onArcHoverRef.current?.((arc as GlobeArc | null)?.link ?? null);
      })
      .onArcClick((arc: object) => {
        pointClicked = true;
        const link = (arc as GlobeArc).link; // a thread's arcs open nothing
        if (link) onArcClickRef.current?.(link);
      })
      .onZoom((pov: { lat: number; lng: number; altitude: number }) => {
        // The drift moves the camera every frame without zooming; only a real
        // altitude change needs the point radii re-evaluated.
        if (Math.abs(pov.altitude - altitudeRef.current) < 1e-6) return;
        altitudeRef.current = pov.altitude;
        onZoomChangeRef.current(pov.altitude);
        // Debounce: re-set pointsData to force pointRadius re-evaluation
        if (zoomTimerRef.current) clearTimeout(zoomTimerRef.current);
        zoomTimerRef.current = setTimeout(() => {
          if (globeRef.current && dotsShownRef.current) {
            globeRef.current.pointsData([...pointsRef.current]);
          }
        }, 150);
      });

    // Initial camera position
    globe.pointOfView(HOME_VIEW);

    // Customize controls for smooth interaction
    const controls = globe.controls();
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    controls.rotateSpeed = 0.6;
    controls.zoomSpeed = 0.8;
    controls.minDistance = 120;
    controls.maxDistance = 600;

    // Night ocean (mockup initGlobe)
    const mat = globe.globeMaterial();
    mat.color.set(tokens.ocean);
    mat.emissive.set("#1a1640");
    mat.emissiveIntensity = 0.35;
    mat.shininess = 8;

    globeRef.current = globe;
    setIsLoaded(true);

    // Land dots. Without them the plain ocean sphere still works.
    fetch(LAND_URL)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ features: LandFeature[] }>;
      })
      .then((geo) => {
        globeRef.current?.hexPolygonsData(geo.features.filter((f) => f.properties.ISO_A2 !== "AQ"));
      })
      .catch((err) => {
        console.warn("Globe: land outlines unavailable, showing the plain ocean.", err);
      });

    // A click that hit no dot. globe.gl reports dot clicks on the frame after
    // pointerup (and ignores clicks on empty space), so look one frame later,
    // after it has: its pointerup listener runs first (capture, on an inner element).
    let emptyFrame = 0;
    const checkEmptyClick = () => {
      pointClicked = false;
      cancelAnimationFrame(emptyFrame);
      emptyFrame = requestAnimationFrame(() => {
        if (!pointClicked) onEmptyClickRef.current?.();
      });
    };
    container.addEventListener("pointerup", checkEmptyClick);

    // Calm drift: +-5 degrees of longitude and back over --dur-drift, until the
    // visitor touches the globe. Never with reduced motion or in low-power mode.
    const stopDrift = () => {
      driftStoppedRef.current = true;
      onGrabRef.current?.();
    };
    container.addEventListener("pointerdown", stopDrift);
    // A press on the globe may become a drag: the arcs pause until it ends, wherever.
    // A release can also be lost: the window loses focus mid-drag, or the
    // canvas loses its pointer capture.
    const grab = () => setDragging(true);
    const release = () => setDragging(false);
    container.addEventListener("pointerdown", grab);
    container.addEventListener("lostpointercapture", release);
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    window.addEventListener("blur", release);
    container.addEventListener("wheel", stopDrift, { passive: true });
    let driftFrame = 0;
    const driftStart = performance.now();
    const drift = (now: number) => {
      const motion = motionRef.current;
      if (driftStoppedRef.current || motion.reduced || motion.lowPower || !globeRef.current) {
        driftStoppedRef.current = true;
        return;
      }
      globeRef.current.pointOfView(
        { ...HOME_VIEW, lng: HOME_VIEW.lng + driftLng(now - driftStart, tokens.driftMs) },
        0,
      );
      driftFrame = requestAnimationFrame(drift);
    };
    driftFrame = requestAnimationFrame(drift);

    // Expose camera controls to parent
    onReadyRef.current?.({
      flyTo: (lat: number, lng: number, altitude: number, ms = 1500) => {
        // The fly-to owns the camera now; the drift would pull it back.
        driftStoppedRef.current = true;
        globeRef.current?.pointOfView({ lat, lng, altitude }, ms);
      },
      getGeometry: () => {
        const g = globeRef.current;
        if (!g) return null;
        // The container is the canvas: full width, GLOBE_OVERSCAN_PX taller than the viewport.
        const r = container.getBoundingClientRect();
        return {
          cx: r.left + r.width / 2,
          cy: r.top + r.height / 2,
          R: projectedRadius(r.height, g.camera().fov, g.pointOfView().altitude),
        };
      },
      project: (lat: number, lng: number, altitude?: number) => {
        const g = globeRef.current;
        if (!g) return null;
        // Facing the camera (mockup `facing`): a little past the limb counts as hidden.
        const p = g.getCoords(lat, lng, altitude ?? 0);
        const c = g.camera().position;
        if (p.x * c.x + p.y * c.y + p.z * c.z <= g.getGlobeRadius() ** 2 * 1.02) return null;
        const s = g.getScreenCoords(lat, lng, altitude ?? DOT_ALTITUDE);
        if (!Number.isFinite(s.x) || !Number.isFinite(s.y)) return null;
        const r = container.getBoundingClientRect();
        return { x: r.left + s.x, y: r.top + s.y };
      },
    });

    // Handle resize
    const handleResize = () => {
      if (globeRef.current) {
        globeRef.current.width(window.innerWidth);
        globeRef.current.height(window.innerHeight + GLOBE_OVERSCAN_PX);
      }
    };
    window.addEventListener("resize", handleResize);
    handleResize();

    teardownRef.current = () => {
      cancelAnimationFrame(driftFrame);
      cancelAnimationFrame(emptyFrame);
      container.removeEventListener("pointerup", checkEmptyClick);
      window.removeEventListener("resize", handleResize);
      container.removeEventListener("pointerdown", stopDrift);
      container.removeEventListener("pointerdown", grab);
      container.removeEventListener("lostpointercapture", release);
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
      window.removeEventListener("blur", release);
      container.removeEventListener("wheel", stopDrift);
    };
  }, []);

  useEffect(() => {
    initGlobe();
    return () => {
      teardownRef.current?.();
      teardownRef.current = null;
      if (zoomTimerRef.current) clearTimeout(zoomTimerRef.current);
      if (globeRef.current) {
        globeRef.current._destructor();
        globeRef.current = null;
      }
    };
  }, [initGlobe]);

  // Ring pulses stop with reduced motion or in low-power mode (both can change after load)
  useEffect(() => {
    if (globeRef.current && isLoaded) {
      const repeat = ringRepeatMs({ reduced, lowPower });
      globeRef.current.ringRepeatPeriod(repeat);
      if (containerRef.current) containerRef.current.dataset.ringRepeat = String(repeat); // e2e
    }
  }, [reduced, lowPower, isLoaded]);

  // The breaking places' rings, only while they may pulse: with a repeat
  // period of 0 three-globe still draws one ring per place (and again on each
  // refresh), so held still there are none. The ticker still lists the stories.
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe || !isLoaded) return;
    const pulse = ringRepeatMs({ reduced, lowPower }) > 0;
    const rings = pulse ? alerts.map(({ lat, lng }) => ({ lat, lng })) : [];
    globe.ringsData(rings);
    if (containerRef.current) containerRef.current.dataset.rings = String(rings.length); // e2e
  }, [alerts, reduced, lowPower, isLoaded]);

  // The arcs: the Links layer's (the inspected one highlighted) and the
  // selected thread's spread (aurora, as far as a replay has lit it), flowing
  // when motion allows. New arc objects make three-globe build new meshes, so
  // a drag doesn't come through here (see the next effect), and each set's
  // objects are kept while its own inputs hold.
  useEffect(() => {
    const globe = globeRef.current;
    const container = containerRef.current;
    const tokens = tokensRef.current;
    if (!globe || !isLoaded || !tokens) return;
    const flow = arcFlows({ reduced, lowPower, touch });
    const same = (a: unknown[], b: unknown[] | undefined) =>
      b !== undefined && a.length === b.length && a.every((x, i) => x === b[i]);
    const linkKey = [links, inspectedLink, flow];
    if (!same(linkKey, linkArcsRef.current?.key)) {
      linkArcsRef.current = {
        key: linkKey,
        arcs: linkArcs(links, { inspected: inspectedLink, colors: tokens.arcs, flow }),
      };
    }
    const threadKey = [thread?.id, thread?.spread, flow];
    if (!same(threadKey, threadArcsRef.current?.key)) {
      threadArcsRef.current = {
        key: threadKey,
        arcs: thread
          ? spreadArcs(thread.id, thread.spread, { colors: tokens.spread, flow })
          : NO_ARCS,
      };
    }
    const linked = linkArcsRef.current!.arcs;
    const spread = revealedArcs(threadArcsRef.current!.arcs, threadLit);
    const arcs = [...linked, ...spread];
    globe.arcsData(arcs);
    if (container) {
      // read by the e2e tests: WebGL arcs can't be found in the DOM
      container.dataset.arcs = String(linked.length);
      // The arc drawn highlighted, if any (not the inspected link, which may not be drawn).
      container.dataset.arcHighlight =
        linked.find((a) => a.color === tokens.arcs.highlight)?.key ?? "";
      container.dataset.threadArcs = String(spread.length);
      // Each replay step as drawn, "1:0,2:1,…": a step at or before the last starts a new replay.
      if (thread && threadLit !== null) {
        const log = replayLogRef.current;
        const last = log?.thread === thread.id ? log.steps.at(-1) : undefined;
        const step = `${threadLit}:${spread.length}`;
        if (step !== last) {
          const fresh = !last || threadLit <= Number(last.split(":")[0]);
          replayLogRef.current = {
            thread: thread.id,
            steps: fresh ? [step] : [...log!.steps, step],
          };
        }
      } else if (!thread) {
        replayLogRef.current = null;
      }
      container.dataset.threadReplay = replayLogRef.current?.steps.join(",") ?? "";
      container.dataset.arcDashed = String(arcs.some((a) => a.dashGap > 0));
      // how many times arcs were drawn: pausing them must not redraw any
      container.dataset.arcsDrawn = String(Number(container.dataset.arcsDrawn ?? 0) + 1);
    }
  }, [links, inspectedLink, thread, threadLit, reduced, lowPower, touch, isLoaded]);

  // A drag pauses the arcs' dashes in place: only the accessor changes, so
  // three-globe keeps each mesh, its dash pattern and where its dashes are.
  useEffect(() => {
    const globe = globeRef.current;
    const container = containerRef.current;
    if (!globe || !isLoaded) return;
    globe.arcDashAnimateTime(arcDashTime(dragging) as (arc: object) => number);
    if (container) {
      const drawn = links.length > 0 || (thread?.spread.length ?? 0) > 1;
      container.dataset.arcFlow = String(arcFlows({ reduced, lowPower, touch, dragging }) && drawn);
    }
  }, [dragging, links, thread, reduced, lowPower, touch, isLoaded]);

  // The active layer's data: dots and their rings, or the Intensity heatmap
  useEffect(() => {
    const globe = globeRef.current;
    const container = containerRef.current;
    if (!globe || !isLoaded) return;
    const drawDots = (dots: GlobePoint[], overHeatmap = false) => {
      dotsShownRef.current = dots.length > 0;
      // Over the heatmap, the dots sit above its highest bump so the heat can't wash them out.
      globe.pointAltitude(overHeatmap ? HEATMAP.topAltitude + 0.005 : DOT_ALTITUDE);
      globe.pointsData(dots);
      if (container) container.dataset.dots = String(dots.length); // read by the e2e tests
    };
    if (layer === "dots") {
      heatForRef.current = null;
      globe.heatmapsData([]);
      drawDots(points);
      return;
    }
    let cancelled = false;
    let settle: ReturnType<typeof setTimeout> | undefined;
    // three-globe builds the heatmap's sphere on its next update (a 1 ms debounce).
    // Its material is transparent but writes depth, which hides the land dots
    // under it everywhere, even where the heat is clear: turn that off. Under a
    // replay's dots the frozen heatmap dims to a backdrop so the dots read.
    // This reaches into three-globe internals (the __globeObjType tag, the
    // debounce, one mesh per heatmap) as of 2.45.0: package.json pins globe.gl
    // and the lockfile its three-globe. Re-check Intensity over land on upgrade.
    const tuneHeatmap = (dim: boolean) =>
      globeRef.current?.scene().traverse((obj: object) => {
        const mesh = obj as {
          __globeObjType?: string;
          material?: { depthWrite: boolean; opacity: number };
        };
        if (mesh.__globeObjType !== "heatmap" || !mesh.material) return;
        mesh.material.depthWrite = false;
        mesh.material.opacity = dim ? HEATMAP.dimmedOpacity : 1;
      });
    // Probe WebGPU first: it decides how many places the heatmap can afford.
    webGpuReady().then((gpu) => {
      if (cancelled || !globeRef.current) return;
      const overlay = showDots(layer, { replaying, cpuPath: !gpu });
      drawDots(overlay ? points : NO_DOTS, true);
      tuneHeatmap(overlay);
      const shown = heatForRef.current !== null;
      if (shown && (heatForRef.current === points || !recomputeHeatmap({ gpu, hold: holdHeatmap })))
        return;
      heatForRef.current = points;
      const heat = heatmapPoints(points, { gpu });
      globeRef.current.heatmapsData(heat.length ? [heat] : []);
      settle = setTimeout(() => tuneHeatmap(overlay), 50);
    });
    return () => {
      cancelled = true;
      clearTimeout(settle);
    };
  }, [points, layer, holdHeatmap, replaying, isLoaded]);

  return (
    <div
      ref={containerRef}
      data-testid="globe"
      data-dot-colors={[...new Set(points.map((p) => p.color))].sort().join(" ")}
      className="fixed inset-x-0 bottom-0"
      style={{ top: -GLOBE_OVERSCAN_PX, zIndex: "var(--z-globe)" }}
    />
  );
}
