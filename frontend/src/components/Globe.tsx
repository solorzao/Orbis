"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { GlobeInstance } from "globe.gl";
import { GlobePoint } from "@/types/news";

interface GlobeProps {
  points: GlobePoint[];
  onPointClick: (point: GlobePoint) => void;
  onZoomChange: (altitude: number) => void;
}

export default function Globe({ points, onPointClick, onZoomChange }: GlobeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const globeRef = useRef<GlobeInstance | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const onPointClickRef = useRef(onPointClick);
  onPointClickRef.current = onPointClick;

  const onZoomChangeRef = useRef(onZoomChange);
  onZoomChangeRef.current = onZoomChange;

  const altitudeRef = useRef(2.5);
  const pointsRef = useRef(points);
  pointsRef.current = points;
  const zoomTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const initGlobe = useCallback(async () => {
    if (!containerRef.current || globeRef.current) return;

    const GlobeGL = (await import("globe.gl")).default;

    const globe = new GlobeGL(containerRef.current)
      .backgroundColor("rgba(0,0,0,0)")
      .globeImageUrl("/textures/earth-night-4k.jpg")
      .bumpImageUrl("/textures/earth-topology.png")
      .atmosphereColor("#1a3a5c")
      .atmosphereAltitude(0.15)
      .showAtmosphere(true)
      .pointsData([])
      .pointLat("lat")
      .pointLng("lng")
      .pointRadius((d: object) => {
        const p = d as GlobePoint;
        const alt = altitudeRef.current;
        // Constant apparent size: dots shrink in globe-units as you zoom in
        // so they don't overlap when the surface expands visually
        const base = 0.15 + Math.log2(Math.max(1, p.count)) * 0.06;
        return Math.max(0.08, base * Math.sqrt(alt));
      })
      .pointColor("color")
      .pointAltitude(0.01)
      .pointResolution(12)
      .pointLabel((d: object) => {
        const p = d as GlobePoint;
        const location = p.locationName || "";
        const label = location
          ? `<span style="color:${p.color};font-weight:600">${p.count} stories</span> <span style="color:#64748b">\u2022</span> ${location}`
          : `<span style="color:${p.color};font-weight:600">${p.count} stories</span>`;
        return `<div style="background:rgba(10,14,28,0.85);backdrop-filter:blur(12px);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:8px 12px;font-family:system-ui;color:#e2e8f0;font-size:12px;max-width:300px;pointer-events:none">${label}</div>`;
      })
      .onPointClick((point: object) => {
        onPointClickRef.current(point as GlobePoint);
      })
      .onZoom((pov: { lat: number; lng: number; altitude: number }) => {
        altitudeRef.current = pov.altitude;
        onZoomChangeRef.current(pov.altitude);
        // Debounce: re-set pointsData to force pointRadius re-evaluation
        if (zoomTimerRef.current) clearTimeout(zoomTimerRef.current);
        zoomTimerRef.current = setTimeout(() => {
          if (globeRef.current) {
            globeRef.current.pointsData([...pointsRef.current]);
          }
        }, 150);
      });

    // Initial camera position
    globe.pointOfView({ lat: 20, lng: 0, altitude: 2.5 });

    // Customize controls for smooth interaction
    const controls = globe.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.3;
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    controls.rotateSpeed = 0.6;
    controls.zoomSpeed = 0.8;
    controls.minDistance = 120;
    controls.maxDistance = 600;

    // Stop auto-rotate on user interaction
    const container = containerRef.current;
    const stopAutoRotate = () => {
      controls.autoRotate = false;
    };
    container.addEventListener("mousedown", stopAutoRotate);
    container.addEventListener("touchstart", stopAutoRotate);

    globeRef.current = globe;
    setIsLoaded(true);

    // Handle resize
    const handleResize = () => {
      if (globeRef.current) {
        globeRef.current.width(window.innerWidth);
        globeRef.current.height(window.innerHeight);
      }
    };
    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      container.removeEventListener("mousedown", stopAutoRotate);
      container.removeEventListener("touchstart", stopAutoRotate);
    };
  }, []);

  useEffect(() => {
    initGlobe();
    return () => {
      if (globeRef.current) {
        globeRef.current._destructor();
        globeRef.current = null;
      }
    };
  }, [initGlobe]);

  // Update points data when it changes
  useEffect(() => {
    if (globeRef.current && isLoaded) {
      globeRef.current.pointsData(points);
    }
  }, [points, isLoaded]);

  return (
    <div className="fixed inset-0 z-0">
      {/* Radial gradient vignette overlay */}
      <div
        className="pointer-events-none absolute inset-0 z-10"
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 40%, rgba(3, 7, 18, 0.6) 100%)",
        }}
      />
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
}
