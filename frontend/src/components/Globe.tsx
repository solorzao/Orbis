"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { GlobeInstance } from "globe.gl";
import { GlobePoint } from "@/types/news";
import {
  GLOBE_OVERSCAN_PX,
  HEATMAP,
  HOME_VIEW,
  driftLng,
  durationMs,
  hasWebGpu,
  heatmapPoints,
  hexToRgba,
  pointTooltipHtml,
  projectedRadius,
  ringRepeatMs,
  type GlobeGeometry,
} from "@/lib/globeView";
import type { GlobeLayer } from "@/components/LayerSwitcher";

// Natural Earth 1:110m countries without Antarctica, self-hosted and cached as
// immutable: a changed file gets a new version (see public/geo/README.md).
const LAND_URL = "/geo/land-110m.v1.geojson";

export interface GlobeControls {
  flyTo: (lat: number, lng: number, altitude: number) => void;
  /** Where the globe sits on screen (for the orbital rings), or null once torn down. */
  getGeometry: () => GlobeGeometry | null;
}

interface GlobeProps {
  points: GlobePoint[];
  onPointClick: (point: GlobePoint) => void;
  onZoomChange: (altitude: number) => void;
  onReady?: (controls: GlobeControls) => void;
  /** prefers-reduced-motion: the globe holds still. */
  reduced?: boolean;
  /** Low-power mode: the globe holds still. */
  lowPower?: boolean;
  /** Dots (the default) or Intensity, a heatmap of the same places; dots hide under it. */
  layer?: GlobeLayer;
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
  };
}

export default function Globe({
  points,
  onPointClick,
  onZoomChange,
  onReady,
  reduced = false,
  lowPower = false,
  layer = "dots",
}: GlobeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const globeRef = useRef<GlobeInstance | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const onPointClickRef = useRef(onPointClick);
  onPointClickRef.current = onPointClick;

  const onZoomChangeRef = useRef(onZoomChange);
  onZoomChangeRef.current = onZoomChange;

  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  const motionRef = useRef({ reduced, lowPower });
  motionRef.current = { reduced, lowPower };

  const altitudeRef = useRef(HOME_VIEW.altitude);
  const pointsRef = useRef(points);
  pointsRef.current = points;
  const layerRef = useRef(layer);
  layerRef.current = layer;
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
      .pointAltitude(0.01)
      .pointResolution(12)
      // Pulsing rings under each dot
      .ringsData([])
      .ringLat("lat")
      .ringLng("lng")
      .ringColor((d: object) => {
        const p = d as GlobePoint;
        // Return a function that fades opacity as ring expands (t: 0→1)
        return (t: number) => {
          const c = p.color || "#3b82f6";
          const opacity = Math.max(0, 0.4 * (1 - t));
          // Convert hex to rgba
          const r = parseInt(c.slice(1, 3), 16);
          const g = parseInt(c.slice(3, 5), 16);
          const b = parseInt(c.slice(5, 7), 16);
          return `rgba(${r},${g},${b},${opacity})`;
        };
      })
      // Intensity (mockup initGlobe): a heatmap weighted by each place's story count
      .heatmapPointLat("lat")
      .heatmapPointLng("lng")
      .heatmapPointWeight("count")
      .heatmapBandwidth(HEATMAP.bandwidth)
      .heatmapColorSaturation(HEATMAP.colorSaturation)
      .heatmapBaseAltitude(HEATMAP.baseAltitude)
      .heatmapTopAltitude(HEATMAP.topAltitude)
      .ringMaxRadius(2)
      .ringPropagationSpeed(1.2)
      .ringRepeatPeriod(ringRepeatMs(motionRef.current))
      .pointLabel((d: object) => pointTooltipHtml(d as GlobePoint))
      .onPointClick((point: object) => {
        onPointClickRef.current(point as GlobePoint);
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
          if (globeRef.current && layerRef.current === "dots") {
            const pts = [...pointsRef.current];
            globeRef.current.pointsData(pts);
            globeRef.current.ringsData(pts);
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

    // Calm drift: +-5 degrees of longitude and back over --dur-drift, until the
    // visitor touches the globe. Never with reduced motion or in low-power mode.
    const stopDrift = () => {
      driftStoppedRef.current = true;
    };
    container.addEventListener("pointerdown", stopDrift);
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
      flyTo: (lat: number, lng: number, altitude: number) => {
        // The fly-to owns the camera now; the drift would pull it back.
        driftStoppedRef.current = true;
        globeRef.current?.pointOfView({ lat, lng, altitude }, 1500);
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
      window.removeEventListener("resize", handleResize);
      container.removeEventListener("pointerdown", stopDrift);
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
      globeRef.current.ringRepeatPeriod(ringRepeatMs({ reduced, lowPower }));
    }
  }, [reduced, lowPower, isLoaded]);

  // The active layer's data: dots and their rings, or the Intensity heatmap
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe || !isLoaded) return;
    if (layer === "intensity") {
      globe.pointsData([]);
      globe.ringsData([]);
      const heat = heatmapPoints(points, { gpu: hasWebGpu() });
      globe.heatmapsData(heat.length ? [heat] : []);
    } else {
      globe.heatmapsData([]);
      globe.pointsData(points);
      globe.ringsData(points);
    }
  }, [points, layer, isLoaded]);

  return (
    <div
      ref={containerRef}
      data-testid="globe"
      className="fixed inset-x-0 bottom-0"
      style={{ top: -GLOBE_OVERSCAN_PX, zIndex: "var(--z-globe)" }}
    />
  );
}
